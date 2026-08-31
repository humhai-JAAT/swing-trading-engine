"""Trade storage — dual-mode (Postgres via DATABASE_URL, else local SQLite).
Each trade table is per `{universe_bot}/{variant_key}` combination (2 total).
Table prefix: ste_ (swing trading engine).
No checkpoint system — this engine scans at every 1H candle close, no subh30.
Capital tracking sums ALL closed trades (not just today's) since positions
carry forward across days (CNC delivery).
"""

import os
import re
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytz
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from common.helpers import PROJECT_ROOT, get_logger
from engine.config import all_variant_ids

logger = get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _now() -> datetime:
    return datetime.now(IST)


def _variant_to_table_suffix(variant_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", variant_id.replace("/", "__"))


VARIANT_TABLES = {v: f"ste_trades_{_variant_to_table_suffix(v)}" for v in all_variant_ids()}


def _table(variant_id: str) -> str:
    try:
        return VARIANT_TABLES[variant_id]
    except KeyError:
        raise ValueError(f"Unknown variant id: {variant_id!r}") from None


_TRADES_TABLE_COLUMNS = """
    id {pk},
    symbol TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('OPEN', 'CLOSED')),
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    capital_used REAL NOT NULL,
    leverage REAL NOT NULL DEFAULT 1.0,
    entry_charges REAL NOT NULL,
    arm_cycle_id TEXT,
    peak_price REAL,
    trough_price REAL,
    target_hit INTEGER NOT NULL DEFAULT 0,
    exit_time TEXT,
    exit_price REAL,
    exit_reason TEXT,
    exit_charges REAL,
    gross_pnl REAL,
    total_charges REAL,
    net_pnl REAL,
    net_pnl_pct REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
"""


def _variant_tables_sql(pk: str) -> str:
    stmts = []
    for table in VARIANT_TABLES.values():
        stmts.append(f"CREATE TABLE IF NOT EXISTS {table} (" + _TRADES_TABLE_COLUMNS.format(pk=pk) + ");")
        stmts.append(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_one_open ON {table} (status) "
                      f"WHERE status = 'OPEN';")
    return "\n\n".join(stmts)


_SHARED_SCHEMA_TAIL = """
CREATE TABLE IF NOT EXISTS ste_cycle_log (
    id {pk},
    cycle_time TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    symbols_scanned INTEGER,
    message TEXT,
    warnings TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_ste_cycle_log_time ON ste_cycle_log(cycle_time);

CREATE TABLE IF NOT EXISTS ste_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

SQLITE_SCHEMA = _variant_tables_sql("INTEGER PRIMARY KEY AUTOINCREMENT") + "\n\n" \
    + _SHARED_SCHEMA_TAIL.format(pk="INTEGER PRIMARY KEY AUTOINCREMENT")

POSTGRES_SCHEMA = _variant_tables_sql("SERIAL PRIMARY KEY") + "\n\n" \
    + _SHARED_SCHEMA_TAIL.format(pk="SERIAL PRIMARY KEY")

_engine: Engine | None = None


def _sqlite_path() -> Path:
    path = PROJECT_ROOT / "data" / "swing_trading_engine.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        _engine = create_engine(database_url, pool_pre_ping=True)
        logger.info(f"Using {_engine.dialect.name} database (DATABASE_URL set)")
    else:
        _engine = create_engine(f"sqlite:///{_sqlite_path()}")
        logger.info("Using local SQLite database (no DATABASE_URL set)")
    return _engine


def _lock_key_for_variant(variant_id: str) -> int:
    return zlib.crc32(variant_id.encode())


@contextmanager
def acquire_trade_lock(variant_id: str):
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        yield
        return
    conn = engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key_for_variant(variant_id)})
        yield
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()


_SCAN_CYCLE_LOCK_KEY = 839204153


@contextmanager
def try_acquire_scan_lock():
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        yield True
        return
    conn = engine.connect()
    try:
        got = conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _SCAN_CYCLE_LOCK_KEY}).scalar()
        try:
            yield bool(got)
        finally:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _SCAN_CYCLE_LOCK_KEY})
    finally:
        conn.close()


def init_db() -> None:
    engine = get_engine()
    schema = POSTGRES_SCHEMA if engine.dialect.name == "postgresql" else SQLITE_SCHEMA
    with engine.begin() as conn:
        for statement in schema.strip().split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))


def open_trade(variant_id: str, symbol: str, entry_price: float, quantity: int, capital_used: float,
               entry_charges: float, arm_cycle_id: str | None, leverage: float = 1.0) -> int:
    table = _table(variant_id)
    now = _now().isoformat()
    with get_engine().begin() as conn:
        result = conn.execute(
            text(f"""INSERT INTO {table}
                    (symbol, status, entry_time, entry_price, quantity, capital_used, leverage,
                     entry_charges, arm_cycle_id, peak_price, trough_price, created_at, updated_at)
                    VALUES (:symbol, 'OPEN', :entry_time, :entry_price, :quantity, :capital_used, :leverage,
                            :entry_charges, :arm_cycle_id, :entry_price, :entry_price, :now, :now)
                    RETURNING id"""),
            {"symbol": symbol, "entry_time": now, "entry_price": entry_price, "quantity": quantity,
             "capital_used": capital_used, "leverage": leverage, "entry_charges": entry_charges,
             "arm_cycle_id": arm_cycle_id, "now": now},
        )
        return result.scalar_one()


def update_price_extremes(variant_id: str, trade_id: int, peak_price: float, trough_price: float) -> None:
    table = _table(variant_id)
    now = _now().isoformat()
    with get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE {table} SET peak_price=:peak, trough_price=:trough, updated_at=:now WHERE id=:id"),
            {"peak": peak_price, "trough": trough_price, "now": now, "id": trade_id},
        )


def mark_target_hit(variant_id: str, trade_id: int) -> None:
    table = _table(variant_id)
    now = _now().isoformat()
    with get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE {table} SET target_hit=1, updated_at=:now WHERE id=:id"),
            {"now": now, "id": trade_id},
        )


def close_trade(variant_id: str, trade_id: int, exit_price: float, exit_reason: str, exit_charges: float) -> None:
    table = _table(variant_id)
    now = _now().isoformat()
    with get_engine().begin() as conn:
        row = conn.execute(
            text(f"SELECT entry_price, quantity, capital_used, entry_charges FROM {table} WHERE id=:id"),
            {"id": trade_id},
        ).mappings().first()
        if row is None:
            raise ValueError(f"Trade {trade_id} not found in {table}")

        gross_pnl = (exit_price - row["entry_price"]) * row["quantity"]
        total_charges = row["entry_charges"] + exit_charges
        net_pnl = gross_pnl - total_charges
        net_pnl_pct = net_pnl / row["capital_used"] * 100

        conn.execute(
            text(f"""UPDATE {table} SET status='CLOSED', exit_time=:now, exit_price=:exit_price,
                    exit_reason=:exit_reason, exit_charges=:exit_charges, gross_pnl=:gross_pnl,
                    total_charges=:total_charges, net_pnl=:net_pnl, net_pnl_pct=:net_pnl_pct, updated_at=:now
                    WHERE id=:id"""),
            {"now": now, "exit_price": exit_price, "exit_reason": exit_reason, "exit_charges": exit_charges,
             "gross_pnl": gross_pnl, "total_charges": total_charges, "net_pnl": net_pnl,
             "net_pnl_pct": net_pnl_pct, "id": trade_id},
        )


def get_open_trade(variant_id: str) -> dict | None:
    table = _table(variant_id)
    with get_engine().connect() as conn:
        row = conn.execute(
            text(f"SELECT * FROM {table} WHERE status='OPEN' ORDER BY id DESC LIMIT 1")
        ).mappings().first()
        return dict(row) if row else None


def get_closed_trades(variant_id: str) -> pd.DataFrame:
    table = _table(variant_id)
    return pd.read_sql_query(
        text(f"SELECT * FROM {table} WHERE status='CLOSED' ORDER BY exit_time DESC"), get_engine()
    )


def get_all_trades(variant_id: str) -> pd.DataFrame:
    table = _table(variant_id)
    return pd.read_sql_query(text(f"SELECT * FROM {table} ORDER BY entry_time DESC"), get_engine())


def get_arm_cycles_used(variant_id: str, symbol: str) -> set[str]:
    """All arm_cycle_ids ever used for this variant+symbol — not just today's,
    since CNC positions carry forward across days."""
    table = _table(variant_id)
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(f"SELECT arm_cycle_id FROM {table} "
                 f"WHERE symbol=:symbol AND arm_cycle_id IS NOT NULL"),
            {"symbol": symbol},
        ).all()
        return {r[0] for r in rows}


def get_starting_capital(variant_id: str, default: float) -> float:
    """Realized capital base = default + ALL realized net P&L (not just today's,
    since CNC positions carry forward — capital compounds across the full
    trade history, not reset daily)."""
    table = _table(variant_id)
    with get_engine().connect() as conn:
        row = conn.execute(
            text(f"SELECT COALESCE(SUM(net_pnl), 0) AS total FROM {table} WHERE status='CLOSED'"),
        ).mappings().first()
        return default + (row["total"] or 0)


def log_cycle(status: str, stage: str = "", symbols_scanned: int = 0, message: str = "",
              warnings: str = "", error: str | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("INSERT INTO ste_cycle_log (cycle_time, status, stage, symbols_scanned, message, warnings, error) "
                 "VALUES (:cycle_time, :status, :stage, :symbols_scanned, :message, :warnings, :error)"),
            {"cycle_time": _now().isoformat(), "status": status, "stage": stage,
             "symbols_scanned": symbols_scanned, "message": message, "warnings": warnings, "error": error},
        )


def get_cycle_logs(limit: int = 30) -> pd.DataFrame:
    return pd.read_sql_query(
        text("SELECT * FROM ste_cycle_log ORDER BY cycle_time DESC LIMIT :limit"),
        get_engine(), params={"limit": limit},
    )


def prune_cycle_logs(retention_days: int = 7) -> int:
    cutoff = (_now() - timedelta(days=retention_days)).isoformat()
    with get_engine().begin() as conn:
        result = conn.execute(
            text("DELETE FROM ste_cycle_log WHERE cycle_time < :cutoff"),
            {"cutoff": cutoff},
        )
        return result.rowcount


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_engine().connect() as conn:
        row = conn.execute(text("SELECT value FROM ste_settings WHERE key=:k"), {"k": key}).first()
        return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with get_engine().begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(
                text("INSERT INTO ste_settings (key, value) VALUES (:k, :v) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
                {"k": key, "v": value},
            )
        else:
            conn.execute(text("DELETE FROM ste_settings WHERE key=:k"), {"k": key})
            conn.execute(text("INSERT INTO ste_settings (key, value) VALUES (:k, :v)"), {"k": key, "v": value})


def reset_all_data() -> None:
    with get_engine().begin() as conn:
        for table in VARIANT_TABLES.values():
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM ste_cycle_log"))
