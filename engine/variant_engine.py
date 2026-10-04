"""Per-variant trailing-exit logic — 2 variants (1 universe-bot x 2 exit
styles), each run against the SHARED data Stage 1/Stage 2 fetched once per
cycle. No subh30 checkpoints, no intraday square-off — CNC carry-forward.

Exit: stop-loss and target are fixed %. Touching the target records when it
happened (target_hit_at); from then on the target level is a hard floor (a
1-minute low at or below it exits there), and the trailing MECHANISM runs on
1H candles that closed after the touch:
  'ema' — exits when a 1H candle closes below its own EMA9.
  'atr' — exits when price pulls back more than atr_multiplier*ATR from the
          peak reached since entry.
Trailing exits fill at the current price, not at the triggering candle's close.
"""

from datetime import datetime, time as dtime, timedelta

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

SLIPPAGE_PCT = 0.05


SESSION_END = dtime(15, 30)


def candle_closes_at(start: pd.Timestamp) -> pd.Timestamp:
    """Candles are stamped with their START time and NSE 1H candles begin at :15,
    so the candle stamped H:15 closes at (H+1):15 — except the final 15:15 one,
    which the session cuts short at 15:30. (Comparing hours instead misjudges a
    forming candle between X:00 and X:15.)"""
    return min(start + timedelta(hours=1), start.replace(hour=SESSION_END.hour, minute=SESSION_END.minute))


def discard_incomplete_candle(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the last row if that candle has not closed yet."""
    if df is None or df.empty:
        return df
    if datetime.now(IST) < candle_closes_at(df.index[-1]):
        return df.iloc[:-1]
    return df


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


def fetch_minute_candles(symbol: str) -> "tuple[BrokerAccount | None, pd.DataFrame | None, list[str]]":
    failed_accounts = []
    for account in _position_data_accounts():
        try:
            df = account.fetch_candles(symbol, interval="1m", period_days=1)
        except Exception as e:
            failed_accounts.append(f"{account.account_id}: {e}")
            continue
        if df is not None and not df.empty:
            return account, df, failed_accounts
        failed_accounts.append(f"{account.account_id}: empty response")
    return None, None, failed_accounts


def manage_open_position(variant_id: str, variant_cfg: dict, trade: dict, settings: dict,
                          now: datetime, minute_data: tuple | None = None) -> dict:
    symbol = trade["symbol"]
    account, df_1m, failed_accounts = minute_data or fetch_minute_candles(symbol)
    if account is None:
        reason = "no_price_data" if failed_accounts else "no_broker_account_configured"
        return {"action": "hold", "reason": reason, "symbol": symbol, "failed_accounts": failed_accounts}

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

    hit_at = trade.get("target_hit_at")
    reason = None
    exit_price = price

    if not hit_at:
        for ts, row in since_entry.iterrows():
            if row["Low"] <= stop_price:  # also when target and stop share a bar: assume the stop came first
                reason, exit_price = "STOP_LOSS", min(stop_price, row["Open"])
                break
            if row["High"] >= target_price:
                hit_at = ts.isoformat()
                db.mark_target_hit(variant_id, trade["id"], hit_at)
                break

    if reason is None and hit_at:
        hit_ts = _timestamp_ist(hit_at)
        after_hit = since_entry[since_entry.index > hit_ts]
        below = after_hit[after_hit["Low"] <= target_price]
        if not below.empty:
            reason, exit_price = "TARGET_FLOOR", min(target_price, float(below["Open"].iloc[0]))
        else:
            df_1h = account.fetch_candles(symbol, interval="1h", period_days=CALENDAR_FETCH_DAYS)
            df_1h = discard_incomplete_candle(trim_to_last_n_trading_days(df_1h, CANDLE_LOOKBACK_TRADING_DAYS))
            # only candles that closed after the touch count as trailing signals
            if df_1h is not None and not df_1h.empty and candle_closes_at(df_1h.index[-1]) > hit_ts:
                exit_style = variant_cfg["exit_style"]
                if exit_style == "ema":
                    triggered = check_ema9_trail_exit(df_1h)
                else:
                    triggered = check_atr_trail_exit(df_1h, peak, settings["atr_period"], settings["atr_multiplier"])
                if triggered is not None:
                    reason = _TRAIL_EXIT_REASON[exit_style]  # fills at the current price, not the candle close

    # No square-off — CNC carry-forward, positions hold until SL/target floor/trailing exit
    if reason:
        exit_price -= exit_price * SLIPPAGE_PCT / 100
    pnl_pct = (exit_price - trade["entry_price"]) * quantity / capital_used * 100

    if reason:
        result = broker.exit_position(variant_id, trade["id"], trade["quantity"], exit_price, reason)
        return {"action": "exit", "symbol": symbol, "price": exit_price, "pnl_pct": pnl_pct,
                "reason": reason, "target_hit": bool(hit_at), **result}

    return {"action": "hold", "symbol": symbol, "price": price, "pnl_pct": pnl_pct,
            "peak": peak, "trough": trough, "target_hit": bool(hit_at)}


def scan_for_entry(universe_bot_key: str, variant_cfg: dict, settings: dict, now: datetime,
                    top_n_df: pd.DataFrame, candles_by_symbol: dict[str, pd.DataFrame],
                    was_flat: bool, indicator_cache: dict[str, pd.DataFrame] | None = None,
                    session_opens: dict[str, float] | None = None) -> dict:
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
                check = (strategy.decide_entry(enriched, used_arm_cycles=used_arm_cycles)
                         if enriched is not None
                         else strategy.EntryCheck(False, None, float(candle_df["Close"].iloc[-1]),
                                                   "insufficient_history"))
            else:
                check = strategy.check_entry(candle_df, used_arm_cycles=used_arm_cycles)
        except Exception as e:
            logger.error(f"check_entry crashed for {variant_id}/{symbol}: {type(e).__name__}: {e}")
            candidates_checked.append({"symbol": symbol, "signal": False,
                                        "reason": f"error: {type(e).__name__}: {e}"})
            continue
        reason, entry_price = check.reason, check.close
        if check.signal and candle_df.index[-1].date() < now.date():
            # the previous session's last candle signalled: the rules fill it at today's open
            entry_price = (session_opens or {}).get(symbol)
            if entry_price is None:
                reason = "no_session_open"
        trade = None
        if check.signal and entry_price is not None:
            try:
                trade = broker.enter_position(variant_id, symbol, entry_price, settings["starting_capital"],
                                               check.arm_cycle_id, settings.get("leverage_multiplier", 1.0))
            except ValueError as e:  # capital can't buy a single share: try the next candidate
                reason = f"unaffordable: {e}"
        candidates_checked.append({"symbol": symbol, "signal": bool(check.signal), "reason": reason})
        if trade:
            return {"action": "enter", "candidates": candidates_checked, "entered": trade}

    return {"action": "no_signal", "candidates": candidates_checked}
