# Rules — boundaries for AI-assisted work on this project

Adapted from the unified trading engine's rules, plus CNC-specific constraints.

## Absolute boundaries — never do these

- **Never place a real trade or wire up any live broker order-execution API.**
  This project is paper-trading only, permanently.
- **Never commit secrets, API keys, tokens, or passwords to git.** Credentials
  live in Streamlit Cloud Secrets / `.streamlit/secrets.toml` (gitignored) only.
- **Never run a destructive database operation** against production data without
  the user explicitly asking for it in that moment.
- **Never `git push` without being explicitly told to.** Local commits are fine;
  pushing is a separate, explicit step.
- **Never merge this codebase with any sibling trading bot project** — own venv,
  own repo, own DB tables (`ste_` prefix). See `trading_projects_separation.md`
  in the private memory system.
- **Never reintroduce the old `vN`/`vN_M` naming convention** — this project
  uses `{universe_bot}/{variant_key}` naming (`bot_500/trailing_ema`, etc.).
- **Never add intraday square-off logic.** This is CNC carry-forward — positions
  hold until SL/target/trailing exit, never forced closed at market close.
- **Never let a shared-data fetch failure fail silently.** Partial data or a
  fallback-path trigger must surface as a visible dashboard warning.
- **Never let two threads share an `AccountRateLimiter` without its lock.**
- **Before starting a new bot variant anywhere in `D:\schedule EB`, check whether
  an existing project already covers the idea.**
- **Never delete a project folder without explicit user confirmation**, and
  always verify `git status` is clean and everything is pushed before deleting.

## Library / dependency policy

Same stack as the unified engine: `pandas`, `SQLAlchemy`, `requests`,
`streamlit`, `APScheduler`, `pytz`, `numpy`, plus broker SDKs. Don't introduce
a new dependency for something this stack already covers.

## Error handling philosophy

- External API calls must fail *closed* into chunk-level fallback, never crash
  the whole cycle.
- A failed chunk's fallback must retry ONLY that chunk.
- Financial calculations need explicit, testable formulas — work through the
  algebra with concrete numbers.

## CNC-specific rules

- Capital tracking must sum ALL closed trades (not just today's).
- Arm cycle dedup must check ALL historical trades (not just today's).
- CNC charges (STT 0.1% both sides, Stamp 0.015% buy) — never use MIS rates.
- Candle lookback: 30 calendar days / 15 trading days for 1H bars — never use
  the unified engine's 12/4 intraday lookback.

## What the AI can do without asking

- Write and locally test code.
- Investigate broker API rate limits/pricing.
- Flag discovered bugs, dead code, or design tensions proactively.
- Update this project's own memory/progress docs.

## What the AI must confirm first

- Any destructive or irreversible action (see Absolute Boundaries).
- Any change to the entry/exit rules, capital model, or variant structure.
- Any change to broker account assignments.
- Combining or restructuring this project with any other trading-bot project.
