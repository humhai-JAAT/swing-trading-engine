# Phases — Swing Trading Engine

Retrospective + forward-looking breakdown. Update status markers as work lands.

## Phase 0 — Architecture design ✅ DONE (2026-08-31)

Designed as a direct architectural replica of the unified trading engine,
adapted for 1H timeframe and CNC carry-forward mechanics. Key decisions:
- 1 universe-bot (full Nifty500, ~500 stocks) × 2 variants (trailing_ema,
  trailing_atr) = 2 total.
- Same 2-stage shared-data pipeline (Stage 1 ranking + Stage 2 candle history).
- Same multi-broker setup (shared Groww + Angel One accounts).
- CNC delivery charges (STT 0.1% both sides, Stamp 0.015% buy).
- 1H candle evaluation with 30-day calendar lookback / 15 trading days.
- Entry scans at 1H boundary offsets: 10:16, 11:16, 12:16, 13:16, 14:16.
- No subh30 checkpoints, no intraday square-off.
- Capital and arm-cycle tracking across ALL trades (not daily reset).

## Phase 1 — Core implementation ✅ DONE (2026-08-31)

Built all 26 source files in one session, adapted from the unified engine:

**Shared/ported unchanged:**
- `common/helpers.py`, `common/indicators.py`, `common/metrics.py`
- `engine/strategy.py` — EMA-MACD V2.1.2, timeframe-agnostic
- `engine/rate_limiter.py` — per-account thread-safe rate limiting
- `engine/broker_accounts.py` — Groww + Angel One account registry
- `engine/live_feed.py` — GrowwFeed websocket (thread name `ste-live-feed`)

**Adapted for CNC/1H:**
- `engine/config.py` — 1 universe-bot, 2 variants, no `square_off_time`,
  `candle_interval=1h`, 30/15 day lookback defaults
- `engine/costs.py` — CNC delivery charges (not MIS)
- `engine/db.py` — `ste_` prefix, no checkpoint tables, capital sums ALL
  closed trades, arm cycles query ALL trades
- `engine/variant_engine.py` — no subh30 gating, no square-off, trailing exit
  fetches 1H candles
- `engine/scheduler.py` — CronTrigger at `hour="10,11,12,13,14", minute="16"`,
  Stage 1 fetches `nifty500` universe
- `engine/stage1_ranking.py` — `WORKERS_PER_ACCOUNT=2`
- `engine/stage2_candles.py` — `CALENDAR_FETCH_DAYS=30`,
  `CANDLE_LOOKBACK_TRADING_DAYS=15`, `CANDLE_WORKERS_PER_ACCOUNT=3`
- `engine/dashboard_view.py` — `ste-` CSS prefix, 2-variant layout, CNC labels
- `app.py` — no `square_off_time` setting, simple radio variant selector
- `viewer_app.py` — CNC carry-forward caption

## Phase 2 — Testing ✅ DONE (2026-08-31)

125 tests across 9 test files, all passing (4.43s):

| Test file | Tests | Coverage |
|---|---|---|
| `test_config.py` | 19 | Variant structure, defaults, settings I/O |
| `test_costs.py` | 14 | CNC charges: STT, stamp, exchange, SEBI, IPFT, GST, total |
| `test_strategy.py` | 13 | EMA-MACD indicators, entry signal, arm cycle rejection |
| `test_db.py` | 17 | ste_ prefix, no checkpoint tables, trade lifecycle, capital tracking |
| `test_variant_engine.py` | 13 | EMA9/ATR trail exits, scan_for_entry structure |
| `test_scheduler.py` | 14 | Market status, wake/sleep, CronTrigger timing |
| `test_metrics.py` | 15 | Portfolio metrics, profit factor, SQN, Wilson lower bound |
| `test_broker.py` | 9 | Paper entry/exit, capital tracking, price extremes |
| `test_nse_universe.py` | 4 | Universe validation, filter correctness |

Initial run had 17 failures (attribute names, Series wrapping, mock signatures)
— all fixed same session.

## Phase 3 — Git & GitHub ✅ DONE (2026-08-31 / 2026-09-01)

- Local git repo initialized, 2 commits on `main`.
- GitHub repo created: [humhai-JAAT/swing-trading-engine](https://github.com/humhai-JAAT/swing-trading-engine) (private).
- Pushed both commits.

## Phase 4 — Standard project docs ✅ DONE (2026-09-01)

Added 6 standard root-level docs: `PRD.md`, `Architecture.md`, `rules.md`,
`Phase.md`, `design.md`, `memory.md` — matching the pattern from all sibling
bot repos.

## Phase 5 — Supabase tables 🟡 PENDING

- Create `ste_` tables in the existing Supabase project (same project as
  unified engine, ref `oosqmkeucbrziplxopyg`).
- Tables: `ste_trades_bot_500__trailing_ema`, `ste_trades_bot_500__trailing_atr`,
  `ste_cycle_log`, `ste_settings`.
- Apply the unique-open-constraint partial index on both trade tables.

## Phase 6 — Streamlit Cloud deployment 🟡 PENDING

- Connect the GitHub repo to Streamlit Cloud.
- Set up secrets: `DATABASE_URL`, broker credentials (shared with unified engine).
- Deploy admin + viewer apps on separate URLs.
- Add `runtime.txt` for Python version pinning if needed.
- Wire up keep-awake GitHub Actions workflow.

## Phase 7 — Live verification 🟡 PENDING

- First real market-hours run with broker credentials.
- Verify Stage 1 fetches full Nifty500 (~500 stocks).
- Verify Stage 2 fetches 1H candles with correct lookback.
- Verify entry scan fires at correct 1H boundary times.
- Observe a full trade lifecycle: entry → target-hit → trailing-exit or SL.
- Verify CNC charges are correct on real trades.
- Verify capital compounds correctly across multi-day positions.
