import numpy as np
import pandas as pd
from typing import Callable


class Orchestrator:
    def __init__(self, experiment_id: str, config: dict, progress_callback: Callable | None = None):
        self.experiment_id = experiment_id
        self.config = config
        self.progress_callback = progress_callback

    def _emit(self, phase: str, pct: float, msg: str = ""):
        if self.progress_callback:
            self.progress_callback({"phase": phase, "progress": pct, "message": msg})

    def run(self) -> dict:
        from api.app.core.config import settings
        import os

        self._emit("init", 0.02, "Loading data")
        # Load dataset
        dataset_id = self.config.get("dataset_id")
        if not dataset_id:
            raise ValueError("dataset_id not in config")

        # Synchronous DB access for worker context
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as SyncSession
        from api.app.models.models import Dataset, Experiment, Subset, GenerationRecord
        sync_engine = create_engine(settings.sync_database_url)

        with SyncSession(sync_engine) as db:
            ds = db.get(Dataset, dataset_id)
            if not ds or not ds.file_path:
                raise ValueError("Dataset not found or no file")
            df = pd.read_parquet(ds.file_path) if ds.file_path.endswith(".parquet") else pd.read_csv(ds.file_path)
            if "date" in df.columns and "ticker" in df.columns:
                df = df.set_index(["date", "ticker"])

        self._emit("features", 0.10, "Generating features")
        from engine.factors.feature_factory import FeatureFactoryAgent
        factory = FeatureFactoryAgent(df)
        features_df = factory.generate_primitive_features()

        target_col = self.config.get("target_col", "target_return_1d")
        if target_col not in df.columns:
            raise ValueError(f"Target column {target_col} not found")
        target = df[target_col].reindex(features_df.index)

        self._emit("relevance", 0.25, "Computing relevance scores")
        from engine.metrics.relevance import RelevanceAgent
        rel_agent = RelevanceAgent(features_df, target)
        rel_df = rel_agent.evaluate_all()
        top_features = rel_df.nlargest(50, "relevance_score").index.tolist()

        self._emit("redundancy", 0.35, "Building redundancy matrix")
        from engine.metrics.redundancy import RedundancyAgent
        red_agent = RedundancyAgent(features_df[top_features])

        self._emit("synergy", 0.45, "Computing synergy")
        from engine.metrics.synergy import SynergyAgent
        syn_agent = SynergyAgent(features_df[top_features], target)

        self._emit("ga", 0.50, "Running NSGA-II")
        from engine.validation.walk_forward import WalkForwardValidator
        dates = features_df.index.get_level_values("date").unique()
        wfv = WalkForwardValidator(dates)

        def stability_fn(feat_names):
            valid = [f for f in feat_names if f in features_df.columns]
            if not valid:
                return 0.5
            from engine.utils.math_utils import cross_sectional_ic
            combined = features_df[valid].mean(axis=1)
            ic_series = cross_sectional_ic(combined, target, dates)
            return wfv.compute_stability_score(ic_series)

        from engine.portfolio.constructor import PortfolioAgent
        port_agent = PortfolioAgent(df, target_col=target_col)

        gen_records = []

        def ga_progress(gen_num, total_gens, pop):
            pct = 0.50 + 0.40 * (gen_num / total_gens)
            self._emit("ga", pct, f"Generation {gen_num}/{total_gens}")
            fits = [ind.fitness.values for ind in pop if ind.fitness.valid]
            if fits:
                arr = np.array(fits)
                gen_records.append({
                    "generation_num": gen_num,
                    "best_fitness": {"relevance": float(arr[:, 0].max()), "synergy": float(arr[:, 1].max()), "stability": float(arr[:, 3].max())},
                    "mean_fitness": {"relevance": float(arr[:, 0].mean()), "synergy": float(arr[:, 1].mean())},
                    "diversity": float(arr[:, 0].std()),
                    "pareto_front_size": sum(1 for ind in pop if hasattr(ind, "fitness") and ind.fitness.valid),
                })

        from engine.optimization.ga_optimizer import SubsetOptimizer
        optimizer = SubsetOptimizer(
            feature_names=top_features,
            relevance_scores=rel_df["relevance_score"].to_dict(),
            redundancy_fn=red_agent.get_redundancy_for_subset,
            synergy_fn=lambda f: syn_agent.compute_synergy_score(f[0], f[1:]) if len(f) > 1 else 0.5,
            stability_fn=stability_fn,
            portfolio_fn=lambda f: port_agent.backtest_long_short_features(f, method="ic").get("sharpe", 0) / 3,
            subset_size_min=self.config.get("subset_size_min", 3),
            subset_size_max=self.config.get("subset_size_max", 10),
            population_size=self.config.get("population_size", 50),
            n_generations=self.config.get("n_generations", 20),
            seed=self.config.get("seed", 42),
            progress_callback=ga_progress,
        )
        results = optimizer.run()

        self._emit("save", 0.92, "Saving results")
        with SyncSession(sync_engine) as db:
            exp = db.get(Experiment, self.experiment_id)
            if exp:
                for rec in gen_records:
                    gr = GenerationRecord(experiment_id=self.experiment_id, **rec)
                    db.add(gr)
                for i, r in enumerate(results[:20]):
                    subset = Subset(
                        experiment_id=self.experiment_id,
                        rank=i + 1,
                        feature_names=r["feature_names"],
                        subset_size=r.get("subset_size", len(r["feature_names"])),
                        relevance_score=r.get("relevance_score"),
                        redundancy_score=r.get("redundancy_score"),
                        synergy_score=r.get("synergy_score"),
                        stability_score=r.get("stability_score"),
                        portfolio_score=r.get("portfolio_score"),
                        composite_score=r.get("composite_score"),
                        pareto_rank=r.get("pareto_rank", 1),
                    )
                    db.add(subset)
                db.commit()

        self._emit("done", 1.0, "Complete")
        best = results[0] if results else {}
        return {
            "summary": {
                "n_features_evaluated": len(top_features),
                "n_subsets_found": len(results),
                "best_composite_score": best.get("composite_score", 0),
                "best_relevance": best.get("relevance_score", 0),
                "best_synergy": best.get("synergy_score", 0),
            }
        }
