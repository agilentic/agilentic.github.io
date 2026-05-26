import numpy as np
import pandas as pd
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.factors.feature_factory import FeatureFactoryAgent
from engine.agents.data_agent import DataAgent


@pytest.fixture(scope="module")
def sample_df():
    agent = DataAgent()
    return agent.generate_sample_data(n_assets=10, n_days=120, seed=0)


@pytest.fixture(scope="module")
def features_df(sample_df):
    factory = FeatureFactoryAgent(sample_df)
    return factory.generate_primitive_features()


class TestFeatureFactory:
    def test_returns_dataframe(self, features_df):
        assert isinstance(features_df, pd.DataFrame)

    def test_has_multiindex(self, features_df):
        assert isinstance(features_df.index, pd.MultiIndex)
        assert features_df.index.names == ["date", "ticker"]

    def test_generates_many_features(self, features_df):
        assert len(features_df.columns) >= 30

    def test_no_all_nan_columns(self, features_df):
        all_nan = features_df.isna().all()
        assert not all_nan.any(), f"All-NaN columns: {all_nan[all_nan].index.tolist()}"

    def test_feature_names_include_rolling(self, features_df):
        rolling_cols = [c for c in features_df.columns if "rmean" in c or "rstd" in c]
        assert len(rolling_cols) > 0

    def test_feature_names_include_rsi(self, features_df):
        rsi_cols = [c for c in features_df.columns if "rsi" in c]
        assert len(rsi_cols) > 0

    def test_feature_names_include_zscore(self, features_df):
        zs_cols = [c for c in features_df.columns if "zscore" in c]
        assert len(zs_cols) > 0

    def test_requires_multiindex(self, sample_df):
        flat_df = sample_df.reset_index()
        factory = FeatureFactoryAgent(flat_df)
        features = factory.generate_primitive_features()
        assert isinstance(features, pd.DataFrame)


class TestDataAgent:
    def test_generates_correct_shape(self, sample_df):
        assert isinstance(sample_df, pd.MultiIndex if False else pd.DataFrame)
        assert len(sample_df) == 10 * 120

    def test_has_required_columns(self, sample_df):
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in sample_df.columns

    def test_has_target(self, sample_df):
        assert "target_return_1d" in sample_df.columns

    def test_prices_positive(self, sample_df):
        assert (sample_df["close"] > 0).all()

    def test_volume_positive(self, sample_df):
        assert (sample_df["volume"] > 0).all()
