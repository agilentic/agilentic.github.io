import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from engine.utils.math_utils import distance_correlation


class RedundancyAgent:
    def __init__(self, features_df: pd.DataFrame):
        self.features = features_df.fillna(0)
        self._corr_matrix: pd.DataFrame | None = None

    def get_correlation_matrix(self) -> pd.DataFrame:
        if self._corr_matrix is None:
            self._corr_matrix = self.features.corr(method="spearman").fillna(0)
        return self._corr_matrix

    def get_redundancy_for_subset(self, feature_names: list[str]) -> float:
        if len(feature_names) < 2:
            return 0.0
        valid = [f for f in feature_names if f in self.features.columns]
        if len(valid) < 2:
            return 0.0
        corr = self.get_correlation_matrix()
        sub = corr.loc[valid, valid]
        n = len(valid)
        off_diag = sub.values[np.triu_indices(n, k=1)]
        return float(np.abs(off_diag).mean())

    def get_clusters(self, n_clusters: int = 10) -> dict[str, int]:
        corr = self.get_correlation_matrix()
        dist = 1 - corr.abs()
        dist = dist.clip(0, 1)
        n_clusters = min(n_clusters, len(corr) - 1)
        if n_clusters < 2:
            return {col: 0 for col in corr.columns}
        model = AgglomerativeClustering(n_clusters=n_clusters, metric="precomputed", linkage="average")
        labels = model.fit_predict(dist.values)
        return dict(zip(corr.columns, labels.tolist()))
