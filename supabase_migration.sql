-- Swing Trading Engine — Supabase migration
-- Apply to project: emlmieoxnbjibcuzsbjz (unified-trading-engine-v2)
-- Tables use ste_ prefix (separate from unified engine's ute_ tables)

CREATE TABLE IF NOT EXISTS ste_trades_bot_500__trailing_ema (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('OPEN', 'CLOSED')),
    entry_time TEXT NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    quantity INTEGER NOT NULL,
    capital_used DOUBLE PRECISION NOT NULL,
    leverage DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    entry_charges DOUBLE PRECISION NOT NULL,
    arm_cycle_id TEXT,
    peak_price DOUBLE PRECISION,
    trough_price DOUBLE PRECISION,
    target_hit INTEGER NOT NULL DEFAULT 0,
    target_hit_at TEXT,
    exit_time TEXT,
    exit_price DOUBLE PRECISION,
    exit_reason TEXT,
    exit_charges DOUBLE PRECISION,
    gross_pnl DOUBLE PRECISION,
    total_charges DOUBLE PRECISION,
    net_pnl DOUBLE PRECISION,
    net_pnl_pct DOUBLE PRECISION,
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
    entry_price DOUBLE PRECISION NOT NULL,
    quantity INTEGER NOT NULL,
    capital_used DOUBLE PRECISION NOT NULL,
    leverage DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    entry_charges DOUBLE PRECISION NOT NULL,
    arm_cycle_id TEXT,
    peak_price DOUBLE PRECISION,
    trough_price DOUBLE PRECISION,
    target_hit INTEGER NOT NULL DEFAULT 0,
    target_hit_at TEXT,
    exit_time TEXT,
    exit_price DOUBLE PRECISION,
    exit_reason TEXT,
    exit_charges DOUBLE PRECISION,
    gross_pnl DOUBLE PRECISION,
    total_charges DOUBLE PRECISION,
    net_pnl DOUBLE PRECISION,
    net_pnl_pct DOUBLE PRECISION,
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

-- One-time upgrade for tables created before 2026-09-27: REAL (4-byte, ~7 digits)
-- -> DOUBLE PRECISION, plus target_hit_at (the app also adds that column on startup).
ALTER TABLE ste_trades_bot_500__trailing_ema
    ADD COLUMN IF NOT EXISTS target_hit_at TEXT,
    ALTER COLUMN entry_price TYPE DOUBLE PRECISION,
    ALTER COLUMN capital_used TYPE DOUBLE PRECISION,
    ALTER COLUMN leverage TYPE DOUBLE PRECISION,
    ALTER COLUMN entry_charges TYPE DOUBLE PRECISION,
    ALTER COLUMN peak_price TYPE DOUBLE PRECISION,
    ALTER COLUMN trough_price TYPE DOUBLE PRECISION,
    ALTER COLUMN exit_price TYPE DOUBLE PRECISION,
    ALTER COLUMN exit_charges TYPE DOUBLE PRECISION,
    ALTER COLUMN gross_pnl TYPE DOUBLE PRECISION,
    ALTER COLUMN total_charges TYPE DOUBLE PRECISION,
    ALTER COLUMN net_pnl TYPE DOUBLE PRECISION,
    ALTER COLUMN net_pnl_pct TYPE DOUBLE PRECISION;
ALTER TABLE ste_trades_bot_500__trailing_atr
    ADD COLUMN IF NOT EXISTS target_hit_at TEXT,
    ALTER COLUMN entry_price TYPE DOUBLE PRECISION,
    ALTER COLUMN capital_used TYPE DOUBLE PRECISION,
    ALTER COLUMN leverage TYPE DOUBLE PRECISION,
    ALTER COLUMN entry_charges TYPE DOUBLE PRECISION,
    ALTER COLUMN peak_price TYPE DOUBLE PRECISION,
    ALTER COLUMN trough_price TYPE DOUBLE PRECISION,
    ALTER COLUMN exit_price TYPE DOUBLE PRECISION,
    ALTER COLUMN exit_charges TYPE DOUBLE PRECISION,
    ALTER COLUMN gross_pnl TYPE DOUBLE PRECISION,
    ALTER COLUMN total_charges TYPE DOUBLE PRECISION,
    ALTER COLUMN net_pnl TYPE DOUBLE PRECISION,
    ALTER COLUMN net_pnl_pct TYPE DOUBLE PRECISION;
