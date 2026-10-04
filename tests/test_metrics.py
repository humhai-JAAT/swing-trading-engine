"""Tests for engine/metrics.py and common/metrics.py."""

import pandas as pd
import pytest

from common.metrics import compute_portfolio_metrics, profit_factor, sqn, wilson_lower_bound_win_rate


class TestComputePortfolioMetrics:
    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["pnl"])
        result = compute_portfolio_metrics(df)
        assert result["total_trades"] == 0
        assert result["total_pnl"] == 0.0
        assert result["win_rate"] == 0.0

    def test_all_winners(self):
        df = pd.DataFrame({"pnl": [100, 200, 150]})
        result = compute_portfolio_metrics(df)
        assert result["total_trades"] == 3
        assert result["win_rate"] == 100.0
        assert result["total_pnl"] == 450.0
        assert result["profit_factor"] == float("inf")

    def test_mixed_trades(self):
        df = pd.DataFrame({"pnl": [100, -50, 200, -30]})
        result = compute_portfolio_metrics(df)
        assert result["total_trades"] == 4
        assert result["win_rate"] == 50.0
        assert result["total_pnl"] == 220.0
        assert result["profit_factor"] == pytest.approx(300 / 80, abs=0.01)

    def test_all_losers(self):
        df = pd.DataFrame({"pnl": [-100, -50]})
        result = compute_portfolio_metrics(df)
        assert result["total_trades"] == 2
        assert result["win_rate"] == 0.0
        assert result["profit_factor"] == 0.0


class TestProfitFactor:
    def test_no_losses(self):
        pnl = pd.Series([100, 200])
        assert profit_factor(pnl) == float("inf")

    def test_no_wins(self):
        pnl = pd.Series([-100, -50])
        assert profit_factor(pnl) == 0.0

    def test_normal(self):
        pnl = pd.Series([100, -50])
        assert profit_factor(pnl) == pytest.approx(2.0)

    def test_empty(self):
        pnl = pd.Series([], dtype=float)
        assert profit_factor(pnl) == 0.0


class TestSQN:
    def test_empty(self):
        pnl = pd.Series([], dtype=float)
        assert sqn(pnl) == 0.0

    def test_single_trade(self):
        pnl = pd.Series([100.0])
        result = sqn(pnl)
        assert result == 0.0

    def test_consistent_wins(self):
        pnl = pd.Series([100.0] * 20)
        result = sqn(pnl)
        assert result == 0.0  # 0 std dev -> returns 0

    def test_positive_sqn(self):
        pnl = pd.Series([100, 50, 80, 120, -20, 60, 90, 40, 110, 70])
        result = sqn(pnl)
        assert result > 0


class TestWilsonLowerBound:
    def test_no_trades(self):
        pnl = pd.Series([], dtype=float)
        assert wilson_lower_bound_win_rate(pnl) == 0.0

    def test_all_wins_small_sample(self):
        pnl = pd.Series([100, 200, 150])
        result = wilson_lower_bound_win_rate(pnl)
        assert result < 100.0
        assert result > 0.0

    def test_large_sample_all_wins(self):
        pnl = pd.Series([10.0] * 100)
        result = wilson_lower_bound_win_rate(pnl)
        assert result > 90.0
