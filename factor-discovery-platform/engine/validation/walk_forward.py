import numpy as np
import pandas as pd
from typing import List, Tuple


class WalkForwardValidator:
    def __init__(
        self,
        dates: pd.Index,
        n_splits: int = 5,
        train_size: float = 0.6,
        gap: int = 20,
    ):
        self.dates = sorted(dates.unique())
        self.n_splits = n_splits
        self.train_size = train_size
        self.gap = gap

    def get_splits(self) -> List[Tuple[np.ndarray, np.ndarray]]:
        n = len(self.dates)
        dates_arr = np.array(self.dates)
        splits = []
        fold_size = n // (self.n_splits + 1)
        for i in range(self.n_splits):
            train_end = int(n * self.train_size) + i * fold_size // self.n_splits
            test_start = train_end + self.gap
            test_end = min(test_start + fold_size, n)
            if test_start >= n or test_end <= test_start:
                continue
            splits.append((dates_arr[:train_end], dates_arr[test_start:test_end]))
        return splits

    def compute_stability_score(self, ic_series: pd.Series) -> float:
        if len(ic_series) < 3:
            return 0.5
        signs = np.sign(ic_series.dropna())
        flip_rate = (signs.diff().abs() > 0).mean()
        cv = ic_series.std() / (abs(ic_series.mean()) + 1e-8)
        cv_penalty = min(cv / 3, 1.0)
        consistency = ic_series.mean() / (ic_series.std() + 1e-8)
        score = 0.4 * (1 - flip_rate) + 0.3 * (1 - cv_penalty) + 0.3 * min(abs(consistency) / 2, 1.0)
        return float(np.clip(score, 0, 1))
