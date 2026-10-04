# Architecture — Swing Trading Engine

## High-level flow

```
Streamlit Cloud app process (admin app; separate viewer app deployment)
├── app.py (admin UI)
├── viewer_app.py (read-only UI, separate deployment)
│
└── scheduler.py (APScheduler background jobs)
        │
        ├── Position management job — every 2 min (IntervalTrigger)
        │     runs manage_open_position() per variant with open trade
        │
        └── Entry scan job — CronTrigger at hour="10,11,12,13,14", minute="16"
                │  (5 scans/day, 1 min after each 1H candle close)
                ▼
            engine.run_full_scan_cycle()
                │
                ├── STAGE 1 — ranking data (see below)
                │
                ├── STAGE 2 — 1H candle history (see below)
                │
                └── for each of 2 variants (1 universe-bot × 2 exit styles):
                        run its own independent strategy-check + position management,
                        reading Stage 1/2's shared data — no per-variant re-fetching
```

## Stage 1 — ranking data layer

Identical to the unified engine's Stage 1, but fetching the full Nifty500
(~500 stocks) instead of Nifty500-minus-Nifty100 (~400).

```
~500 stocks split into chunks
        │
        ▼
Parallel workers (WORKERS_PER_ACCOUNT=2) on primary broker (Groww)
        │
        ▼
Merge + sort → final rank list (~500 stocks, ranked by % change)
        │
        ▼ (in-memory, shared read-only)
bot_500 filters: take top-N (gainers_pool_size, default 30)
```

Chunk-level fallback: if any chunk-fetch fails on Groww, ONLY that chunk is
retried via Angel One. If both fail, the cycle proceeds with a smaller rank
list and a visible dashboard warning.

## Stage 2 — 1H candle history layer

```
bot_500 top-N
        │
        ▼
Parallel fetch — 1H candle history, 30 calendar days lookback
(CALENDAR_FETCH_DAYS=30, trimmed to CANDLE_LOOKBACK_TRADING_DAYS=15)
Primary: Groww · Fallback: Angel One
CANDLE_WORKERS_PER_ACCOUNT=3
        │
        ▼
Temp space — candle history (keyed by symbol, shared read-only)
        │
        ▼ both variants read from the same shared cache
```

**Why 30 calendar days / 15 trading days?** The strategy needs EMA100 + SMA9
warm-up = 109 bars minimum. At ~6 hourly candles per trading day, 15 trading
days gives ~90 bars — plus partial days and pre-market, this reliably clears
the 109-bar minimum. 30 calendar days accounts for weekends and holidays.

## Live position monitoring

Same dual-path design as the unified engine:
- **2-min REST job** (IntervalTrigger) — `manage_open_position()` fetches 1-min
  candles for price monitoring, then 1H candles for trailing-exit evaluation.
- **GrowwFeed websocket** (live_feed.py, daemon thread) — subscribes only to
  symbols with open positions, polls every ~2s, feeds ticks through the same
  `locked_decide_and_exit()` function.

Both paths funnel into `locked_decide_and_exit()` (wrapped in
`db.acquire_trade_lock()`) — no duplicated decision logic, no double-exit risk.

## CNC-specific differences from the unified engine

| Aspect | Unified (MIS intraday) | Swing (CNC delivery) |
|---|---|---|
| Timeframe | 5-min candles | 1H candles |
| Order type | MIS (intraday only) | CNC (carry-forward) |
| Square-off | Yes, after market close | None — hold until exit signal |
| STT | 0% buy, 0.025% sell | 0.1% both buy AND sell |
| Stamp duty | 0.003% buy | 0.015% buy |
| Capital tracking | Today's closed trades only | ALL closed trades ever |
| Arm cycles | Today's only | ALL ever (carry-forward) |
| Entry scan | Every 5 min (CronTrigger :01/:06/...) | Every 1H (CronTrigger :16) |
| Candle lookback | 12 cal days / 4 trading days | 30 cal days / 15 trading days |
| Checkpoint system | Subh30/puradin gating | None |

## Multi-broker / multi-account setup

Shared with the unified engine: 1 Groww account (paid, primary) + 1 Angel One
account (free, fallback). See the unified engine's Architecture.md for the
full reasoning on account count.

## Thread-safety design

Same `AccountRateLimiter` pattern as the unified engine — one
`threading.Lock()` + one "last call time" per broker account. Workers sharing
the same account safely take turns; workers on different accounts run
genuinely in parallel.

## Database

Dual-mode: Postgres (via `DATABASE_URL` env var) or local SQLite
(`data/swing_trading_engine.db`). Table prefix: `ste_` (not `ute_`).

Tables:
- `ste_trades_bot_500__trailing_ema` — trade records for EMA trailing variant
- `ste_trades_bot_500__trailing_atr` — trade records for ATR trailing variant
- `ste_cycle_log` — scan/position cycle execution log
- `ste_settings` — key/value settings store

Per-variant advisory locks (Postgres only, `zlib.crc32(variant_id)`) prevent
concurrent double-exits. Scan-level advisory lock
(`_SCAN_CYCLE_LOCK_KEY = 839204153`) prevents overlapping scan cycles.

## Naming convention

Same `{universe_bot}/{variant_key}` pattern as the unified engine:
`bot_500/trailing_ema`, `bot_500/trailing_atr`. No `vN`/`vN_M` naming.

## Technology decisions

Same stack as the unified engine: Python, Streamlit Community Cloud, same
reasoning (I/O-bound workload, existing broker SDKs, pandas ecosystem).

## File/folder structure

```
app.py                        Admin Streamlit app — full controls
viewer_app.py                 Read-only Streamlit app — separate Cloud deployment
requirements.txt
config/settings.yaml
.streamlit/secrets.toml       Local secrets — gitignored
data/                         Local SQLite DB + cached CSVs — gitignored
engine/
  config.py                    1 UNIVERSE_BOT, 2 VARIANTS, CNC defaults
  costs.py                     CNC delivery charges (NOT MIS intraday)
  db.py                        ste_ prefix, no checkpoint tables, CNC capital tracking
  scheduler.py                 APScheduler — 1H entry scan + 2-min position mgmt
  stage1_ranking.py            Parallel ranking-data fetch (Nifty500)
  stage2_candles.py            1H candle history fetch, 30-day lookback
  rate_limiter.py              AccountRateLimiter (per-account lock)
  broker_accounts.py           Account/key registry — Groww/Angel One
  strategy.py                  EMA-MACD V2.1.2 — timeframe-agnostic
  variant_engine.py            2 trailing-exit mechanisms, no subh30/puradin/square-off
  nse_universe.py              Nifty500 index-constituent CSV fetch
  broker.py                    Paper position sizing/entry/exit
  live_feed.py                 GrowwFeed websocket tick monitoring
  metrics.py                   Trade metrics aggregation
  dashboard_view.py            Shared rendering, ste- CSS prefix
common/
  helpers.py, indicators.py, metrics.py
tests/
  9 test files, 125 tests
```
