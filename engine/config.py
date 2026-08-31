"""Swing Trading Engine configuration — 1H timeframe, CNC carry-forward,
full Nifty500 universe (single universe-bot), 2 variants (trailing_ema,
trailing_atr). Adapted from the unified trading engine's multi-universe,
multi-variant intraday design.
"""

import yaml

from common.helpers import PROJECT_ROOT

SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

UNIVERSE_BOTS = [
    {"key": "bot_500", "label": "Bot 500 - Full Nifty500", "universe": "nifty500"},
]
UNIVERSE_BOTS_BY_KEY = {b["key"]: b for b in UNIVERSE_BOTS}

VARIANTS = [
    {"key": "trailing_ema", "exit_style": "ema"},
    {"key": "trailing_atr", "exit_style": "atr"},
]
VARIANTS_BY_KEY = {v["key"]: v for v in VARIANTS}


def all_variant_ids() -> list[str]:
    """Every `{universe_bot}/{variant_key}` combination — 1 x 2 = 2."""
    return [f"{b['key']}/{v['key']}" for b in UNIVERSE_BOTS for v in VARIANTS]


DEFAULTS = {
    "starting_capital": 10000,
    "leverage_multiplier": 1.0,
    "profit_target_pct": 3.0,
    "stop_loss_pct": 1.5,
    "wake_time": "09:00",
    "sleep_time": "16:00",
    "gainers_pool_size": 30,
    "scan_interval_minutes": 60,
    "position_management_interval_minutes": 2,
    "atr_period": 14,
    "atr_multiplier": 1.5,
    "candle_interval": "1h",
    "candle_fetch_calendar_days": 30,
    "candle_lookback_trading_days": 15,
    "public_variant": "",
}


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULTS)
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return {**DEFAULTS, **cfg}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(settings, f, sort_keys=False, default_flow_style=False)
