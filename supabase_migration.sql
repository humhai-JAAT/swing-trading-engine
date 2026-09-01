-- Swing Trading Engine — Supabase migration
-- Apply to project: emlmieoxnbjibcuzsbjz (unified-trading-engine-v2)
-- Tables use ste_ prefix (separate from unified engine's ute_ tables)

CREATE TABLE IF NOT EXISTS ste_trades_bot_500__trailing_ema (
    id SERIAL PRIMARY KEY,
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
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ste_trades_bot_500__trailing_ema_one_open
    ON ste_trades_bot_500__trailing_ema (status) WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS ste_trades_bot_500__trailing_atr (
    id SERIAL PRIMARY KEY,
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
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ste_trades_bot_500__trailing_atr_one_open
    ON ste_trades_bot_500__trailing_atr (status) WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS ste_cycle_log (
    id SERIAL PRIMARY KEY,
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

-- Enable RLS on all tables (app connects via DATABASE_URL which bypasses RLS)
ALTER TABLE ste_trades_bot_500__trailing_ema ENABLE ROW LEVEL SECURITY;
ALTER TABLE ste_trades_bot_500__trailing_atr ENABLE ROW LEVEL SECURITY;
ALTER TABLE ste_cycle_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE ste_settings ENABLE ROW LEVEL SECURITY;
