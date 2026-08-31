"""Tests for engine/broker.py — paper trading entry/exit with CNC charges."""

import pytest

from engine import broker, db, config


@pytest.fixture(autouse=True)
def fresh_sqlite_db(tmp_path, monkeypatch):
    db._engine = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "_sqlite_path", lambda: tmp_path / "test.db")
    db.init_db()
    yield
    db._engine = None


class TestEnterPosition:
    def test_basic_entry(self):
        result = broker.enter_position("bot_500/trailing_ema", "RELIANCE", 2500.0, 10000.0, "arm_1")
        assert result["symbol"] == "RELIANCE"
        assert result["entry_price"] == 2500.0
        assert result["quantity"] == 4  # floor(10000/2500)
        assert result["entry_charges"] > 0

    def test_insufficient_capital(self):
        with pytest.raises(ValueError, match="insufficient"):
            broker.enter_position("bot_500/trailing_ema", "MRF", 100000.0, 10000.0, None)

    def test_trade_in_db(self):
        broker.enter_position("bot_500/trailing_ema", "TCS", 3500.0, 10000.0, None)
        trade = db.get_open_trade("bot_500/trailing_ema")
        assert trade is not None
        assert trade["symbol"] == "TCS"


class TestExitPosition:
    def test_basic_exit(self):
        entry = broker.enter_position("bot_500/trailing_ema", "INFY", 1500.0, 10000.0, None)
        result = broker.exit_position("bot_500/trailing_ema", entry["trade_id"],
                                       entry["quantity"], 1550.0, "EMA_TRAIL_EXIT")
        assert result["exit_price"] == 1550.0
        assert result["exit_reason"] == "EMA_TRAIL_EXIT"
        assert result["exit_charges"] > 0

    def test_trade_closed_in_db(self):
        entry = broker.enter_position("bot_500/trailing_atr", "HDFC", 1600.0, 10000.0, None)
        broker.exit_position("bot_500/trailing_atr", entry["trade_id"],
                              entry["quantity"], 1650.0, "ATR_TRAIL_EXIT")
        assert db.get_open_trade("bot_500/trailing_atr") is None


class TestAvailableCapital:
    def test_initial_capital(self):
        cap = broker.available_capital("bot_500/trailing_ema", 10000.0)
        assert cap == 10000.0

    def test_capital_after_profit(self):
        entry = broker.enter_position("bot_500/trailing_ema", "A", 100.0, 10000.0, None)
        broker.exit_position("bot_500/trailing_ema", entry["trade_id"],
                              entry["quantity"], 110.0, "TARGET")
        cap = broker.available_capital("bot_500/trailing_ema", 10000.0)
        assert cap > 10000.0


class TestUpdateExtremes:
    def test_updates_peak_and_trough(self):
        entry = broker.enter_position("bot_500/trailing_ema", "SBIN", 600.0, 10000.0, None)
        new_peak, new_trough = broker.update_extremes(
            "bot_500/trailing_ema", entry["trade_id"], 600.0, 600.0, 620.0, 590.0
        )
        assert new_peak == 620.0
        assert new_trough == 590.0

    def test_peak_only_increases(self):
        entry = broker.enter_position("bot_500/trailing_atr", "ICICI", 800.0, 10000.0, None)
        peak1, _ = broker.update_extremes("bot_500/trailing_atr", entry["trade_id"], 800.0, 800.0, 820.0, 790.0)
        peak2, _ = broker.update_extremes("bot_500/trailing_atr", entry["trade_id"], peak1, 790.0, 810.0, 795.0)
        assert peak2 == 820.0  # doesn't decrease
