import numpy as np
import pandas as pd
from scipy import stats
from engine.utils.math_utils import distance_correlation, cross_sectional_ic


class RelevanceAgent:
    def __init__(self, features_df: pd.DataFrame, target: pd.Series):
        self.features = features_df
        self.target = target
        self.dates = features_df.index.get_level_values("date").unique()

    def compute_ic(self, feature_name: str) -> float:
        ic_series = cross_sectional_ic(
            self.features[feature_name], self.target, self.dates
        )
        return float(ic_series.mean()) if len(ic_series) > 0 else 0.0

    def compute_icir(self, feature_name: str) -> float:
        ic_series = cross_sectional_ic(
            self.features[feature_name], self.target, self.dates
        )
        if len(ic_series) < 5:
            return 0.0
        return float(ic_series.mean() / (ic_series.std() + 1e-8))

    def compute_distance_correlation(self, feature_name: str) -> float:
        x = self.features[feature_name].values
        y = self.target.reindex(self.features.index).values
        return distance_correlation(x, y)

    def evaluate_all(self) -> pd.DataFrame:
        records = []
        for col in self.features.columns:
            ic = self.compute_ic(col)
            icir = self.compute_icir(col)
            dcorr = self.compute_distance_correlation(col)
            composite = 0.40 * abs(ic) + 0.30 * abs(icir) / 3 + 0.30 * dcorr
            records.append({
                "feature": col,
                "ic": ic,
                "icir": icir,
                "distance_corr": dcorr,
                "relevance_score": composite,
            })
        return pd.DataFrame(records).set_index("feature")
