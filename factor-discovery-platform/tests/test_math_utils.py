import numpy as np
import pandas as pd
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.utils.math_utils import (
    distance_correlation,
    conditional_mutual_information,
    cross_sectional_ic,
    sharpe_ratio,
    max_drawdown,
)


def test_distance_correlation_identical():
    x = np.random.randn(200)
    assert distance_correlation(x, x) > 0.95


def test_distance_correlation_independent():
    rng = np.random.default_rng(42)
    x = rng.standard_normal(500)
    y = rng.standard_normal(500)
    dcorr = distance_correlation(x, y, sample_size=500)
    assert dcorr < 0.3


def test_distance_correlation_nonlinear():
    x = np.linspace(-3, 3, 300)
    y = x ** 2
    dcorr = distance_correlation(x, y)
    pearson = abs(np.corrcoef(x, y)[0, 1])
    assert dcorr > pearson


def test_distance_correlation_with_nans():
    x = np.array([np.nan, 1.0, 2.0, 3.0, 4.0])
    y = np.array([1.0, np.nan, 2.0, 3.0, 4.0])
    result = distance_correlation(x, y)
    assert np.isfinite(result)


def test_distance_correlation_short():
    result = distance_correlation(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
    assert result == 0.0


def test_conditional_mutual_information_positive():
    rng = np.random.default_rng(0)
    n = 500
    z = rng.standard_normal(n)
    x = z + 0.5 * rng.standard_normal(n)
    y = z + 0.5 * rng.standard_normal(n)
    cmi = conditional_mutual_information(x, y, z)
    assert cmi >= 0.0


def test_cross_sectional_ic_perfect():
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    tickers = [f"T{i}" for i in range(20)]
    idx = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])
    rng = np.random.default_rng(1)
    target = pd.Series(rng.standard_normal(len(idx)), index=idx)
    feature = target + 0.01 * rng.standard_normal(len(idx))
    ic_series = cross_sectional_ic(feature, target, pd.Index(dates))
    assert ic_series.mean() > 0.9


def test_cross_sectional_ic_uncorrelated():
    dates = pd.date_range("2020-01-01", periods=20, freq="B")
    tickers = [f"T{i}" for i in range(30)]
    idx = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])
    rng = np.random.default_rng(99)
    target = pd.Series(rng.standard_normal(len(idx)), index=idx)
    feature = pd.Series(rng.standard_normal(len(idx)), index=idx)
    ic_series = cross_sectional_ic(feature, target, pd.Index(dates))
    assert abs(ic_series.mean()) < 0.3


def test_sharpe_ratio_positive():
    returns = np.full(252, 0.001)
    sharpe = sharpe_ratio(returns)
    assert sharpe > 0


def test_sharpe_ratio_zero_vol():
    returns = np.zeros(100)
    assert sharpe_ratio(returns) == 0.0


def test_max_drawdown_flat():
    returns = np.zeros(100)
    assert max_drawdown(returns) == 0.0


def test_max_drawdown_negative():
    returns = np.array([-0.1, -0.1, -0.1, 0.1, 0.1])
    mdd = max_drawdown(returns)
    assert mdd < 0


def test_max_drawdown_recovery():
    returns = np.array([0.1, -0.05, 0.1])
    mdd = max_drawdown(returns)
    assert mdd >= -0.05
