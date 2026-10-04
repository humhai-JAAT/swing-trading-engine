"""NSE Nifty500 universe — full 500-stock list, no subset filtering needed
since this project uses a single universe-bot (bot_500).
"""

import time

import pandas as pd
import requests

from common.helpers import PROJECT_ROOT, get_logger

logger = get_logger(__name__)

_INDEX_URLS = {
    "nifty500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

INDEX_CACHE_TTL_DAYS = 7


def _fetch_index_symbols(index_key: str, force_refresh: bool = False) -> list[str]:
    url = _INDEX_URLS[index_key]
    cache_path = PROJECT_ROOT / "data" / f"{index_key}_list.csv"
    if not force_refresh and cache_path.exists():
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400
        if age_days < INDEX_CACHE_TTL_DAYS:
            return pd.read_csv(cache_path)["Symbol"].tolist()

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(resp.content)
        return pd.read_csv(cache_path)["Symbol"].tolist()
    except Exception as e:
        logger.warning(f"{index_key} list fetch failed ({e}), using cached copy if any")
        if cache_path.exists():
            return pd.read_csv(cache_path)["Symbol"].tolist()
        raise


def get_universe_symbols(universe: str, force_refresh: bool = False) -> set[str]:
    if universe == "nifty500":
        return set(_fetch_index_symbols("nifty500", force_refresh))
    raise ValueError(f"Unknown universe: {universe!r}")


def filter_to_universe(rank_list: pd.DataFrame, universe: str, top_n: int,
                        force_refresh: bool = False) -> tuple[pd.DataFrame, list[str]]:
    universe_symbols = get_universe_symbols(universe, force_refresh)
    present = set(rank_list["symbol"]) if not rank_list.empty else set()
    missing = sorted(universe_symbols - present)

    filtered = rank_list[rank_list["symbol"].isin(universe_symbols)]
    top = filtered.sort_values("pct_change", ascending=False).head(top_n).reset_index(drop=True)
    return top, missing
