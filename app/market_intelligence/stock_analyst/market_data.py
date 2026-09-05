"""Provider-independent, read-only market-data adapters for AXIS Stock Analyst."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from datetime import time as wall_time
from typing import Any, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp

from app.integrations.massive_market_data import verified_ssl_context
from app.market_intelligence.stock_analyst.engine import (
    infer_sector_etf,
    sector_leader_candidates,
)
from app.market_intelligence.stock_analyst.models import DailyBar, StockMarketBundle
from app.market_intelligence.stock_analyst.sector_rotation import rotation_peers

ET = ZoneInfo("America/New_York")
_HISTORY_REQUEST_LOCK = threading.Lock()
_LAST_HISTORY_REQUEST_AT = 0.0
_MINIMUM_HISTORY_INTERVAL_SECONDS = 1.1
MINIMUM_ANALYSIS_SESSIONS = 120


class StockMarketDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class StockMarketDataProvider(Protocol):
    name: str

    async def fetch(self, ticker: str) -> StockMarketBundle: ...


def normalize_us_symbol(ticker: str) -> str:
    value = ticker.strip().upper().removeprefix("$")
    if not value or len(value) > 12 or any(not (char.isalnum() or char in ".-") for char in value):
        raise StockMarketDataError("AXIS_STOCK_SYMBOL_INVALID")
    return value.removeprefix("US.")


class MoomooDailyBarProvider:
    """Read-only daily bars through the AXIS-owned local OpenD connection."""

    name = "moomoo"

    def __init__(self, host: str, port: int, lookback_days: int = 620) -> None:
        self.host = host
        self.port = port
        self.lookback_days = lookback_days

    async def fetch(self, ticker: str) -> StockMarketBundle:
        return await asyncio.to_thread(self._fetch_sync, normalize_us_symbol(ticker))

    def _fetch_sync(self, ticker: str) -> StockMarketBundle:
        try:
            from moomoo import KL_FIELD, RET_OK, AuType, KLType, OpenQuoteContext, SysConfig
        except Exception as exc:
            raise StockMarketDataError("MOOMOO_SDK_UNAVAILABLE") from exc
        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            end = datetime.now(ET).date()
            start = end - timedelta(days=self.lookback_days)
            sector = infer_sector_etf(ticker)
            bars = self._history(
                context,
                f"US.{ticker}",
                start.isoformat(),
                end.isoformat(),
                RET_OK,
                KLType,
                AuType,
                KL_FIELD,
            )
            if len(bars) < MINIMUM_ANALYSIS_SESSIONS:
                raise StockMarketDataError("AXIS_STOCK_HISTORY_INSUFFICIENT")
            sector_bars = None
            benchmark_bars = None
            with suppress(StockMarketDataError):
                sector_bars = self._history(
                    context,
                    f"US.{sector}",
                    start.isoformat(),
                    end.isoformat(),
                    RET_OK,
                    KLType,
                    AuType,
                    KL_FIELD,
                )
            if sector == "SPY":
                benchmark_bars = sector_bars
            else:
                with suppress(StockMarketDataError):
                    benchmark_bars = self._history(
                        context,
                        "US.SPY",
                        start.isoformat(),
                        end.isoformat(),
                        RET_OK,
                        KLType,
                        AuType,
                        KL_FIELD,
                    )
            source_timestamp = bars[-1].timestamp
            return StockMarketBundle(
                ticker,
                bars,
                sector,
                sector_bars,
                benchmark_bars,
                provider=self.name,
                fetched_at=datetime.now(UTC),
                source_timestamp=source_timestamp,
                market_status=_derived_market_status(),
            )
        except StockMarketDataError:
            raise
        except Exception as exc:
            raise StockMarketDataError("MOOMOO_STOCK_HISTORY_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    @staticmethod
    def _history(
        context: Any,
        code: str,
        start: str,
        end: str,
        ret_ok: int,
        kl_type: Any,
        au_type: Any,
        kl_field: Any,
    ) -> tuple[DailyBar, ...]:
        global _LAST_HISTORY_REQUEST_AT
        with _HISTORY_REQUEST_LOCK:
            elapsed = time.monotonic() - _LAST_HISTORY_REQUEST_AT
            if elapsed < _MINIMUM_HISTORY_INTERVAL_SECONDS:
                time.sleep(_MINIMUM_HISTORY_INTERVAL_SECONDS - elapsed)
            _LAST_HISTORY_REQUEST_AT = time.monotonic()
        ret, frame, _ = context.request_history_kline(
            code,
            start=start,
            end=end,
            ktype=kl_type.K_DAY,
            autype=au_type.QFQ,
            fields=[kl_field.ALL],
            max_count=1000,
        )
        if ret != ret_ok or not hasattr(frame, "iterrows"):
            raise StockMarketDataError("MOOMOO_STOCK_HISTORY_UNAVAILABLE")
        rows = []
        for _, item in frame.iterrows():
            try:
                timestamp = datetime.strptime(str(item["time_key"])[:10], "%Y-%m-%d").replace(
                    hour=16, tzinfo=ET
                )
                rows.append(
                    DailyBar(
                        timestamp=timestamp,
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=float(item.get("volume") or 0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        by_date = {bar.timestamp.date(): bar for bar in rows}
        return tuple(by_date[value] for value in sorted(by_date))


def _derived_market_status(now: datetime | None = None) -> str:
    current = (now or datetime.now(ET)).astimezone(ET)
    if current.weekday() >= 5:
        return "closed"
    if current.time() < wall_time(9, 30):
        return "pre-market"
    if current.time() <= wall_time(16, 0):
        return "open"
    return "after-hours"


class MassiveDailyBarProvider:
    """Massive adjusted daily OHLCV behind the shared Stock Analyst boundary.

    The mandatory ticker request is strict. Sector, benchmark, peer, leader, and
    snapshot context are best effort, matching the recovered Cosmos service.
    """

    name = "massive"
    _INDEX_SYMBOLS = {"SPX": "I:SPX", "NDX": "I:NDX", "DJI": "I:DJI"}

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.massive.com",
        timeout_seconds: int = 15,
        lookback_days: int = 550,
        concurrency: int = 4,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if not api_key:
            raise StockMarketDataError("MASSIVE_API_KEY_MISSING")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.lookback_days = max(180, lookback_days)
        self.semaphore = asyncio.Semaphore(max(1, concurrency))
        self.session = session
        self._bar_cache: dict[str, tuple[float, tuple[DailyBar, ...]]] = {}
        self._bar_cache_lock = asyncio.Lock()

    async def fetch(self, ticker: str) -> StockMarketBundle:
        symbol = normalize_us_symbol(ticker)
        provider_symbol = self._INDEX_SYMBOLS.get(symbol, symbol)
        now = datetime.now(UTC)
        own_session = self.session is None
        session = self.session or aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
            connector=aiohttp.TCPConnector(ssl=verified_ssl_context()),
        )
        unavailable: list[str] = []
        try:
            bars = await self._bars(session, provider_symbol, mandatory=True)
            if len(bars) < MINIMUM_ANALYSIS_SESSIONS:
                raise StockMarketDataError("AXIS_STOCK_HISTORY_INSUFFICIENT")
            sector = infer_sector_etf(symbol)
            context_symbols = tuple(
                dict.fromkeys(
                    (
                        "SPY",
                        sector,
                        *rotation_peers(sector),
                        *sector_leader_candidates(sector),
                    )
                )
            )
            optional_results = await asyncio.gather(
                *(self._bars(session, item, mandatory=False) for item in context_symbols),
                return_exceptions=True,
            )
            context: dict[str, tuple[DailyBar, ...]] = {}
            for item, result in zip(context_symbols, optional_results, strict=True):
                if isinstance(result, tuple) and len(result) >= 21:
                    context[item] = result
                else:
                    unavailable.append(f"context:{item}")
            snapshot = await self._snapshot_metadata(session, symbol)
            if snapshot is None:
                unavailable.append("latest_snapshot")
                source_timestamp = bars[-1].timestamp
                market_status = _derived_market_status()
            else:
                source_timestamp, market_status = snapshot
            peers = {item: context[item] for item in rotation_peers(sector) if item in context}
            candidates = {
                item: context[item] for item in sector_leader_candidates(sector) if item in context
            }
            return StockMarketBundle(
                ticker=symbol,
                bars=bars,
                sector_etf=sector,
                sector_bars=context.get(sector),
                benchmark_bars=context.get("SPY"),
                peer_bars=peers,
                sector_candidate_bars=candidates,
                provider=self.name,
                fetched_at=now,
                source_timestamp=source_timestamp,
                market_status=market_status,
                unavailable_data=tuple(unavailable),
            )
        finally:
            if own_session:
                await session.close()

    async def _bars(
        self,
        session: aiohttp.ClientSession,
        ticker: str,
        *,
        mandatory: bool,
    ) -> tuple[DailyBar, ...]:
        now_monotonic = time.monotonic()
        async with self._bar_cache_lock:
            cached = self._bar_cache.get(ticker)
            if cached is not None and now_monotonic - cached[0] <= 60:
                return cached[1]
        now = datetime.now(ET)
        start = now.date() - timedelta(days=self.lookback_days)
        encoded = quote(ticker, safe="")
        url = (
            f"{self.base_url}/v2/aggs/ticker/{encoded}/range/1/day/"
            f"{start.isoformat()}/{now.date().isoformat()}"
        )
        try:
            async with (
                self.semaphore,
                session.get(
                    url,
                    params={"adjusted": "true", "sort": "asc", "limit": "1500"},
                ) as response,
            ):
                if response.status in {401, 403}:
                    raise StockMarketDataError("MASSIVE_AUTH_FAILED")
                if response.status == 429:
                    raise StockMarketDataError("MASSIVE_RATE_LIMITED")
                if response.status == 404:
                    raise StockMarketDataError("AXIS_STOCK_SYMBOL_NOT_FOUND")
                if response.status != 200:
                    raise StockMarketDataError("STOCK_ANALYST_PROVIDER_FAILURE")
                payload = await response.json(content_type=None)
        except StockMarketDataError:
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            raise StockMarketDataError("STOCK_ANALYST_PROVIDER_FAILURE") from exc
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            count_value = (
                payload.get("queryCount") or payload.get("resultsCount")
                if isinstance(payload, dict)
                else None
            )
            try:
                result_count = int(count_value or 0)
            except (TypeError, ValueError):
                result_count = -1
            empty_success = (
                mandatory
                and isinstance(payload, dict)
                and str(payload.get("status") or "").upper() in {"OK", "DELAYED"}
                and result_count == 0
            )
            if empty_success:
                raise StockMarketDataError("AXIS_STOCK_SYMBOL_NOT_FOUND")
            raise StockMarketDataError("STOCK_ANALYST_DATA_QUALITY_FAILURE")
        rows: list[DailyBar] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                volume = float(item.get("v") or 0)
                bar = DailyBar(
                    timestamp=datetime.fromtimestamp(float(item["t"]) / 1000, tz=UTC),
                    open=float(item["o"]),
                    high=float(item["h"]),
                    low=float(item["l"]),
                    close=float(item["c"]),
                    volume=volume if math.isfinite(volume) and volume >= 0 else 0,
                )
            except (KeyError, OSError, OverflowError, TypeError, ValueError):
                continue
            rows.append(bar)
        by_date = {bar.timestamp.astimezone(ET).date(): bar for bar in rows}
        bars = tuple(by_date[value] for value in sorted(by_date))
        if not bars and mandatory:
            raise StockMarketDataError("AXIS_STOCK_SYMBOL_NOT_FOUND")
        if bars:
            async with self._bar_cache_lock:
                self._bar_cache[ticker] = (time.monotonic(), bars)
        return bars

    async def _snapshot_metadata(
        self,
        session: aiohttp.ClientSession,
        ticker: str,
    ) -> tuple[datetime, str] | None:
        if ticker in self._INDEX_SYMBOLS:
            url = f"{self.base_url}/v3/snapshot/indices"
            params = {"ticker": self._INDEX_SYMBOLS[ticker], "limit": "10"}
        else:
            url = f"{self.base_url}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
            params = None
        try:
            async with self.semaphore, session.get(url, params=params) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError):
            return None
        root: Any
        if ticker in self._INDEX_SYMBOLS:
            results = payload.get("results") if isinstance(payload, dict) else None
            root = results[0] if isinstance(results, list) and results else None
        else:
            root = payload.get("ticker") if isinstance(payload, dict) else None
        if not isinstance(root, dict):
            return None
        timestamp = _latest_timestamp(root) or datetime.now(UTC)
        status = str(
            root.get("market_status")
            or (payload.get("market_status") if isinstance(payload, dict) else "")
            or _derived_market_status()
        ).lower()
        return timestamp, status


def _latest_timestamp(payload: dict[str, Any]) -> datetime | None:
    candidates: list[float] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if "timestamp" in key.lower() or key.lower() in {"t", "last_updated"}:
                    with suppress(TypeError, ValueError):
                        candidates.append(float(nested))
                elif isinstance(nested, dict):
                    collect(nested)

    collect(payload)
    if not candidates:
        return None
    raw = max(candidates)
    if raw > 1e15:
        raw /= 1e9
    elif raw > 1e12:
        raw /= 1e3
    try:
        return datetime.fromtimestamp(raw, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None
