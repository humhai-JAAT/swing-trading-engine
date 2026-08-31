"""Tests for engine/strategy.py — EMA-MACD V2.1.2 entry logic."""

import numpy as np
import pandas as pd
import pytest

from engine.strategy import (
    MIN_BARS_REQUIRED,
    build_indicator_cache,
    build_indicators,
    check_entry,
    decide_entry,
)


def _make_candles(n: int, base_price: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01 09:15", periods=n, freq="1h")
    close = base_price + np.arange(n) * trend + np.random.randn(n) * 0.5
    return pd.DataFrame({
        "Open": close - 0.1,
        "High": close + 0.5,
        "Low": close - 0.5,
        "Close": close,
        "Volume": np.random.randint(1000, 10000, n),
    }, index=dates)


class TestBuildIndicators:
    def test_output_columns(self):
        df = _make_candles(150)
        result = build_indicators(df)
        for col in ["ema_fast", "ema_slow", "ema_trend", "ema_trend_sma",
                     "macd", "macd_signal", "ema_sep_pct", "armed",
                     "arm_cycle_id", "entry_signal"]:
            assert col in result.columns

    def test_preserves_original_columns(self):
        df = _make_candles(150)
        result = build_indicators(df)
        for col in ["Open", "High", "Low", "Close"]:
            assert col in result.columns

    def test_same_length(self):
        df = _make_candles(150)
        result = build_indicators(df)
        assert len(result) == len(df)

    def test_armed_is_boolean(self):
        df = _make_candles(150)
        result = build_indicators(df)
        assert result["armed"].dtype == bool

    def test_entry_signal_is_boolean(self):
        df = _make_candles(150)
        result = build_indicators(df)
        assert result["entry_signal"].dtype == bool


class TestDecideEntry:
    def test_insufficient_history(self):
        df = _make_candles(50)
        enriched = build_indicators(df)
        result = decide_entry(enriched)
        assert result.signal is False
        assert result.reason == "insufficient_history"

    def test_no_signal_on_random_data(self):
        np.random.seed(42)
        df = _make_candles(200)
        enriched = build_indicators(df)
        result = decide_entry(enriched)
        assert result.reason in ("no_signal", "signal_not_fresh", "entry",
                                  "arm_cycle_stale", "arm_cycle_already_used",
                                  "insufficient_history")

    def test_arm_cycle_already_used(self):
        np.random.seed(42)
        df = _make_candles(200, trend=0.05)
        enriched = build_indicators(df)
        result = decide_entry(enriched)
        if result.signal and result.arm_cycle_id is not None:
            used = {str(result.arm_cycle_id)}
            result2 = decide_entry(enriched, used_arm_cycles=used)
            assert result2.signal is False
            assert result2.reason == "arm_cycle_already_used"


class TestCheckEntry:
    def test_too_few_bars(self):
        df = _make_candles(10)
        result = check_entry(df)
        assert result.signal is False
        assert result.reason == "insufficient_history"

    def test_returns_entry_check(self):
        df = _make_candles(200)
        result = check_entry(df)
        assert hasattr(result, "signal")
        assert hasattr(result, "reason")
        assert hasattr(result, "close")
        assert hasattr(result, "arm_cycle_id")


class TestBuildIndicatorCache:
    def test_filters_short_candles(self):
        candles = {
            "SHORT": _make_candles(10),
            "LONG": _make_candles(200),
        }
        cache = build_indicator_cache(candles)
        assert "SHORT" not in cache
        assert "LONG" in cache

    def test_cache_has_indicators(self):
        candles = {"RELIANCE": _make_candles(200)}
        cache = build_indicator_cache(candles)
        assert "entry_signal" in cache["RELIANCE"].columns

    def test_empty_input(self):
        cache = build_indicator_cache({})
        assert cache == {}

    def test_none_values_skipped(self):
        candles = {"A": None, "B": _make_candles(200)}
        cache = build_indicator_cache(candles)
        assert "A" not in cache
        assert "B" in cache
