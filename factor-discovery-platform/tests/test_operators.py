import numpy as np
import pandas as pd
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.factors.operators import (
    lag, diff, pct_change, rolling_mean, rolling_std,
    rolling_zscore, decay_linear, ema_transform, rsi,
    rank_transform, winsorize_series, OperatorCatalog,
)


def make_panel(n_tickers=5, n_dates=50, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="B")
    tickers = [f"T{i}" for i in range(n_tickers)]
    idx = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])
    return pd.Series(rng.standard_normal(len(idx)) + 100, index=idx, name="close")


def test_lag_shifts_values():
    s = make_panel()
    lagged = lag(s, 1)
    t0 = s.xs("T0", level="ticker")
    l0 = lagged.xs("T0", level="ticker")
    pd.testing.assert_series_equal(t0.iloc[:-1].values, l0.iloc[1:].values, check_names=False)


def test_lag_first_value_is_nan():
    s = make_panel()
    lagged = lag(s, 1)
    assert lagged.xs("T0", level="ticker").iloc[0] is np.nan or np.isnan(lagged.xs("T0", level="ticker").iloc[0])


def test_diff_same_shape():
    s = make_panel()
    result = diff(s, 1)
    assert result.shape == s.shape


def test_pct_change_range():
    s = make_panel()
    pct = pct_change(s, 1).dropna()
    assert (pct.abs() < 10).all()


def test_rolling_mean_no_nan_after_warmup():
    s = make_panel()
    rm = rolling_mean(s, 5)
    per_ticker = rm.xs("T0", level="ticker")
    assert per_ticker.iloc[4:].notna().all()


def test_rolling_std_nonnegative():
    s = make_panel()
    rs = rolling_std(s, 5).dropna()
    assert (rs >= 0).all()


def test_rolling_zscore_mean_zero():
    s = make_panel(n_dates=100)
    zs = rolling_zscore(s, 20).dropna()
    assert abs(zs.mean()) < 1.0


def test_decay_linear_shape():
    s = make_panel()
    result = decay_linear(s, 5)
    assert result.shape == s.shape


def test_ema_transform_smooth():
    s = make_panel()
    ema = ema_transform(s, span=5)
    assert ema.shape == s.shape
    assert ema.dropna().std() <= s.dropna().std()


def test_rsi_range():
    s = make_panel(n_dates=60)
    r = rsi(s, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_rank_transform_range():
    s = make_panel()
    rt = rank_transform(s).dropna()
    assert (rt >= 0).all() and (rt <= 1).all()


def test_winsorize_clips_extremes():
    s = pd.Series([0.01, 0.5, 0.99, -0.01, -0.5, -0.99, 100, -100])
    ws = winsorize_series(s, 0.1, 0.9)
    assert ws.max() <= s.quantile(0.9) + 1e-9
    assert ws.min() >= s.quantile(0.1) - 1e-9


class TestOperatorCatalog:
    def setup_method(self):
        self.catalog = OperatorCatalog()

    def test_get_catalog_returns_categories(self):
        cat = self.catalog.get_catalog()
        assert "categories" in cat
        assert cat["total"] > 10

    def test_validate_valid_expression(self):
        result = self.catalog.validate_expression("rolling_zscore(close, 20)")
        assert result["valid"] is True
        assert "complexity" in result

    def test_validate_invalid_syntax(self):
        result = self.catalog.validate_expression("def foo(:")
        assert result["valid"] is False
        assert "error" in result

    def test_validate_blocks_forbidden_tokens(self):
        result = self.catalog.validate_expression("import os; os.system('rm -rf /')")
        assert result["valid"] is False

    def test_validate_depth(self):
        result = self.catalog.validate_expression("rolling_zscore(rolling_mean(close, 20), 5)")
        assert result["valid"] is True
        assert result["depth"] >= 2
