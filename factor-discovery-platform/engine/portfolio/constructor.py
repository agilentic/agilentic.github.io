import numpy as np
import pandas as pd
from engine.utils.math_utils import sharpe_ratio, max_drawdown, cross_sectional_ic


class PortfolioAgent:
    def __init__(self, df: pd.DataFrame, target_col: str = "target_return_1d"):
        self.df = df
        self.target_col = target_col

    def combine_signals(self, feature_names: list[str], method: str = "ic") -> pd.Series:
        valid = [f for f in feature_names if f in self.df.columns]
        if not valid:
            return pd.Series(dtype=float)
        features = self.df[valid].fillna(0)
        if method == "equal":
            return features.mean(axis=1)
        target = self.df[self.target_col] if self.target_col in self.df.columns else None
        if target is None or method == "equal":
            return features.mean(axis=1)
        dates = features.index.get_level_values("date").unique()
        ic_weights = {}
        for col in valid:
            ic_series = cross_sectional_ic(features[col], target, dates)
            ic_weights[col] = abs(ic_series.mean()) if len(ic_series) > 0 else 0.0
        total = sum(ic_weights.values())
        if total == 0:
            return features.mean(axis=1)
        weights = {k: v / total for k, v in ic_weights.items()}
        return sum(features[col] * w for col, w in weights.items())

    def backtest_long_short_features(
        self,
        feature_names: list[str],
        method: str = "ic",
        n_quantiles: int = 10,
    ) -> dict:
        signal = self.combine_signals(feature_names, method)
        if signal.empty:
            return self._empty_metrics()
        return self._backtest_signal(signal, n_quantiles)

    def _backtest_signal(self, signal: pd.Series, n_quantiles: int = 10) -> dict:
        target = self.df[self.target_col] if self.target_col in self.df.columns else None
        if target is None:
            return self._empty_metrics()
        dates = signal.index.get_level_values("date").unique()
        daily_returns = []
        date_list = []
        for d in dates:
            try:
                s = signal.xs(d, level="date")
                t = target.xs(d, level="date")
            except KeyError:
                continue
            combined = pd.concat([s, t], axis=1).dropna()
            if len(combined) < n_quantiles * 2:
                continue
            combined.columns = ["signal", "ret"]
            combined["q"] = pd.qcut(combined["signal"], n_quantiles, labels=False, duplicates="drop")
            top = combined[combined["q"] == combined["q"].max()]["ret"].mean()
            bot = combined[combined["q"] == combined["q"].min()]["ret"].mean()
            if np.isfinite(top) and np.isfinite(bot):
                daily_returns.append(top - bot)
                date_list.append(d)
        if not daily_returns:
            return self._empty_metrics()
        rets = np.array(daily_returns)
        cum = np.cumprod(1 + rets)
        dd_series = (cum - np.maximum.accumulate(cum)) / (np.maximum.accumulate(cum) + 1e-10)
        ann_ret = float(np.prod(1 + rets) ** (252 / len(rets)) - 1)
        ann_vol = float(rets.std() * np.sqrt(252))
        sharpe = sharpe_ratio(rets)
        mdd = max_drawdown(rets)
        sortino_d = rets[rets < 0].std() if (rets < 0).any() else 1e-8
        sortino = float(rets.mean() / (sortino_d + 1e-8) * np.sqrt(252))
        hit_rate = float((rets > 0).mean())
        calmar = float(ann_ret / (abs(mdd) + 1e-8))
        ir = float(rets.mean() / (rets.std() + 1e-8) * np.sqrt(252))
        return {
            "sharpe": sharpe, "sortino": sortino, "max_drawdown": mdd,
            "annualized_return": ann_ret, "annualized_vol": ann_vol,
            "hit_rate": hit_rate, "calmar": calmar, "information_ratio": ir,
            "decile_spread": float(rets.mean()),
            "returns_ts": rets.tolist(), "cumulative_returns_ts": cum.tolist(),
            "drawdown_ts": dd_series.tolist(),
            "dates_ts": [str(d) for d in date_list],
        }

    def _empty_metrics(self) -> dict:
        return {"sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0,
                "annualized_return": 0.0, "annualized_vol": 0.0,
                "hit_rate": 0.5, "calmar": 0.0, "information_ratio": 0.0,
                "decile_spread": 0.0}
