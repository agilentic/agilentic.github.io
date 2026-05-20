import hashlib
import random
import numpy as np
import pandas as pd
from typing import Callable

try:
    from deap import base, creator, tools, algorithms
    DEAP_AVAILABLE = True
except ImportError:
    DEAP_AVAILABLE = False


class SubsetOptimizer:
    def __init__(
        self,
        feature_names: list[str],
        relevance_scores: dict[str, float],
        redundancy_fn: Callable,
        synergy_fn: Callable,
        stability_fn: Callable,
        portfolio_fn: Callable,
        subset_size_min: int = 3,
        subset_size_max: int = 10,
        population_size: int = 50,
        n_generations: int = 20,
        seed: int = 42,
        progress_callback: Callable | None = None,
    ):
        self.feature_names = feature_names
        self.n_features = len(feature_names)
        self.relevance_scores = relevance_scores
        self.redundancy_fn = redundancy_fn
        self.synergy_fn = synergy_fn
        self.stability_fn = stability_fn
        self.portfolio_fn = portfolio_fn
        self.subset_size_min = subset_size_min
        self.subset_size_max = subset_size_max
        self.population_size = population_size
        self.n_generations = n_generations
        self.seed = seed
        self.progress_callback = progress_callback
        self._eval_cache: dict[str, tuple] = {}

    def _chromosome_to_features(self, chromosome) -> list[str]:
        return [self.feature_names[i] for i, bit in enumerate(chromosome) if bit]

    def _cache_key(self, chromosome) -> str:
        return hashlib.md5(bytes(chromosome)).hexdigest()

    def _evaluate(self, individual) -> tuple:
        key = self._cache_key(individual)
        if key in self._eval_cache:
            return self._eval_cache[key]
        features = self._chromosome_to_features(individual)
        if len(features) < self.subset_size_min or len(features) > self.subset_size_max:
            result = (0.0, 0.0, 1.0, 0.0, 0.0, float(len(features)))
            self._eval_cache[key] = result
            return result
        rel = np.mean([self.relevance_scores.get(f, 0) for f in features])
        syn = self.synergy_fn(features)
        red = self.redundancy_fn(features)
        sta = self.stability_fn(features)
        port = self.portfolio_fn(features)
        comp = len(features)
        result = (float(rel), float(syn), float(red), float(sta), float(port), float(comp))
        self._eval_cache[key] = result
        return result

    def run(self) -> list[dict]:
        if not DEAP_AVAILABLE:
            return self._run_random_search()
        random.seed(self.seed)
        np.random.seed(self.seed)
        if "FitnessMulti" not in dir(creator):
            creator.create("FitnessMulti", base.Fitness, weights=(1.0, 1.0, -1.0, 1.0, 1.0, -0.1))
        if "Individual" not in dir(creator):
            creator.create("Individual", list, fitness=creator.FitnessMulti)
        tb = base.Toolbox()
        tb.register("attr_bool", random.randint, 0, 1)
        tb.register("individual", tools.initRepeat, creator.Individual, tb.attr_bool, self.n_features)
        tb.register("population", tools.initRepeat, list, tb.individual)
        tb.register("evaluate", self._evaluate)
        tb.register("mate", tools.cxUniform, indpb=0.3)
        tb.register("mutate", tools.mutFlipBit, indpb=1.0 / self.n_features)
        tb.register("select", tools.selNSGA2)
        pop = tb.population(n=self.population_size)
        fitnesses = list(map(tb.evaluate, pop))
        for ind, fit in zip(pop, fitnesses):
            ind.fitness.values = fit
        for gen in range(self.n_generations):
            offspring = tools.selTournamentDCD(pop, len(pop))
            offspring = algorithms.varAnd(offspring, tb, cxpb=0.7, mutpb=0.2)
            invalid = [ind for ind in offspring if not ind.fitness.valid]
            fits = list(map(tb.evaluate, invalid))
            for ind, fit in zip(invalid, fits):
                ind.fitness.values = fit
            pop = tb.select(pop + offspring, self.population_size)
            if self.progress_callback:
                self.progress_callback(gen + 1, self.n_generations, pop)
        return self._extract_results(pop)

    def _run_random_search(self) -> list[dict]:
        rng = np.random.default_rng(self.seed)
        results = []
        for _ in range(min(50, self.population_size * self.n_generations)):
            k = rng.integers(self.subset_size_min, self.subset_size_max + 1)
            chosen = rng.choice(self.feature_names, size=k, replace=False).tolist()
            rel = float(np.mean([self.relevance_scores.get(f, 0) for f in chosen]))
            results.append({"feature_names": chosen, "relevance_score": rel, "synergy_score": 0.5, "composite_score": rel, "pareto_rank": 1})
        results.sort(key=lambda x: x["composite_score"], reverse=True)
        return results[:20]

    def _extract_results(self, population) -> list[dict]:
        pareto = tools.sortNondominated(population, len(population), first_front_only=False)
        results = []
        for rank, front in enumerate(pareto[:5]):
            for ind in front:
                features = self._chromosome_to_features(ind)
                if len(features) < self.subset_size_min:
                    continue
                fit = ind.fitness.values
                composite = sum(w * v for w, v in zip([1, 1, -1, 1, 1, -0.1], fit)) / 6
                results.append({
                    "feature_names": features,
                    "subset_size": len(features),
                    "relevance_score": fit[0],
                    "synergy_score": fit[1],
                    "redundancy_score": fit[2],
                    "stability_score": fit[3],
                    "portfolio_score": fit[4],
                    "composite_score": float(composite),
                    "pareto_rank": rank + 1,
                })
        results.sort(key=lambda x: x["composite_score"], reverse=True)
        return results[:30]
