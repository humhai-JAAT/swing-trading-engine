"""Multi-broker, multi-account registry — shared with the unified trading
engine's broker accounts (same env vars / Streamlit secrets). Adapted from
the unified engine's broker_accounts.py — identical broker integration code,
this project just reads from the same credential slots.
"""

import base64
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyotp
import pytz
import requests

from common.helpers import PROJECT_ROOT, get_logger
from engine.rate_limiter import AccountRateLimiter

logger = get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _jwt_exp_timestamp(token: str) -> float | None:
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload["exp"])
    except Exception as e:
        logger.warning(f"Could not decode JWT exp claim: {e}")
        return None


def _http_error_detail(e: "requests.exceptions.HTTPError") -> str:
    resp = e.response
    if resp is None:
        return str(e)
    try:
        return f"{e} | body: {resp.json()}"
    except Exception:
        return f"{e} | body: {resp.text[:300]}"


ANGELONE_QUOTE_RATE_SECONDS = 1.1
ANGELONE_CANDLE_RATE_SECONDS = 0.4
GROWW_QUOTE_RATE_SECONDS = 0.12
GROWW_CANDLE_RATE_SECONDS = 0.12
ANGELONE_QUOTE_BATCH_SIZE = 50
GROWW_QUOTE_BATCH_SIZE = 50
ANGELONE_SESSION_TTL_SECONDS = 2 * 3600
GROWW_TOKEN_REFRESH_BUFFER_SECONDS = 5 * 60


@dataclass
class QuoteResult:
    symbol: str
    last_price: float
    pct_change: float


class BrokerAccount:
    account_id: str
    broker: str

    def __init__(self):
        self.quote_limiter = AccountRateLimiter(self._quote_rate_seconds())
        self.candle_limiter = AccountRateLimiter(self._candle_rate_seconds())

    def _quote_rate_seconds(self) -> float:
        raise NotImplementedError

    def _candle_rate_seconds(self) -> float:
        raise NotImplementedError

    def is_configured(self) -> bool:
        raise NotImplementedError

    def fetch_quotes_batch(self, symbols: list[str]) -> list[QuoteResult]:
        raise NotImplementedError

    def fetch_candles(self, symbol: str, interval: str, period_days: int) -> "pd.DataFrame | None":
        raise NotImplementedError


class AngelOneAccount(BrokerAccount):
    BASE_URL = "https://apiconnect.angelbroking.com"
    INSTRUMENT_MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
    _CANDLE_INTERVAL_MAP = {
        "1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE",
        "1h": "ONE_HOUR", "1d": "ONE_DAY",
    }

    def __init__(self, account_id: str, client_code: str, password: str,
                 totp_secret: str, api_key: str):
        self.account_id = account_id
        self.broker = "angelone"
        self._client_code = client_code
        self._password = password
        self._totp_secret = totp_secret
        self._api_key = api_key
        self._jwt_token: str | None = None
        self._logged_in_at = 0.0
        self._session_lock = threading.Lock()
        self._instrument_cache_path = PROJECT_ROOT / "data" / f"angelone_instrument_master_{account_id}.csv"
        super().__init__()

    def _quote_rate_seconds(self) -> float:
        return ANGELONE_QUOTE_RATE_SECONDS

    def _candle_rate_seconds(self) -> float:
        return ANGELONE_CANDLE_RATE_SECONDS

    def is_configured(self) -> bool:
        return all([self._client_code, self._password, self._totp_secret, self._api_key])

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "106.193.147.98",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self._api_key,
            "X-UserType": "USER",
            "X-SourceID": "WEB",
        }
        if self._jwt_token:
            headers["Authorization"] = f"Bearer {self._jwt_token}"
        return headers

    def _login(self) -> bool:
        try:
            totp_code = pyotp.TOTP(self._totp_secret).now()
            resp = requests.post(
                f"{self.BASE_URL}/rest/auth/angelbroking/user/v1/loginByPassword",
                headers=self._headers(),
                json={"clientcode": self._client_code, "password": self._password, "totp": totp_code},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("status"):
                logger.warning(f"[{self.account_id}] Angel One login failed: {payload.get('message')}")
                return False
            self._jwt_token = payload["data"]["jwtToken"]
            self._logged_in_at = time.time()
            return True
        except requests.exceptions.HTTPError as e:
            logger.warning(f"[{self.account_id}] Angel One login request failed: {_http_error_detail(e)}")
            return False
        except Exception as e:
            logger.warning(f"[{self.account_id}] Angel One login request failed: {e}")
            return False

    def _ensure_session(self) -> bool:
        if self._jwt_token is not None and time.time() - self._logged_in_at <= ANGELONE_SESSION_TTL_SECONDS:
            return True
        with self._session_lock:
            if self._jwt_token is not None and time.time() - self._logged_in_at <= ANGELONE_SESSION_TTL_SECONDS:
                return True
            return self._login()

    def _load_symbol_to_token(self, force_refresh: bool = False) -> dict:
        if not force_refresh and self._instrument_cache_path.exists():
            age_days = (time.time() - self._instrument_cache_path.stat().st_mtime) / 86400
            if age_days < 7:
                df = pd.read_csv(self._instrument_cache_path)
                return dict(zip(df["name"], df["token"]))

        resp = requests.get(self.INSTRUMENT_MASTER_URL, timeout=60)
        resp.raise_for_status()
        full = pd.DataFrame(resp.json())
        eq = full[
            (full["exch_seg"] == "NSE")
            & (full["instrumenttype"] == "")
            & full["symbol"].astype(str).str.endswith("-EQ", na=False)
        ]
        eq = eq[["name", "token"]].dropna().drop_duplicates(subset="name")
        self._instrument_cache_path.parent.mkdir(parents=True, exist_ok=True)
        eq.to_csv(self._instrument_cache_path, index=False)
        return dict(zip(eq["name"], eq["token"]))

    def fetch_quotes_batch(self, symbols: list[str]) -> list[QuoteResult]:
        if not self.is_configured() or not self._ensure_session():
            return []
        try:
            symbol_map = self._load_symbol_to_token()
        except Exception as e:
            logger.warning(f"[{self.account_id}] instrument master fetch failed: {e}")
            return []

        token_to_symbol = {str(tok): sym for sym, tok in symbol_map.items() if sym in symbols}
        tokens = list(token_to_symbol.keys())
        results: list[QuoteResult] = []

        for i in range(0, len(tokens), ANGELONE_QUOTE_BATCH_SIZE):
            batch = tokens[i:i + ANGELONE_QUOTE_BATCH_SIZE]

            def _do_request():
                return requests.post(
                    f"{self.BASE_URL}/rest/secure/angelbroking/market/v1/quote",
                    headers=self._headers(),
                    json={"mode": "FULL", "exchangeTokens": {"NSE": batch}}, timeout=15,
                )

            try:
                resp = self.quote_limiter.call(_do_request)
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get("status"):
                    logger.warning(f"[{self.account_id}] quote batch failed: {payload.get('message')}")
                    continue
                for item in payload["data"]["fetched"]:
                    symbol = token_to_symbol.get(str(item.get("symbolToken", "")))
                    if symbol is None:
                        continue
                    ltp = item.get("ltp")
                    close = item.get("close")
                    if ltp is None or not close:
                        continue
                    pct_change = (ltp - close) / close * 100
                    results.append(QuoteResult(symbol=symbol, last_price=float(ltp), pct_change=float(pct_change)))
            except requests.exceptions.HTTPError as e:
                logger.warning(f"[{self.account_id}] quote batch request failed: {_http_error_detail(e)}")
                continue
            except Exception as e:
                logger.warning(f"[{self.account_id}] quote batch request failed: {e}")
                continue

        return results

    def fetch_candles(self, symbol: str, interval: str, period_days: int) -> "pd.DataFrame | None":
        if not self.is_configured() or not self._ensure_session():
            return None
        angel_interval = self._CANDLE_INTERVAL_MAP.get(interval)
        if angel_interval is None:
            return None
        try:
            symbol_map = self._load_symbol_to_token()
        except Exception as e:
            logger.warning(f"[{self.account_id}] instrument master fetch failed: {e}")
            return None
        token = symbol_map.get(symbol)
        if token is None:
            return None

        now = pd.Timestamp.now(tz=IST)
        from_dt = now - pd.Timedelta(days=period_days)

        def _do_request():
            return requests.post(
                f"{self.BASE_URL}/rest/secure/angelbroking/historical/v1/getCandleData",
                headers=self._headers(),
                json={
                    "exchange": "NSE", "symboltoken": str(token), "interval": angel_interval,
                    "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
                    "todate": now.strftime("%Y-%m-%d %H:%M"),
                },
                timeout=15,
            )

        try:
            resp = self.candle_limiter.call(_do_request)
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("status"):
                logger.warning(f"[{self.account_id}] candle fetch for {symbol} returned status:false "
                                f"| message: {payload.get('message')} | errorcode: {payload.get('errorcode')}")
                return None
            rows = payload.get("data") or []
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["Datetime", "Open", "High", "Low", "Close", "Volume"])
            df["Datetime"] = pd.to_datetime(df["Datetime"])
            df = df.set_index("Datetime")
            df.index = df.index.tz_convert(IST) if df.index.tz is not None else df.index.tz_localize(IST)
            return df
        except requests.exceptions.HTTPError as e:
            logger.warning(f"[{self.account_id}] candle fetch failed for {symbol}: {_http_error_detail(e)}")
            return None
        except Exception as e:
            logger.warning(f"[{self.account_id}] candle fetch failed for {symbol}: {e}")
            return None


class GrowwAccount(BrokerAccount):
    def __init__(self, account_id: str, api_key: str, api_secret: str | None = None,
                 totp_secret: str | None = None):
        self.account_id = account_id
        self.broker = "groww"
        self._api_key = api_key
        self._api_secret = api_secret
        self._totp_secret = totp_secret
        self._client = None
        self._client_expires_at = 0.0
        self._client_lock = threading.Lock()
        self._instrument_cache_path = PROJECT_ROOT / "data" / f"groww_instrument_master_{account_id}.csv"
        self._token_cache_path = PROJECT_ROOT / "data" / f"groww_token_cache_{account_id}.json"
        super().__init__()

    def _quote_rate_seconds(self) -> float:
        return GROWW_QUOTE_RATE_SECONDS

    def _candle_rate_seconds(self) -> float:
        return GROWW_CANDLE_RATE_SECONDS

    def is_configured(self) -> bool:
        return bool(self._api_key and (self._totp_secret or self._api_secret))

    def _get_client(self):
        if self._client is not None and time.time() < self._client_expires_at - GROWW_TOKEN_REFRESH_BUFFER_SECONDS:
            return self._client
        if not self.is_configured():
            return None

        with self._client_lock:
            if self._client is not None and time.time() < self._client_expires_at - GROWW_TOKEN_REFRESH_BUFFER_SECONDS:
                return self._client

            try:
                from growwapi import GrowwAPI
            except Exception as e:
                logger.warning(f"[{self.account_id}] Groww client init failed: {e}")
                return None

            cached = self._load_cached_token()
            if cached is not None:
                token, exp = cached
                if time.time() < exp - GROWW_TOKEN_REFRESH_BUFFER_SECONDS:
                    try:
                        self._client = GrowwAPI(token)
                        self._client_expires_at = exp
                        return self._client
                    except Exception as e:
                        logger.warning(f"[{self.account_id}] Groww client init from cached token failed: {e}")

            try:
                if self._totp_secret:
                    import pyotp
                    totp_code = pyotp.TOTP(self._totp_secret).now()
                    token = GrowwAPI.get_access_token(self._api_key, totp=totp_code)
                else:
                    token = GrowwAPI.get_access_token(self._api_key, secret=self._api_secret)
                self._client = GrowwAPI(token)
                exp = _jwt_exp_timestamp(token)
                self._client_expires_at = exp if exp is not None else time.time() + 3600
                self._save_cached_token(token, self._client_expires_at)
            except Exception as e:
                logger.warning(f"[{self.account_id}] Groww client init failed: {e}")
                return None
            return self._client

    def _load_cached_token(self) -> "tuple[str, float] | None":
        try:
            if not self._token_cache_path.exists():
                return None
            data = json.loads(self._token_cache_path.read_text())
            return data["token"], float(data["expires_at"])
        except Exception:
            return None

    def _save_cached_token(self, token: str, expires_at: float) -> None:
        try:
            self._token_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_cache_path.write_text(json.dumps({"token": token, "expires_at": expires_at}))
        except Exception as e:
            logger.warning(f"[{self.account_id}] could not persist Groww token cache: {e}")

    def get_client(self):
        return self._get_client()

    def _load_symbol_to_token(self, force_refresh: bool = False) -> dict:
        if not force_refresh and self._instrument_cache_path.exists():
            age_days = (time.time() - self._instrument_cache_path.stat().st_mtime) / 86400
            if age_days < 7:
                df = pd.read_csv(self._instrument_cache_path)
                return dict(zip(df["trading_symbol"], df["exchange_token"].astype(str)))

        client = self._get_client()
        if client is None:
            return {}
        full = client.get_all_instruments()
        eq = full[(full["exchange"] == "NSE") & (full["segment"] == "CASH")]
        eq = eq[["trading_symbol", "exchange_token"]].dropna().drop_duplicates(subset="trading_symbol")
        self._instrument_cache_path.parent.mkdir(parents=True, exist_ok=True)
        eq.to_csv(self._instrument_cache_path, index=False)
        return dict(zip(eq["trading_symbol"], eq["exchange_token"].astype(str)))

    def fetch_quotes_batch(self, symbols: list[str]) -> list[QuoteResult]:
        client = self._get_client()
        if client is None:
            return []
        results: list[QuoteResult] = []
        for i in range(0, len(symbols), GROWW_QUOTE_BATCH_SIZE):
            batch = symbols[i:i + GROWW_QUOTE_BATCH_SIZE]

            def _do_request():
                return client.get_ohlc(
                    segment="CASH",
                    exchange_trading_symbols=tuple(f"NSE_{s}" for s in batch),
                )

            try:
                payload = self.quote_limiter.call(_do_request)
                for key, ohlc in (payload or {}).items():
                    symbol = key.replace("NSE_", "", 1)
                    open_price = ohlc.get("open")
                    close_price = ohlc.get("close")
                    if not open_price or close_price is None:
                        continue
                    pct_change = (close_price - open_price) / open_price * 100
                    results.append(QuoteResult(symbol=symbol, last_price=float(close_price),
                                                pct_change=float(pct_change)))
            except Exception as e:
                logger.warning(f"[{self.account_id}] Groww OHLC batch failed: {e}")
                continue
        return results

    def fetch_candles(self, symbol: str, interval: str, period_days: int) -> "pd.DataFrame | None":
        client = self._get_client()
        if client is None:
            return None
        now = pd.Timestamp.now(tz=IST)
        from_dt = now - pd.Timedelta(days=period_days)
        groww_interval = {"1m": "1minute", "5m": "5minute", "15m": "15minute",
                           "1h": "1hour", "1d": "1day"}.get(interval)
        if groww_interval is None:
            return None

        def _do_request():
            return client.get_historical_candles(
                exchange="NSE", segment="CASH", groww_symbol=f"NSE-{symbol}",
                start_time=from_dt.strftime("%Y-%m-%d %H:%M:%S"),
                end_time=now.strftime("%Y-%m-%d %H:%M:%S"),
                candle_interval=groww_interval,
            )

        try:
            payload = self.candle_limiter.call(_do_request)
            candles = (payload or {}).get("candles")
            if not candles:
                return None
            df = pd.DataFrame(candles, columns=["Datetime", "Open", "High", "Low", "Close", "Volume", "_unused"])
            df = df.drop(columns=["_unused"])
            df["Datetime"] = pd.to_datetime(df["Datetime"])
            df = df.set_index("Datetime")
            df.index = df.index.tz_localize(IST) if df.index.tz is None else df.index.tz_convert(IST)
            return df
        except Exception as e:
            logger.warning(f"[{self.account_id}] Groww candle fetch failed for {symbol}: {e}")
            return None


def _env(prefix: str, suffix: str) -> str | None:
    return os.environ.get(f"{prefix}_{suffix}")


def get_configured_accounts() -> dict[str, list[BrokerAccount]]:
    angelone_accounts = []
    for n in (1, 2):
        prefix = f"ANGELONE_{n}"
        acct = AngelOneAccount(
            account_id=f"angelone_{n}",
            client_code=_env(prefix, "CLIENT_CODE"),
            password=_env(prefix, "PASSWORD"),
            totp_secret=_env(prefix, "TOTP_SECRET"),
            api_key=_env(prefix, "API_KEY"),
        )
        if acct.is_configured():
            angelone_accounts.append(acct)

    groww_accounts = []
    for n in (1, 2, 3):
        prefix = f"GROWW_{n}"
        acct = GrowwAccount(
            account_id=f"groww_{n}",
            api_key=_env(prefix, "API_KEY"),
            api_secret=_env(prefix, "API_SECRET"),
            totp_secret=_env(prefix, "TOTP_SECRET"),
        )
        if acct.is_configured():
            groww_accounts.append(acct)

    return {"angelone": angelone_accounts, "groww": groww_accounts}
