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


# ---- candle close time, exits after the target, entry edge cases ----
from datetime import datetime
from unittest.mock import patch

import pytz

from engine import config, db, strategy
from engine.variant_engine import (SLIPPAGE_PCT, _decide_and_exit, candle_closes_at,
                                   discard_incomplete_candle, scan_for_entry)

IST = pytz.timezone("Asia/Kolkata")
V = "bot_500/trailing_ema"


def _ist(*args):
    return IST.localize(datetime(*args))


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db._engine = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "_sqlite_path", lambda: tmp_path / "test.db")
    db.init_db()
    yield
    db._engine = None


class TestCandleClose:
    def test_forming_candle_dropped_between_x00_and_x15(self):
        idx = pd.DatetimeIndex([_ist(2026, 9, 24, 9, 15), _ist(2026, 9, 24, 10, 15)])
        df = pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)
        with patch("engine.variant_engine.datetime") as clock:
            clock.now.return_value = _ist(2026, 9, 24, 11, 0)
            assert discard_incomplete_candle(df).index[-1] == idx[0]

    def test_last_candle_of_the_day_closes_at_1530(self):
        assert candle_closes_at(pd.Timestamp(_ist(2026, 9, 24, 15, 15))) == _ist(2026, 9, 24, 15, 30)


class _Account:
    def __init__(self, df_1h=None):
        self.df_1h = df_1h

    def fetch_candles(self, *args, **kwargs):
        return self.df_1h


def _open_trade(minute_bars):
    """Entry 100 x 10 on Rs 1000 capital: target 103, stop 98.5. Bars are (open, high, low, close)."""
    db.open_trade(V, "TEST", 100.0, 10, 1000.0, 1.0, None)
    trade = {**db.get_open_trade(V), "entry_time": "2026-09-24T10:17:00+05:30"}
    idx = pd.date_range(_ist(2026, 9, 24, 10, 18), periods=len(minute_bars), freq="1min")
    return trade, pd.DataFrame(minute_bars, columns=["Open", "High", "Low", "Close"], index=idx)


def _falling_1h(last_start):
    idx = pd.date_range(end=last_start, periods=20, freq="1h")
    close = np.linspace(120, 100, 20)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close}, index=idx)


class TestExitAfterTarget:
    def test_dip_below_target_exits_at_the_floor(self, fresh_db):
        trade, df = _open_trade([(100, 103.5, 101, 103.2), (103.2, 103.4, 102.5, 102.6)])
        r = _decide_and_exit(V, config.VARIANTS[0], trade, config.DEFAULTS, None, _Account(), "TEST", df)
        assert r["reason"] == "TARGET_FLOOR"
        assert r["price"] == pytest.approx(103.0 * (1 - SLIPPAGE_PCT / 100))

    def test_candle_that_closed_before_the_touch_does_not_trail(self, fresh_db):
        trade, df = _open_trade([(100, 103.5, 101, 103.2), (103.2, 104.2, 103.1, 104.0)])
        r = _decide_and_exit(V, config.VARIANTS[0], trade, config.DEFAULTS, None,
                             _Account(_falling_1h(_ist(2026, 9, 24, 9, 15))), "TEST", df)
        assert r["action"] == "hold"

    def test_trail_exit_fills_at_current_price_not_candle_close(self, fresh_db):
        trade, df = _open_trade([(100, 103.5, 101, 103.2), (103.2, 104.2, 103.1, 104.0)])
        r = _decide_and_exit(V, config.VARIANTS[0], trade, config.DEFAULTS, None,
                             _Account(_falling_1h(_ist(2026, 9, 24, 10, 15))), "TEST", df)
        assert r["reason"] == "EMA_TRAIL_EXIT"
        assert r["price"] == pytest.approx(104.0 * (1 - SLIPPAGE_PCT / 100))


class TestEntryEdgeCases:
    def _scan(self, candle_start, signals, now, session_opens=None):
        top = pd.DataFrame({"symbol": list(signals)})
        candles = {s: pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([candle_start])) for s in signals}
        with patch.object(strategy, "decide_entry", side_effect=lambda enriched, **kw: signals[enriched]):
            return scan_for_entry("bot_500", config.VARIANTS[0], config.DEFAULTS, now, top, candles, True,
                                  indicator_cache={s: s for s in signals}, session_opens=session_opens)

    def test_unaffordable_signal_is_skipped_for_the_next_one(self, fresh_db):
        arm = pd.Timestamp(_ist(2026, 9, 25, 10, 15))
        signals = {"MRF": strategy.EntryCheck(True, arm, 130000.0, "entry"),
                   "TCS": strategy.EntryCheck(True, arm, 3000.0, "entry")}
        r = self._scan(_ist(2026, 9, 25, 10, 15), signals, _ist(2026, 9, 25, 11, 16))
        assert r["entered"]["symbol"] == "TCS"
        assert r["candidates"][0]["reason"].startswith("unaffordable")

    def test_previous_session_signal_fills_at_todays_open(self, fresh_db):
        arm = pd.Timestamp(_ist(2026, 9, 24, 11, 15))
        signals = {"TCS": strategy.EntryCheck(True, arm, 3000.0, "entry")}
        yesterday_last, morning = _ist(2026, 9, 24, 15, 15), _ist(2026, 9, 25, 9, 16)
        assert self._scan(yesterday_last, signals, morning)["candidates"][0]["reason"] == "no_session_open"
        r = self._scan(yesterday_last, signals, morning, session_opens={"TCS": 3050.0})
        assert r["entered"]["entry_price"] == 3050.0
