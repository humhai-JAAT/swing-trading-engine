"""Tests for engine/db.py — SQLite mode, ste_ prefix, CNC capital tracking."""

import pytest

from engine import db, config


@pytest.fixture(autouse=True)
def fresh_sqlite_db(tmp_path, monkeypatch):
    """Each test gets a fresh SQLite DB in a temp dir."""
    db._engine = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "_sqlite_path", lambda: tmp_path / "test.db")
    db.init_db()
    yield
    db._engine = None


class TestTablePrefix:
    def test_tables_have_ste_prefix(self):
        for table_name in db.VARIANT_TABLES.values():
            assert table_name.startswith("ste_trades_")

    def test_variant_table_count(self):
        assert len(db.VARIANT_TABLES) == 2

    def test_variant_ids_match_config(self):
        assert set(db.VARIANT_TABLES.keys()) == set(config.all_variant_ids())


class TestNoCheckpointTables:
    def test_no_checkpoint_log_table(self):
        engine = db.get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text
            tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            table_names = [r[0] for r in tables]
            assert "ste_checkpoint_log" not in table_names

    def test_no_checkpoint_functions(self):
        assert not hasattr(db, "get_checkpoints_used_today")
        assert not hasattr(db, "mark_checkpoint_used")


class TestCycleLogPrefix:
    def test_cycle_log_table_exists(self):
        engine = db.get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text
            tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            table_names = [r[0] for r in tables]
            assert "ste_cycle_log" in table_names

    def test_settings_table_exists(self):
        engine = db.get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text
            tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            table_names = [r[0] for r in tables]
            assert "ste_settings" in table_names


class TestTradeLifecycle:
    def test_open_and_get_trade(self):
        variant_id = "bot_500/trailing_ema"
        trade_id = db.open_trade(variant_id, "RELIANCE", 2500.0, 4, 10000.0, 14.23, "arm_1")
        assert trade_id > 0

        trade = db.get_open_trade(variant_id)
        assert trade is not None
        assert trade["symbol"] == "RELIANCE"
        assert trade["entry_price"] == 2500.0
        assert trade["quantity"] == 4
        assert trade["status"] == "OPEN"

    def test_close_trade(self):
        variant_id = "bot_500/trailing_ema"
        trade_id = db.open_trade(variant_id, "TCS", 3500.0, 2, 7000.0, 10.0, None)
        db.close_trade(variant_id, trade_id, 3600.0, "EMA_TRAIL_EXIT", 9.5)

        trade = db.get_open_trade(variant_id)
        assert trade is None

        closed = db.get_closed_trades(variant_id)
        assert len(closed) == 1
        assert closed.iloc[0]["exit_reason"] == "EMA_TRAIL_EXIT"
        assert closed.iloc[0]["exit_price"] == 3600.0

    def test_pnl_calculation(self):
        variant_id = "bot_500/trailing_atr"
        trade_id = db.open_trade(variant_id, "INFY", 1500.0, 6, 9000.0, 12.0, None)
        db.close_trade(variant_id, trade_id, 1550.0, "ATR_TRAIL_EXIT", 11.0)

        closed = db.get_closed_trades(variant_id)
        row = closed.iloc[0]
        assert row["gross_pnl"] == pytest.approx(300.0)  # (1550-1500)*6
        assert row["total_charges"] == pytest.approx(23.0)  # 12+11
        assert row["net_pnl"] == pytest.approx(277.0)  # 300-23

    def test_mark_target_hit(self):
        variant_id = "bot_500/trailing_ema"
        trade_id = db.open_trade(variant_id, "HDFC", 1600.0, 5, 8000.0, 11.0, None)
        db.mark_target_hit(variant_id, trade_id)

        trade = db.get_open_trade(variant_id)
        assert trade["target_hit"] == 1

    def test_update_price_extremes(self):
        variant_id = "bot_500/trailing_ema"
        trade_id = db.open_trade(variant_id, "SBIN", 600.0, 15, 9000.0, 12.0, None)
        db.update_price_extremes(variant_id, trade_id, 620.0, 590.0)

        trade = db.get_open_trade(variant_id)
        assert trade["peak_price"] == 620.0
        assert trade["trough_price"] == 590.0


class TestCapitalTracking:
    def test_starting_capital_no_trades(self):
        capital = db.get_starting_capital("bot_500/trailing_ema", 10000.0)
        assert capital == 10000.0

    def test_capital_sums_all_closed_trades(self):
        variant_id = "bot_500/trailing_ema"

        trade_id = db.open_trade(variant_id, "A", 100.0, 100, 10000.0, 10.0, None)
        db.close_trade(variant_id, trade_id, 110.0, "TARGET", 10.0)

        trade_id2 = db.open_trade(variant_id, "B", 200.0, 50, 10000.0, 10.0, None)
        db.close_trade(variant_id, trade_id2, 190.0, "STOP_LOSS", 10.0)

        capital = db.get_starting_capital(variant_id, 10000.0)
        closed = db.get_closed_trades(variant_id)
        total_pnl = closed["net_pnl"].sum()
        assert capital == pytest.approx(10000.0 + total_pnl)

    def test_capital_independent_per_variant(self):
        v1 = "bot_500/trailing_ema"
        v2 = "bot_500/trailing_atr"

        trade_id = db.open_trade(v1, "X", 100.0, 100, 10000.0, 5.0, None)
        db.close_trade(v1, trade_id, 120.0, "TARGET", 5.0)

        capital_v1 = db.get_starting_capital(v1, 10000.0)
        capital_v2 = db.get_starting_capital(v2, 10000.0)
        assert capital_v1 > 10000.0
        assert capital_v2 == 10000.0


class TestArmCyclesUsed:
    def test_returns_all_arm_cycles(self):
        variant_id = "bot_500/trailing_ema"
        db.open_trade(variant_id, "RELIANCE", 2500.0, 4, 10000.0, 14.0, "cycle_1")
        db.close_trade(variant_id, 1, 2550.0, "TARGET", 14.0)
        db.open_trade(variant_id, "RELIANCE", 2600.0, 3, 10000.0, 14.0, "cycle_2")

        used = db.get_arm_cycles_used(variant_id, "RELIANCE")
        assert "cycle_1" in used
        assert "cycle_2" in used


class TestSettings:
    def test_get_default(self):
        assert db.get_setting("nonexistent", "fallback") == "fallback"

    def test_set_and_get(self):
        db.set_setting("public_variant", "bot_500/trailing_ema")
        assert db.get_setting("public_variant") == "bot_500/trailing_ema"

    def test_overwrite(self):
        db.set_setting("key", "v1")
        db.set_setting("key", "v2")
        assert db.get_setting("key") == "v2"


class TestCycleLog:
    def test_log_and_retrieve(self):
        db.log_cycle(status="OK", stage="entry_scan", symbols_scanned=30, message="test")
        logs = db.get_cycle_logs(limit=5)
        assert len(logs) == 1
        assert logs.iloc[0]["status"] == "OK"
        assert logs.iloc[0]["stage"] == "entry_scan"

    def test_prune_keeps_recent(self):
        db.log_cycle(status="OK", stage="entry_scan")
        pruned = db.prune_cycle_logs(retention_days=7)
        assert pruned == 0
        assert len(db.get_cycle_logs()) == 1


class TestResetAllData:
    def test_reset_clears_everything(self):
        v1 = "bot_500/trailing_ema"
        db.open_trade(v1, "X", 100.0, 10, 1000.0, 5.0, None)
        db.log_cycle(status="OK", stage="entry_scan")

        db.reset_all_data()
        assert db.get_open_trade(v1) is None
        assert len(db.get_cycle_logs()) == 0


class TestOneOpenConstraint:
    def test_cannot_open_two_trades_same_variant(self):
        variant_id = "bot_500/trailing_ema"
        db.open_trade(variant_id, "A", 100.0, 10, 1000.0, 5.0, None)
        with pytest.raises(Exception):
            db.open_trade(variant_id, "B", 200.0, 5, 1000.0, 5.0, None)
