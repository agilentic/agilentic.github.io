import numpy as np
import pandas as pd
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.validation.walk_forward import WalkForwardValidator


def make_dates(n=500):
    return pd.date_range("2020-01-01", periods=n, freq="B")


class TestWalkForwardValidator:
    def test_correct_number_of_splits(self):
        dates = make_dates(500)
        wfv = WalkForwardValidator(dates, n_splits=5, train_size=0.6, gap=20)
        splits = wfv.get_splits()
        assert len(splits) > 0
        assert len(splits) <= 5

    def test_no_overlap_between_train_and_test(self):
        dates = make_dates(500)
        wfv = WalkForwardValidator(dates, n_splits=5, train_size=0.6, gap=20)
        for train_dates, test_dates in wfv.get_splits():
            train_set = set(train_dates.tolist())
            test_set = set(test_dates.tolist())
            assert len(train_set & test_set) == 0

    def test_gap_enforced(self):
        dates = make_dates(500)
        gap = 20
        wfv = WalkForwardValidator(dates, n_splits=5, train_size=0.6, gap=gap)
        for train_dates, test_dates in wfv.get_splits():
            assert test_dates[0] > train_dates[-1]

    def test_strictly_increasing(self):
        dates = make_dates(300)
        wfv = WalkForwardValidator(dates, n_splits=3, train_size=0.5, gap=10)
        splits = wfv.get_splits()
        for i in range(1, len(splits)):
            prev_train_end = splits[i - 1][0][-1]
            curr_train_end = splits[i][0][-1]
            assert curr_train_end >= prev_train_end

    def test_stability_score_range(self):
        dates = make_dates(200)
        wfv = WalkForwardValidator(dates, n_splits=5)
        ic_series = pd.Series(np.random.randn(30) * 0.05 + 0.02)
        score = wfv.compute_stability_score(ic_series)
        assert 0.0 <= score <= 1.0

    def test_stability_score_consistent_positive(self):
        dates = make_dates(200)
        wfv = WalkForwardValidator(dates, n_splits=5)
        ic_series = pd.Series(np.full(30, 0.05))
        score = wfv.compute_stability_score(ic_series)
        assert score > 0.5

    def test_stability_score_noisy(self):
        dates = make_dates(200)
        wfv = WalkForwardValidator(dates, n_splits=5)
        ic_series = pd.Series(np.array([0.1, -0.1, 0.1, -0.1, 0.1, -0.1]))
        score_noisy = wfv.compute_stability_score(ic_series)
        ic_stable = pd.Series(np.full(6, 0.05))
        score_stable = wfv.compute_stability_score(ic_stable)
        assert score_stable > score_noisy

    def test_stability_score_short_series(self):
        dates = make_dates(200)
        wfv = WalkForwardValidator(dates)
        score = wfv.compute_stability_score(pd.Series([0.05]))
        assert score == 0.5
