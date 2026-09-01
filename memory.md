# Memory / Progress Log — Swing Trading Engine

Project-local journal of decisions, bugs, and state — lives in the repo so
anyone (including a future AI session reading the code cold) can get oriented.

## Current state (2026-09-01)

All code built, 125 tests passing, pushed to GitHub
([humhai-JAAT/swing-trading-engine](https://github.com/humhai-JAAT/swing-trading-engine),
private). Standard project docs (PRD, Architecture, rules, Phase, design,
this file) created. Not yet deployed to Streamlit Cloud; Supabase tables not
yet created.

## Build log (2026-08-31)

Built the entire codebase in one session, adapted from the unified trading
engine. 26 source files created, covering:
- Common layer (helpers, indicators, metrics) — ported unchanged.
- Engine layer (config, costs, db, strategy, variant_engine, scheduler,
  stage1_ranking, stage2_candles, rate_limiter, broker_accounts, broker,
  live_feed, nse_universe, metrics, dashboard_view) — adapted for CNC/1H.
- Streamlit apps (app.py, viewer_app.py) — adapted for 2-variant layout.

Key adaptation decisions:
1. **CNC charges** — STT 0.1% both sides (vs MIS 0%/0.025%), Stamp 0.015%
   buy (vs 0.003%). Implemented in `engine/costs.py`.
2. **No checkpoint system** — subh30 is irrelevant for 1H candles. Entry scans
   run via CronTrigger at fixed 1H-boundary+1 offsets.
3. **No square-off** — CNC positions carry forward until exit signal.
4. **Capital tracking** — sums ALL closed trades (not just today's). Same for
   arm cycle dedup — queries ALL historical trades.
5. **Candle lookback** — 30 calendar days / 15 trading days for 1H bars
   (vs 12/4 for 5-min in unified engine). Ensures 109+ bars for EMA100 warm-up.

## Test suite (2026-08-31)

125 tests across 9 files. Initial run: 17 failures due to:
- `test_costs.py`: wrong attribute names (`exchange_txn` → `exchange_charge`,
  `sebi` → `sebi_charge`, `ipft` → `ipft_charge`), GST/total formulas missing
  brokerage.
- `test_metrics.py`: functions expected `pd.Series`, tests passed Python lists.
  `wilson_lower_bound_win_rate` takes a Series, not `(wins, total)` ints.
- `test_db.py`: `close_trade` called with trade_id where variant_id expected.
- `test_nse_universe.py`: mock lambda signature mismatch (`force_refresh`).

All 17 fixed same session → 125/125 passing.

## Git history

1. `5eb3ed6` — Initial commit: 26 source files.
2. `6c808af` — Add comprehensive test suite: 9 test files, 125 tests.
3. Standard project docs commit — PRD, Architecture, rules, Phase, design, memory.

## Shared resources with unified engine

- **Broker accounts**: same Groww + Angel One credentials (shared, not separate).
- **Supabase project**: same project (`oosqmkeucbrziplxopyg`), different table
  prefix (`ste_` vs `ute_`).
- **Strategy**: EMA-MACD V2.1.2 — timeframe-agnostic, identical code.
