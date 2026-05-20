import ast
import numpy as np
import pandas as pd
from typing import Any


def lag(s: pd.Series, n: int = 1) -> pd.Series:
    return s.groupby(level="ticker").shift(n)


def diff(s: pd.Series, n: int = 1) -> pd.Series:
    return s.groupby(level="ticker").diff(n)


def pct_change(s: pd.Series, n: int = 1) -> pd.Series:
    return s.groupby(level="ticker").pct_change(n)


def rolling_mean(s: pd.Series, w: int = 20) -> pd.Series:
    return s.groupby(level="ticker").transform(lambda x: x.rolling(w, min_periods=max(1, w // 2)).mean())


def rolling_std(s: pd.Series, w: int = 20) -> pd.Series:
    return s.groupby(level="ticker").transform(lambda x: x.rolling(w, min_periods=max(1, w // 2)).std())


def rolling_min(s: pd.Series, w: int = 20) -> pd.Series:
    return s.groupby(level="ticker").transform(lambda x: x.rolling(w, min_periods=1).min())


def rolling_max(s: pd.Series, w: int = 20) -> pd.Series:
    return s.groupby(level="ticker").transform(lambda x: x.rolling(w, min_periods=1).max())


def rolling_rank(s: pd.Series, w: int = 20) -> pd.Series:
    return s.groupby(level="ticker").transform(
        lambda x: x.rolling(w, min_periods=max(1, w // 2)).apply(
            lambda v: pd.Series(v).rank(pct=True).iloc[-1], raw=False
        )
    )


def zscore_normalize(s: pd.Series) -> pd.Series:
    return s.groupby(level="ticker").transform(lambda x: (x - x.mean()) / (x.std() + 1e-8))


def rolling_zscore(s: pd.Series, w: int = 20) -> pd.Series:
    rm = rolling_mean(s, w)
    rs = rolling_std(s, w)
    return (s - rm) / (rs + 1e-8)


def decay_linear(s: pd.Series, w: int = 10) -> pd.Series:
    weights = np.arange(1, w + 1, dtype=float)
    weights /= weights.sum()
    return s.groupby(level="ticker").transform(
        lambda x: x.rolling(w, min_periods=1).apply(
            lambda v: np.dot(v[-len(weights):], weights[-len(v):]) / weights[-len(v):].sum(), raw=True
        )
    )


def ema_transform(s: pd.Series, span: int = 10) -> pd.Series:
    return s.groupby(level="ticker").transform(lambda x: x.ewm(span=span, adjust=False).mean())


def rsi(s: pd.Series, w: int = 14) -> pd.Series:
    def _rsi(x: pd.Series) -> pd.Series:
        d = x.diff()
        gain = d.clip(lower=0).rolling(w, min_periods=1).mean()
        loss = (-d.clip(upper=0)).rolling(w, min_periods=1).mean()
        rs = gain / (loss + 1e-8)
        return 100 - 100 / (1 + rs)
    return s.groupby(level="ticker").transform(_rsi)


def rank_transform(s: pd.Series) -> pd.Series:
    return s.groupby(level="date").rank(pct=True)


def winsorize_series(s: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    lo = s.quantile(lower)
    hi = s.quantile(upper)
    return s.clip(lo, hi)


OPERATOR_MAP = {
    "lag": lag, "diff": diff, "pct_change": pct_change,
    "rolling_mean": rolling_mean, "rolling_std": rolling_std,
    "rolling_min": rolling_min, "rolling_max": rolling_max,
    "rolling_rank": rolling_rank, "zscore_normalize": zscore_normalize,
    "rolling_zscore": rolling_zscore, "decay_linear": decay_linear,
    "ema_transform": ema_transform, "rsi": rsi,
    "rank_transform": rank_transform, "winsorize_series": winsorize_series,
}

OPERATOR_CATALOG = {
    "Time Series": [
        {"name": "lag", "signature": "lag(series, n=1)", "description": "Lag a series by n periods", "category": "Time Series"},
        {"name": "diff", "signature": "diff(series, n=1)", "description": "First difference over n periods", "category": "Time Series"},
        {"name": "pct_change", "signature": "pct_change(series, n=1)", "description": "Percentage change over n periods", "category": "Time Series"},
        {"name": "decay_linear", "signature": "decay_linear(series, w=10)", "description": "Linearly decaying weighted average", "category": "Time Series"},
        {"name": "ema_transform", "signature": "ema_transform(series, span=10)", "description": "Exponential moving average", "category": "Time Series"},
    ],
    "Rolling Statistics": [
        {"name": "rolling_mean", "signature": "rolling_mean(series, w=20)", "description": "Rolling mean over w periods", "category": "Rolling Statistics"},
        {"name": "rolling_std", "signature": "rolling_std(series, w=20)", "description": "Rolling standard deviation", "category": "Rolling Statistics"},
        {"name": "rolling_min", "signature": "rolling_min(series, w=20)", "description": "Rolling minimum", "category": "Rolling Statistics"},
        {"name": "rolling_max", "signature": "rolling_max(series, w=20)", "description": "Rolling maximum", "category": "Rolling Statistics"},
        {"name": "rolling_rank", "signature": "rolling_rank(series, w=20)", "description": "Percentile rank within rolling window", "category": "Rolling Statistics"},
        {"name": "rolling_zscore", "signature": "rolling_zscore(series, w=20)", "description": "Z-score relative to rolling window", "category": "Rolling Statistics"},
    ],
    "Normalization": [
        {"name": "zscore_normalize", "signature": "zscore_normalize(series)", "description": "Z-score normalize the full series", "category": "Normalization"},
        {"name": "winsorize_series", "signature": "winsorize_series(series, lower=0.01, upper=0.99)", "description": "Clip outliers at quantile bounds", "category": "Normalization"},
        {"name": "rank_transform", "signature": "rank_transform(series)", "description": "Cross-sectional percentile rank by date", "category": "Normalization"},
    ],
    "Technical": [
        {"name": "rsi", "signature": "rsi(series, w=14)", "description": "Relative Strength Index", "category": "Technical"},
    ],
}


class OperatorCatalog:
    FORBIDDEN = {"import", "exec", "eval", "open", "os", "sys", "__"}

    def get_catalog(self) -> dict:
        total = sum(len(v) for v in OPERATOR_CATALOG.values())
        return {"categories": OPERATOR_CATALOG, "total": total}

    def validate_expression(self, expr: str) -> dict:
        for token in self.FORBIDDEN:
            if token in expr:
                return {"valid": False, "error": f"Forbidden token: {token}"}
        try:
            tree = ast.parse(expr, mode="eval")
            complexity = sum(1 for _ in ast.walk(tree))
            depth = self._tree_depth(tree)
            return {"valid": True, "complexity": complexity, "depth": depth}
        except SyntaxError as e:
            return {"valid": False, "error": str(e)}

    def _tree_depth(self, node: ast.AST, current: int = 0) -> int:
        children = list(ast.iter_child_nodes(node))
        if not children:
            return current
        return max(self._tree_depth(c, current + 1) for c in children)

    def evaluate_expression(self, expr: str, df: pd.DataFrame) -> pd.Series:
        for token in self.FORBIDDEN:
            if token in expr:
                raise ValueError(f"Forbidden: {token}")
        local_ns = {**OPERATOR_MAP, **{col: df[col] for col in df.columns}, "pd": pd, "np": np}
        result = eval(expr, {"__builtins__": {}}, local_ns)
        return result
