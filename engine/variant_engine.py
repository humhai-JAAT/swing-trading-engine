"""Per-variant trailing-exit logic — 2 variants (1 universe-bot x 2 exit
styles), each run against the SHARED data Stage 1/Stage 2 fetched once per
cycle. No subh30 checkpoints, no intraday square-off — CNC carry-forward.

Exit: stop-loss and target are fixed %, but reaching the target flips the
position into trailing mode (mark_target_hit), and the trailing MECHANISM
differs:
  'ema' — exits when a 1H candle closes below its own EMA9.
  'atr' — exits when price pulls back more than atr_multiplier*ATR from the
          peak reached since entry.
Both share a hard floor once trailing is active: exit price can never be below
the original target level.
"""

from datetime import datetime, time as dtime

import pandas as pd
import pytz

from common import indicators
from common.helpers import get_logger
from engine import broker, config, db, strategy
from engine.broker_accounts import BrokerAccount, get_configured_accounts
from engine.stage2_candles import CALENDAR_FETCH_DAYS, CANDLE_LOOKBACK_TRADING_DAYS, trim_to_last_n_trading_days

logger = get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_TRAIL_EXIT_REASON = {"ema": "EMA_TRAIL_EXIT", "atr": "ATR_TRAIL_EXIT"}


def _timestamp_ist(time_str: str) -> pd.Timestamp:
    ts = pd.Timestamp(time_str)
    return IST.localize(ts) if ts.tzinfo is None else ts.tz_convert(IST)


def check_ema9_trail_exit(candle_df: pd.DataFrame) -> float | None:
    if candle_df is None or candle_df.empty or len(candle_df) < 10:
        return None
    ema9 = indicators.ema(candle_df["Close"], 9)
    last_close = float(candle_df["Close"].iloc[-1])
    if last_close < float(ema9.iloc[-1]):
        return last_close
    return None


def check_atr_trail_exit(candle_df: pd.DataFrame, peak_price: float, atr_period: int,
                          atr_multiplier: float) -> float | None:
    if candle_df is None or candle_df.empty or len(candle_df) < atr_period + 1:
        return None
    atr_series = indicators.atr(candle_df, atr_period)
    last_close = float(candle_df["Close"].iloc[-1])
    last_atr = float(atr_series.iloc[-1])
    if (peak_price - last_close) >= atr_multiplier * last_atr:
        return last_close
    return None


def _position_data_accounts() -> list[BrokerAccount]:
    accounts = get_configured_accounts()
    return accounts["groww"] + accounts["angelone"]


def manage_open_position(variant_id: str, variant_cfg: dict, trade: dict, settings: dict,
                          now: datetime) -> dict:
    accounts = _position_data_accounts()
    if not accounts:
        return {"action": "hold", "reason": "no_broker_account_configured", "symbol": trade["symbol"]}

    symbol = trade["symbol"]
    account = None
    df_1m = None
    failed_accounts = []
    for candidate in accounts:
        try:
            candidate_df = candidate.fetch_candles(symbol, interval="1m", period_days=1)
        except Exception as e:
            failed_accounts.append(f"{candidate.account_id}: {e}")
            continue
        if candidate_df is not None and not candidate_df.empty:
            account, df_1m = candidate, candidate_df
            break
        failed_accounts.append(f"{candidate.account_id}: empty response")

    if account is None:
        return {"action": "hold", "reason": "no_price_data", "symbol": symbol,
                "failed_accounts": failed_accounts}

    return locked_decide_and_exit(variant_id, variant_cfg, trade, settings, now, account, symbol, df_1m)


def locked_decide_and_exit(variant_id: str, variant_cfg: dict, trade: dict, settings: dict, now: datetime,
                            account: BrokerAccount, symbol: str, df_1m: pd.DataFrame) -> dict:
    with db.acquire_trade_lock(variant_id):
        fresh_trade = db.get_open_trade(variant_id)
        if fresh_trade is None or fresh_trade["id"] != trade["id"]:
            return {"action": "hold", "reason": "already_closed", "symbol": symbol}

        return _decide_and_exit(variant_id, variant_cfg, fresh_trade, settings, now, account, symbol, df_1m)


def _decide_and_exit(variant_id: str, variant_cfg: dict, trade: dict, settings: dict, now: datetime,
                      account: BrokerAccount, symbol: str, df_1m: pd.DataFrame) -> dict:
    entry_time = _timestamp_ist(trade["entry_time"])
    quantity = trade["quantity"]
    capital_used = trade["capital_used"]
    target_price = trade["entry_price"] + (capital_used * settings["profit_target_pct"] / 100) / quantity
    stop_price = trade["entry_price"] - (capital_used * settings["stop_loss_pct"] / 100) / quantity

    since_entry = df_1m[df_1m.index >= entry_time]
    if since_entry.empty:
        since_entry = df_1m.tail(1)
    price = float(since_entry["Close"].iloc[-1])
    recent_high = float(since_entry["High"].max())
    recent_low = float(since_entry["Low"].min())
    peak, trough = broker.update_extremes(variant_id, trade["id"], trade["peak_price"], trade["trough_price"],
                                           recent_high, recent_low)

    target_hit = bool(trade.get("target_hit"))
    reason = None
    exit_price = price

    if not target_hit:
        for _, row in since_entry.iterrows():
            if row["Low"] <= stop_price:
                reason, exit_price = "STOP_LOSS", stop_price
                break
            if row["High"] >= target_price:
                target_hit = True
                break
        if target_hit and reason is None:
            db.mark_target_hit(variant_id, trade["id"])

    if reason is None and target_hit:
        df_1h = account.fetch_candles(symbol, interval="1h", period_days=CALENDAR_FETCH_DAYS)
        df_1h = trim_to_last_n_trading_days(df_1h, CANDLE_LOOKBACK_TRADING_DAYS)
        exit_style = variant_cfg["exit_style"]
        if exit_style == "ema":
            trail_price = check_ema9_trail_exit(df_1h)
        else:
            trail_price = check_atr_trail_exit(df_1h, peak, settings["atr_period"], settings["atr_multiplier"])
        if trail_price is not None:
            reason = _TRAIL_EXIT_REASON[exit_style]
            exit_price = max(trail_price, target_price)

    # No square-off — CNC carry-forward, positions hold until SL/target/trailing exit

    pnl_pct = (exit_price - trade["entry_price"]) * quantity / capital_used * 100

    if reason:
        result = broker.exit_position(variant_id, trade["id"], trade["quantity"], exit_price, reason)
        return {"action": "exit", "symbol": symbol, "price": exit_price, "pnl_pct": pnl_pct,
                "reason": reason, "target_hit": target_hit, **result}

    return {"action": "hold", "symbol": symbol, "price": price, "pnl_pct": pnl_pct,
            "peak": peak, "trough": trough, "target_hit": target_hit}


def scan_for_entry(universe_bot_key: str, variant_cfg: dict, settings: dict, now: datetime,
                    top_n_df: pd.DataFrame, candles_by_symbol: dict[str, pd.DataFrame],
                    was_flat: bool, indicator_cache: dict[str, pd.DataFrame] | None = None) -> dict:
    variant_id = f"{universe_bot_key}/{variant_cfg['key']}"

    if not was_flat:
        return {"action": "skip_scan", "reason": "already_in_position"}

    candidates_checked = []
    for symbol in top_n_df["symbol"].tolist() if not top_n_df.empty else []:
        candle_df = candles_by_symbol.get(symbol)
        if candle_df is None or candle_df.empty:
            candidates_checked.append({"symbol": symbol, "signal": False, "reason": "no_candle_data"})
            continue

        try:
            used_arm_cycles = db.get_arm_cycles_used(variant_id, symbol)
            if indicator_cache is not None:
                enriched = indicator_cache.get(symbol)
                check = (strategy.decide_entry(enriched, used_arm_cycles=used_arm_cycles, today=now)
                         if enriched is not None
                         else strategy.EntryCheck(False, None, float(candle_df["Close"].iloc[-1]),
                                                   "insufficient_history"))
            else:
                check = strategy.check_entry(candle_df, used_arm_cycles=used_arm_cycles, today=now)
        except Exception as e:
            logger.error(f"check_entry crashed for {variant_id}/{symbol}: {type(e).__name__}: {e}")
            candidates_checked.append({"symbol": symbol, "signal": False,
                                        "reason": f"error: {type(e).__name__}: {e}"})
            continue
        candidates_checked.append({"symbol": symbol, "signal": bool(check.signal), "reason": check.reason})

        if check.signal:
            starting_capital = settings["starting_capital"]
            leverage = settings.get("leverage_multiplier", 1.0)
            trade = broker.enter_position(variant_id, symbol, check.close, starting_capital,
                                           check.arm_cycle_id, leverage)
            return {"action": "enter", "candidates": candidates_checked, "entered": trade}

    return {"action": "no_signal", "candidates": candidates_checked}
