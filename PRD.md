# PRD — Swing Trading Engine

## What we're building

A paper-trading (simulated, zero real capital at risk) **swing trading** bot for
NSE-listed stocks using **1-hour candles** and **CNC (Cash & Carry) delivery
orders** — positions carry forward across days until a stop-loss, target, or
trailing exit triggers. This is a direct architectural replica of the
`unified-trading-engine` (intraday, 5-min, MIS), adapted for a longer timeframe
and carry-forward mechanics.

Same entry strategy as the unified engine: EMA9/EMA30 crossover + MACD(12,26,9)
bullish + EMA100 > SMA9(EMA100) trend filter + 0.6% min EMA separation
(EMA-MACD V2.1.2), evaluated on **1-hour candles** instead of 5-minute.

## Why this project exists

The unified trading engine proved the shared-data architecture (fetch once,
share across variants) and the EMA-MACD V2.1.2 strategy work on a 5-min
intraday timeframe. This project tests the **same strategy on a higher
timeframe** (1H) with delivery-mode positions that carry forward — answering
whether the signals that work intraday also work for multi-day swing trades.

Key differences from the unified engine:
- **1H candles** (not 5-min) — fewer signals, longer hold times.
- **CNC delivery** (not MIS intraday) — no daily square-off, positions hold
  until SL/target/trailing exit.
- **Different charge model** — CNC delivery charges: STT 0.1% both buy AND
  sell (vs MIS 0%/0.025%), Stamp duty 0.015% buy only.
- **Capital compounds across all trades** — `get_starting_capital()` sums ALL
  closed trades' P&L (not just today's), since positions span multiple days.
- **No checkpoint system** — the unified engine's subh30 checkpoint gating is
  irrelevant for hourly candles; entry scans run at fixed 1H-boundary offsets.

## Core structure: 1 universe-bot × 2 variants = 2 total

| Universe-bot | Stock universe | Approx size |
|---|---|---|
| `bot_500` | Full Nifty 500 | ~500 |

**2 variants** (trailing-exit style only — no entry-timing axis, since there
are no subh30/puradin checkpoint alternatives on a 1H timeframe):

| Variant key | Exit behavior |
|---|---|
| `trailing_ema` | Fixed SL 1.5%; once fixed target 3% is first reached, flips to EMA9-close-below trailing on 1H candles |
| `trailing_atr` | Fixed SL 1.5%; once fixed target 3% is first reached, flips to ATR-pullback trailing |

2 variants total, one process, one database, one dashboard.

## The 2-stage shared data pipeline

Same architecture as the unified engine, simplified for 1 universe-bot:

**Stage 1 — ranking data**: fetch today's %-change for all ~500 Nifty500 stocks
ONCE per cycle, split across parallel workers (multi-broker accounts). Top-N
(`gainers_pool_size`, default 30) derived from one ranked list.

**Stage 2 — candle history**: fetch **1H candle history** (30 calendar days /
15 trading days lookback — enough for EMA100 + SMA9 warm-up requiring 109+
bars) ONLY for the top-N symbols. Shared read-only across both variants.

## Entry scan schedule

5 scans per trading day, each 1 minute after the corresponding 1H candle closes:
- 10:16, 11:16, 12:16, 13:16, 14:16

## Who this is for

Same single retail trader as the unified engine — forward-testing whether the
EMA-MACD V2.1.2 strategy works on a 1H swing timeframe with CNC carry-forward,
risk-free.

## Explicitly out of scope

- Real order execution / any live broker order-placement integration.
- More than 1 concurrent position per variant.
- Merging or sharing code/DB with any sibling trading bot project.
- Intraday square-off logic — positions carry forward by design.
- Subh30/puradin checkpoint system — irrelevant for hourly candles.

## Known accepted cost

Same broker accounts as the unified engine (shared Groww + Angel One), same
Supabase project (different table prefix: `ste_` vs `ute_`).
