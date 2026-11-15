"""Swing Trading Engine configuration — 1H timeframe, CNC carry-forward,
full Nifty500 universe (single universe-bot), 3 variants sharing the same
entry (trailing_ema, trailing_atr, ema30_15m — see each variant's exit in
variant_engine.py). Adapted from the unified trading engine's multi-universe,
multi-variant intraday design.
"""

import json

SETTINGS_KEY = "strategy_settings"

UNIVERSE_BOTS = [
    {"key": "bot_500", "label": "Bot 500 - Full Nifty500", "universe": "nifty500"},
]
UNIVERSE_BOTS_BY_KEY = {b["key"]: b for b in UNIVERSE_BOTS}

VARIANTS = [
    {"key": "trailing_ema", "exit_style": "ema"},
    {"key": "trailing_atr", "exit_style": "atr"},
    # Added 2026-11-15 (user): same entry, exit = fixed stop-loss for the whole trade OR a
    # 15-minute candle closing below its EMA30. No target, no floor.
    {"key": "ema30_15m", "exit_style": "ema30_15m"},
]
VARIANTS_BY_KEY = {v["key"]: v for v in VARIANTS}


def all_variant_ids() -> list[str]:
    """Every `{universe_bot}/{variant_key}` combination — 1 x 3 = 3."""
    return [f"{b['key']}/{v['key']}" for b in UNIVERSE_BOTS for v in VARIANTS]


def variant_capital(variant_cfg: dict, settings: dict) -> float:
    """A variant's own starting capital, else the shared `starting_capital` setting."""
    return float(variant_cfg.get("starting_capital", settings["starting_capital"]))


DEFAULTS = {
    "starting_capital": 50000,  # per variant; Rs 10k until 2026-11-15 (user raised all three to 50k)
    "leverage_multiplier": 1.0,
    "profit_target_pct": 3.0,
    "stop_loss_pct": 1.5,
    "wake_time": "09:00",
    "sleep_time": "16:00",
    "gainers_pool_size": 50,
    "scan_interval_minutes": 60,
    "position_management_interval_minutes": 2,
    "atr_period": 14,
    "atr_multiplier": 1.5,
    "candle_interval": "1h",
    "candle_fetch_calendar_days": 45,
    "candle_lookback_trading_days": 25,
    "public_variant": "",
}


def load_settings() -> dict:
    from engine import db  # db imports config at module level
    saved = db.get_setting(SETTINGS_KEY)
    return {**DEFAULTS, **(json.loads(saved) if saved else {})}


def save_settings(settings: dict) -> None:
    from engine import db
    db.set_setting(SETTINGS_KEY, json.dumps(settings))
