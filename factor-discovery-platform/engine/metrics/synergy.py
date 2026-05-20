import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import TimeSeriesSplit
from engine.utils.math_utils import conditional_mutual_information, cross_sectional_ic


class SynergyAgent:
    def __init__(self, features_df: pd.DataFrame, target: pd.Series):
        self.features = features_df.fillna(0)
        self.target = target.reindex(features_df.index).fillna(0)
        self.dates = features_df.index.get_level_values("date").unique()

    def compute_incremental_ic(self, feature_name: str, subset: list[str]) -> float:
        if feature_name not in self.features.columns:
            return 0.0
        base_ic = self._subset_mean_ic(subset)
        new_ic = self._subset_mean_ic(subset + [feature_name])
        return float(new_ic - base_ic)

    def _subset_mean_ic(self, feature_names: list[str]) -> float:
        valid = [f for f in feature_names if f in self.features.columns]
        if not valid:
            return 0.0
        combined = self.features[valid].mean(axis=1)
        ic_series = cross_sectional_ic(combined, self.target, self.dates)
        return float(ic_series.mean()) if len(ic_series) > 0 else 0.0

    def compute_cmi(self, feature_name: str, subset: list[str]) -> float:
        if feature_name not in self.features.columns or not subset:
            return 0.0
        x = self.features[feature_name].values
        y = self.target.values
        z_cols = [f for f in subset if f in self.features.columns]
        if not z_cols:
            return 0.0
        z = self.features[z_cols].mean(axis=1).values
        return conditional_mutual_information(x, y, z)

    def compute_synergy_score(self, feature_name: str, subset: list[str]) -> float:
        cmi = self.compute_cmi(feature_name, subset)
        inc_ic = self.compute_incremental_ic(feature_name, subset)
        score = 0.5 * min(cmi * 5, 1.0) + 0.5 * max(-1, min(1, inc_ic * 20))
        return float(max(0, score))

    def compute_subset_synergy_matrix(self, feature_names: list[str]) -> pd.DataFrame:
        n = len(feature_names)
        mat = np.zeros((n, n))
        for i, fi in enumerate(feature_names):
            for j, fj in enumerate(feature_names):
                if i != j:
                    subset = [feature_names[k] for k in range(n) if k != i and k != j][:3]
                    mat[i, j] = self.compute_cmi(fi, [fj] + subset)
        return pd.DataFrame(mat, index=feature_names, columns=feature_names)
