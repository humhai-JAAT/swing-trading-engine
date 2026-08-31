"""Stage 2 — candle history layer. Fetches 1H candle history for the
deduplicated top-N symbols from Stage 1, shared across all variants.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import pandas as pd

from common.helpers import get_logger
from engine.broker_accounts import BrokerAccount, get_configured_accounts

logger = get_logger(__name__)

CANDLE_WORKERS_PER_ACCOUNT = 3

CALENDAR_FETCH_DAYS = 30
CANDLE_LOOKBACK_TRADING_DAYS = 15


def trim_to_last_n_trading_days(df: "pd.DataFrame | None", n_days: int) -> "pd.DataFrame | None":
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    dates = sorted(set(df.index.date))
    keep_dates = set(dates[-n_days:])
    return df[[d in keep_dates for d in df.index.date]]


@dataclass
class Stage2Result:
    candles_by_symbol: dict[str, pd.DataFrame] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    symbols_requested: int = 0
    symbols_fetched: int = 0


def merge_unique_symbols(top_lists: dict[str, pd.DataFrame]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for df in top_lists.values():
        if df is None or df.empty:
            continue
        for symbol in df["symbol"]:
            if symbol not in seen:
                seen.add(symbol)
                ordered.append(symbol)
    return ordered


def _fetch_one(account: BrokerAccount, symbol: str, interval: str, period_days: int) -> "pd.DataFrame | None":
    return account.fetch_candles(symbol, interval=interval, period_days=period_days)


def fetch_candle_history(symbols: list[str], interval: str = "1h",
                          period_days: int = CALENDAR_FETCH_DAYS,
                          primary_accounts: list[BrokerAccount] | None = None,
                          fallback_accounts: list[BrokerAccount] | None = None) -> Stage2Result:
    accounts = get_configured_accounts()
    if primary_accounts is None:
        primary_accounts = accounts["groww"] or accounts["angelone"]
    if fallback_accounts is None:
        fallback_accounts = accounts["angelone"]

    result = Stage2Result(symbols_requested=len(symbols))
    if not primary_accounts or not symbols:
        if not primary_accounts:
            result.warnings.append("No broker accounts configured for Stage 2 candle fetch.")
        return result

    workers = []
    for account in primary_accounts:
        workers.extend([account] * CANDLE_WORKERS_PER_ACCOUNT)

    failed_symbols: list[str] = []
    with ThreadPoolExecutor(max_workers=max(len(workers), 1)) as executor:
        futures = {
            executor.submit(_fetch_one, workers[i % len(workers)], symbol, interval, period_days): symbol
            for i, symbol in enumerate(symbols)
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                df = future.result()
            except Exception as e:
                logger.warning(f"Stage 2 fetch for {symbol} raised: {e}")
                df = None
            df = trim_to_last_n_trading_days(df, CANDLE_LOOKBACK_TRADING_DAYS)
            if df is not None and not df.empty:
                result.candles_by_symbol[symbol] = df
            else:
                failed_symbols.append(symbol)

    if failed_symbols and fallback_accounts:
        fallback_workers = [acct for acct in fallback_accounts for _ in range(CANDLE_WORKERS_PER_ACCOUNT)]
        still_failed = []
        with ThreadPoolExecutor(max_workers=len(fallback_workers)) as executor:
            futures = {
                executor.submit(_fetch_one, fallback_workers[i % len(fallback_workers)],
                                 symbol, interval, period_days): symbol
                for i, symbol in enumerate(failed_symbols)
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    df = future.result()
                except Exception as e:
                    logger.warning(f"Stage 2 fallback fetch for {symbol} raised: {e}")
                    df = None
                df = trim_to_last_n_trading_days(df, CANDLE_LOOKBACK_TRADING_DAYS)
                if df is not None and not df.empty:
                    result.candles_by_symbol[symbol] = df
                else:
                    still_failed.append(symbol)
        if still_failed:
            fallback_ids = ", ".join(acct.account_id for acct in fallback_accounts)
            result.warnings.append(
                f"{len(still_failed)}/{len(symbols)} symbols had no candle data even after "
                f"fallback ({fallback_ids}): {still_failed[:10]}"
                f"{'...' if len(still_failed) > 10 else ''}"
            )
    elif failed_symbols:
        result.warnings.append(
            f"{len(failed_symbols)}/{len(symbols)} symbols had no candle data and no fallback "
            f"account was configured to retry them."
        )

    result.symbols_fetched = len(result.candles_by_symbol)
    return result
