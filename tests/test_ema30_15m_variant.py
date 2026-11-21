"""ema30_15m variant (2026-11-15): same entry, exit = fixed stop-loss for the whole trade
OR a 15-minute candle (closed after entry) closing below its EMA30. No target, no floor,
own Rs 50,000 pool."""

from datetime import datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import pytz

from engine import config, db, strategy
from engine.variant_engine import (SLIPPAGE_PCT, _decide_and_exit, candle_closes_at, check_ema30_15m_exit,
                                   discard_incomplete_candle, scan_for_entry)

IST = pytz.timezone("Asia/Kolkata")
V3 = "bot_500/ema30_15m"
CFG = config.VARIANTS_BY_KEY["ema30_15m"]


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


class _Account:
    account_id = "test"

    def __init__(self, df_15m=None):
        self.df_15m = df_15m

    def fetch_candles(self, *args, **kwargs):
        return self.df_15m


def _15m(last_start, lo, hi, n=40):
    """n 15-minute bars ending at `last_start`, closes moving linearly lo -> hi."""
    idx = pd.date_range(end=last_start, periods=n, freq="15min")
    close = np.linspace(lo, hi, n)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close}, index=idx)


SL15 = {**config.DEFAULTS, "stop_loss_pct": 1.5}  # pin SL for the explicit-stop test (DEFAULTS is now 2.0)


def _open_trade(minute_bars):
    """Entry 100 x 10 on Rs 1000 capital: stop 98.0 at 2% SL (target would be 103 — irrelevant here)."""
    db.open_trade(V3, "TEST", 100.0, 10, 1000.0, 1.0, None)
    trade = {**db.get_open_trade(V3), "entry_time": "2026-09-24T10:17:00+05:30"}
    idx = pd.date_range(_ist(2026, 9, 24, 10, 18), periods=len(minute_bars), freq="1min")
    return trade, pd.DataFrame(minute_bars, columns=["Open", "High", "Low", "Close"], index=idx)


class TestCandleCloseFor15m:
    def test_15m_candle_closes_15_minutes_later(self):
        assert candle_closes_at(pd.Timestamp(_ist(2026, 9, 24, 10, 15)), 15) == _ist(2026, 9, 24, 10, 30)

    def test_last_15m_candle_of_day_closes_at_1530(self):
        assert candle_closes_at(pd.Timestamp(_ist(2026, 9, 24, 15, 15)), 15) == _ist(2026, 9, 24, 15, 30)

    def test_default_is_still_one_hour(self):
        assert candle_closes_at(pd.Timestamp(_ist(2026, 9, 24, 10, 15))) == _ist(2026, 9, 24, 11, 15)

    def test_forming_15m_candle_dropped(self):
        idx = pd.DatetimeIndex([_ist(2026, 9, 24, 10, 0), _ist(2026, 9, 24, 10, 15)])
        df = pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)
        with patch("engine.variant_engine.datetime") as clock:
            clock.now.return_value = _ist(2026, 9, 24, 10, 20)
            assert discard_incomplete_candle(df, minutes=15).index[-1] == idx[0]


class TestCheckEma30:
    def test_none_on_short_or_empty(self):
        assert check_ema30_15m_exit(None) is None
        assert check_ema30_15m_exit(pd.DataFrame()) is None
        assert check_ema30_15m_exit(_15m(_ist(2026, 9, 24, 10, 15), 120, 100, n=20)) is None

    def test_falling_close_below_ema30_exits(self):
        assert check_ema30_15m_exit(_15m(_ist(2026, 9, 24, 10, 15), 120, 100)) == pytest.approx(100.0)

    def test_rising_close_above_ema30_holds(self):
        assert check_ema30_15m_exit(_15m(_ist(2026, 9, 24, 10, 15), 90, 110)) is None


class TestEma30Variant:
    def test_stop_loss_exits_at_stop(self, fresh_db):
        trade, df = _open_trade([(100, 100.5, 98.2, 98.4)])
        r = _decide_and_exit(V3, CFG, trade, SL15, None, _Account(), "TEST", df)
        assert r["reason"] == "STOP_LOSS"
        assert r["price"] == pytest.approx(98.5 * (1 - SLIPPAGE_PCT / 100))

    def test_no_target_no_floor(self, fresh_db):
        """Rises through the old 3% target and dips back under it: the old variants would floor out here."""
        trade, df = _open_trade([(100, 103.5, 101, 103.2), (103.2, 103.4, 102.5, 102.6)])
        r = _decide_and_exit(V3, CFG, trade, config.DEFAULTS, None,
                             _Account(_15m(_ist(2026, 9, 24, 10, 15), 90, 110)), "TEST", df)
        assert r["action"] == "hold"
        assert r["target_hit"] is False
        assert db.get_open_trade(V3)["target_hit"] == 0

    def test_15m_close_below_ema30_exits_at_current_price(self, fresh_db):
        trade, df = _open_trade([(100, 101, 99.5, 100.8)])
        r = _decide_and_exit(V3, CFG, trade, config.DEFAULTS, None,
                             _Account(_15m(_ist(2026, 9, 24, 10, 15), 120, 100)), "TEST", df)
        assert r["reason"] == "EMA30_15M_EXIT"
        assert r["price"] == pytest.approx(100.8 * (1 - SLIPPAGE_PCT / 100))

    def test_15m_candle_closed_before_entry_does_not_count(self, fresh_db):
        trade, df = _open_trade([(100, 101, 99.5, 100.8)])
        r = _decide_and_exit(V3, CFG, trade, config.DEFAULTS, None,
                             _Account(_15m(_ist(2026, 9, 24, 9, 45), 120, 100)), "TEST", df)  # closed 10:00 < entry 10:17
        assert r["action"] == "hold"

    def test_no_15m_data_holds(self, fresh_db):
        trade, df = _open_trade([(100, 101, 99.5, 100.8)])
        r = _decide_and_exit(V3, CFG, trade, config.DEFAULTS, None, _Account(None), "TEST", df)
        assert r["action"] == "hold"


class TestCapitalSizing:
    def _scan(self, price, capital):
        now = _ist(2026, 9, 25, 11, 16)
        top = pd.DataFrame({"symbol": ["X"]})
        candles = {"X": pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([_ist(2026, 9, 25, 10, 15)]))}
        check = strategy.EntryCheck(True, pd.Timestamp(_ist(2026, 9, 25, 10, 15)), price, "entry")
        with patch.object(strategy, "decide_entry", return_value=check):
            return scan_for_entry("bot_500", CFG, {**config.DEFAULTS, "starting_capital": capital}, now, top,
                                  candles, True, indicator_cache={"X": "X"})

    def test_sizing_follows_the_capital_setting(self, fresh_db):
        assert self._scan(30000.0, 10000)["action"] == "no_signal"  # can't buy one share on 10k
        r = self._scan(30000.0, 50000)
        assert r["action"] == "enter"
        assert r["entered"]["capital_used"] == pytest.approx(50000.0)
