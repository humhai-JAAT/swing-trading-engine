"""Persistent Groww websocket (GrowwFeed) listener for tick-driven stop-loss/
target/trailing-exit reaction on OPEN positions — much faster than waiting for
the 2-min REST position-management job.

Only covers positions whose data can come from a configured Groww account.
If no Groww account is configured, start() is a no-op and the 2-min REST job
remains the only path.

Runs as a single daemon background thread. Every poll_interval_seconds (default 2s):
  1. re-syncs subscriptions to whichever symbols currently have an open position
     across both variants (at most 2 symbols).
  2. reads the latest LTP via GrowwFeed.get_all_feed()
  3. for each open position with a fresh tick, builds a synthetic single-row
     candle and runs locked_decide_and_exit().
"""

import threading
import time
from datetime import datetime

import pandas as pd
import pytz

from common.helpers import get_logger
from engine import config, db
from engine.broker_accounts import GrowwAccount, get_configured_accounts
from engine.variant_engine import locked_decide_and_exit

logger = get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

DEFAULT_POLL_INTERVAL_SECONDS = 2.0
SYMBOL_TOKEN_CACHE_TTL_SECONDS = 3600

_thread: threading.Thread | None = None
_stop_event = threading.Event()
_feed = None
_subscribed_tokens: dict[str, str] = {}
_subscribed_tokens_lock = threading.Lock()
_symbol_token_cache: dict[str, str] = {}
_symbol_token_cache_loaded_at = 0.0


def _groww_account() -> GrowwAccount | None:
    pool = get_configured_accounts().get("groww") or []
    return pool[0] if pool else None


def _all_open_trades() -> dict[str, dict]:
    open_trades = {}
    for universe_bot in config.UNIVERSE_BOTS:
        for variant_cfg in config.VARIANTS:
            variant_id = f"{universe_bot['key']}/{variant_cfg['key']}"
            trade = db.get_open_trade(variant_id)
            if trade:
                open_trades[variant_id] = trade
    return open_trades


def _instrument(token: str) -> dict:
    return {"exchange": "NSE", "segment": "CASH", "exchange_token": token}


def _get_symbol_to_token(account: GrowwAccount) -> dict[str, str]:
    global _symbol_token_cache, _symbol_token_cache_loaded_at
    if not _symbol_token_cache or time.time() - _symbol_token_cache_loaded_at > SYMBOL_TOKEN_CACHE_TTL_SECONDS:
        _symbol_token_cache = account._load_symbol_to_token()
        _symbol_token_cache_loaded_at = time.time()
    return _symbol_token_cache


def _sync_subscriptions(account: GrowwAccount, feed, open_trades: dict[str, dict]) -> None:
    global _subscribed_tokens

    wanted_symbols = {trade["symbol"] for trade in open_trades.values()}
    symbol_to_token = _get_symbol_to_token(account) if wanted_symbols else {}
    wanted_tokens: dict[str, str] = {}
    for sym in wanted_symbols:
        token = symbol_to_token.get(sym)
        if token:
            wanted_tokens[token] = sym
        else:
            logger.warning(f"live_feed: no exchange_token found for {sym!r}, cannot subscribe")

    with _subscribed_tokens_lock:
        current = dict(_subscribed_tokens)
    to_add = {tok: sym for tok, sym in wanted_tokens.items() if tok not in current}
    to_remove = {tok: sym for tok, sym in current.items() if tok not in wanted_tokens}

    if to_remove:
        try:
            feed.unsubscribe_ltp([_instrument(tok) for tok in to_remove])
        except Exception as e:
            logger.warning(f"live_feed: unsubscribe failed for {list(to_remove.values())}: {e}")

    if to_add:
        try:
            feed.subscribe_ltp([_instrument(tok) for tok in to_add])
        except Exception as e:
            logger.warning(f"live_feed: subscribe failed for {list(to_add.values())}: {e}")
            wanted_tokens = {tok: sym for tok, sym in wanted_tokens.items() if tok not in to_add}

    with _subscribed_tokens_lock:
        _subscribed_tokens = wanted_tokens


def _check_tick(variant_id: str, variant_cfg: dict, trade: dict, settings: dict, now: datetime,
                account: GrowwAccount, symbol: str, ltp: float) -> None:
    tick_df = pd.DataFrame(
        {"Open": [ltp], "High": [ltp], "Low": [ltp], "Close": [ltp]},
        index=pd.DatetimeIndex([now]).tz_localize(IST) if now.tzinfo is None else pd.DatetimeIndex([now]),
    )
    try:
        result = locked_decide_and_exit(variant_id, variant_cfg, trade, settings, now, account, symbol, tick_df)
        if result.get("action") == "exit":
            logger.info(f"live_feed: [{variant_id}] tick-driven exit "
                        f"{result.get('reason')} @ {result.get('price')}")
    except Exception as e:
        logger.warning(f"live_feed: check failed for {variant_id}/{symbol}: {e}")


def _poll_once(account: GrowwAccount, feed) -> None:
    settings = config.load_settings()
    now = datetime.now(IST)
    open_trades = _all_open_trades()

    _sync_subscriptions(account, feed, open_trades)
    if not open_trades:
        return

    try:
        feed_data = feed.get_all_feed()
    except Exception as e:
        logger.warning(f"live_feed: get_all_feed failed: {e}")
        return
    ltp_by_token = feed_data.get("ltp", {}).get("NSE", {}).get("CASH", {})

    token_by_symbol = {sym: tok for tok, sym in _subscribed_tokens.items()}
    for variant_id, trade in open_trades.items():
        universe_key, variant_key = variant_id.split("/", 1)
        variant_cfg = config.VARIANTS_BY_KEY[variant_key]
        symbol = trade["symbol"]
        token = token_by_symbol.get(symbol)
        if token is None:
            continue
        tick = ltp_by_token.get(token)
        if not tick or not tick.get("ltp"):
            continue
        _check_tick(variant_id, variant_cfg, trade, settings, now, account, symbol, float(tick["ltp"]))


def _run_loop(poll_interval_seconds: float) -> None:
    global _feed
    account = _groww_account()
    if account is None:
        logger.info("live_feed: no Groww account configured, thread exiting "
                     "(2-min REST position-management job remains active)")
        return

    try:
        from growwapi import GrowwFeed
        client = account.get_client()
        if client is None:
            logger.warning("live_feed: Groww client unavailable, thread exiting")
            return
        _feed = GrowwFeed(client)
    except Exception as e:
        logger.warning(f"live_feed: could not connect GrowwFeed: {e}")
        return

    logger.info("live_feed: connected, entering poll loop")
    while not _stop_event.is_set():
        try:
            _poll_once(account, _feed)
        except Exception as e:
            logger.warning(f"live_feed: poll loop iteration failed: {e}")
        _stop_event.wait(poll_interval_seconds)

    logger.info("live_feed: stopped")


def start(poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> bool:
    global _thread
    if _groww_account() is None:
        logger.info("live_feed.start(): no Groww account configured, skipping")
        return False
    if _thread is not None and _thread.is_alive():
        return True
    _stop_event.clear()
    _thread = threading.Thread(target=_run_loop, args=(poll_interval_seconds,),
                                daemon=True, name="ste-live-feed")
    _thread.start()
    return True


def stop(timeout_seconds: float = 5.0) -> None:
    global _feed, _subscribed_tokens
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=timeout_seconds)
        if _thread.is_alive():
            logger.warning("live_feed.stop(): thread still alive after timeout")
    _feed = None
    with _subscribed_tokens_lock:
        _subscribed_tokens = {}


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
