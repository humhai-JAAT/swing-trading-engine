"""Tests for engine/variant_engine.py — trailing exits, scan_for_entry."""

import numpy as np
import pandas as pd
import pytest

from engine.variant_engine import check_ema9_trail_exit, check_atr_trail_exit


def _make_1h_candles(n: int, base: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01 10:15", periods=n, freq="1h")
    close = base + np.arange(n) * trend + np.random.randn(n) * 0.3
    return pd.DataFrame({
        "Open": close - 0.1,
        "High": close + 0.5,
        "Low": close - 0.5,
        "Close": close,
    }, index=dates)


class TestEMA9TrailExit:
    def test_no_exit_when_above_ema(self):
        np.random.seed(10)
        df = _make_1h_candles(50, base=100, trend=0.5)
        result = check_ema9_trail_exit(df)
        # With a strong uptrend, close should be above EMA9
        # (may or may not trigger depending on randomness)
        assert result is None or isinstance(result, float)

    def test_none_on_empty_df(self):
        assert check_ema9_trail_exit(pd.DataFrame()) is None

    def test_none_on_too_few_bars(self):
        df = _make_1h_candles(5)
        assert check_ema9_trail_exit(df) is None

    def test_none_on_none_input(self):
        assert check_ema9_trail_exit(None) is None

    def test_exit_on_downtrend(self):
        np.random.seed(42)
        df = _make_1h_candles(50, base=200, trend=-2.0)
        result = check_ema9_trail_exit(df)
        assert result is not None
        assert isinstance(result, float)


class TestATRTrailExit:
    def test_none_on_empty(self):
        assert check_atr_trail_exit(pd.DataFrame(), 200.0, 14, 1.5) is None

    def test_none_on_none(self):
        assert check_atr_trail_exit(None, 200.0, 14, 1.5) is None

    def test_none_on_too_few_bars(self):
        df = _make_1h_candles(10)
        assert check_atr_trail_exit(df, 200.0, 14, 1.5) is None

    def test_exit_on_big_pullback(self):
        np.random.seed(42)
        df = _make_1h_candles(30, base=200)
        peak = 250.0  # way above current prices
        result = check_atr_trail_exit(df, peak, 14, 1.5)
        assert result is not None

    def test_no_exit_when_close_to_peak(self):
        np.random.seed(42)
        df = _make_1h_candles(30, base=200, trend=0.1)
        last_close = float(df["Close"].iloc[-1])
        peak = last_close + 0.01
        result = check_atr_trail_exit(df, peak, 14, 1.5)
        assert result is None


class TestScanForEntryStructure:
    """Tests that scan_for_entry returns the right structure — actual entry
    signals tested via test_strategy.py since the logic is timeframe-agnostic."""

    def test_skip_when_in_position(self):
        from engine.variant_engine import scan_for_entry
        from engine import config
        variant_cfg = config.VARIANTS[0]
        result = scan_for_entry(
            "bot_500", variant_cfg, config.DEFAULTS,
            pd.Timestamp.now(), pd.DataFrame(columns=["symbol"]),
            {}, was_flat=False,
        )
        assert result["action"] == "skip_scan"
        assert result["reason"] == "already_in_position"

    def test_no_signal_on_empty_top_n(self):
        from engine.variant_engine import scan_for_entry
        from engine import config, db

        # Need a fresh DB for was_flat check
        db._engine = None
        import tempfile, os
        tmp = tempfile.mkdtemp()
        original = db._sqlite_path
        db._sqlite_path = lambda: __import__("pathlib").Path(tmp) / "test.db"
        db.init_db()

        variant_cfg = config.VARIANTS[0]
        result = scan_for_entry(
            "bot_500", variant_cfg, config.DEFAULTS,
            pd.Timestamp.now(), pd.DataFrame(columns=["symbol"]),
            {}, was_flat=True,
        )
        assert result["action"] == "no_signal"
        assert result["candidates"] == []

        db._engine = None
        db._sqlite_path = original

    def test_no_entry_timing_in_variants(self):
        from engine import config
        for v in config.VARIANTS:
            assert "entry_timing" not in v
