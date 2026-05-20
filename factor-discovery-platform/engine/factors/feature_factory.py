import pandas as pd
import numpy as np
from engine.factors.operators import (
    lag, diff, pct_change, rolling_mean, rolling_std,
    rolling_min, rolling_max, rolling_rank, rolling_zscore,
    decay_linear, ema_transform, rsi, rank_transform, winsorize_series,
)


class FeatureFactoryAgent:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self._check_index()

    def _check_index(self):
        if not isinstance(self.df.index, pd.MultiIndex):
            if "date" in self.df.columns and "ticker" in self.df.columns:
                self.df = self.df.set_index(["date", "ticker"])
            else:
                raise ValueError("DataFrame must have (date, ticker) MultiIndex")

    def _apply(self, fn, col, *args, name: str | None = None) -> pd.Series | None:
        if col not in self.df.columns:
            return None
        try:
            result = fn(self.df[col], *args)
            result.name = name or f"{fn.__name__}_{col}"
            return result
        except Exception:
            return None

    def generate_primitive_features(self, config: dict | None = None) -> pd.DataFrame:
        features: dict[str, pd.Series] = {}

        def add(s: pd.Series | None):
            if s is not None and not s.isna().all():
                features[s.name] = s

        for col in ["close", "volume", "high", "low", "open"]:
            for w in [5, 10, 20, 60]:
                add(self._apply(rolling_mean, col, w, name=f"rmean_{col}_{w}"))
                add(self._apply(rolling_std, col, w, name=f"rstd_{col}_{w}"))
            for n in [1, 5, 20]:
                add(self._apply(diff, col, n, name=f"diff_{col}_{n}"))
                add(self._apply(pct_change, col, n, name=f"ret_{col}_{n}"))
            for w in [10, 20]:
                add(self._apply(rolling_zscore, col, w, name=f"zscore_{col}_{w}"))
                add(self._apply(decay_linear, col, w, name=f"decay_{col}_{w}"))

        for col in ["close"]:
            for w in [7, 14, 21]:
                add(self._apply(rsi, col, w, name=f"rsi_{col}_{w}"))
            for span in [5, 12, 26]:
                add(self._apply(ema_transform, col, span, name=f"ema_{col}_{span}"))
            add(self._apply(rank_transform, col, name=f"xrank_{col}"))

        df_features = pd.concat(features, axis=1)
        return df_features
