"""Read-only intraday market-data boundary for AXIS GEX Explorer."""

from __future__ import annotations

import asyncio
import math
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp

from app.integrations.massive_market_data import verified_ssl_context
from app.market_intelligence.gex_explorer.models import GexIntradayBar

ET = ZoneInfo("America/New_York")


class GexIntradayDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class GexIntradayResult:
    ticker: str
    provider: str
    session_date: date
    source_timestamp: datetime
    bars: tuple[GexIntradayBar, ...]


class GexIntradayDataProvider(Protocol):
    name: str

    async def fetch(self, ticker: str, *, bar_count: int) -> GexIntradayResult: ...


class MassiveGexIntradayProvider:
    """Latest regular-session 1-minute candles from the Massive aggregate API."""

    name = "massive"
    _INDEX_TICKERS = {
        "SPX": "I:SPX",
        "NDX": "I:NDX",
        "DJI": "I:DJI",
    }

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.massive.com",
        timeout_seconds: int = 15,
        lookback_calendar_days: int = 10,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if not api_key:
            raise GexIntradayDataError("MASSIVE_API_KEY_MISSING")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.lookback_calendar_days = max(3, lookback_calendar_days)
        self.session = session

    async def fetch(self, ticker: str, *, bar_count: int) -> GexIntradayResult:
        if bar_count <= 0 or bar_count > 1000:
            raise GexIntradayDataError("GEX_INTRADAY_POLICY_INVALID")
        symbol = ticker.strip().upper().removeprefix("US.").removeprefix("$")
        if not symbol:
            raise GexIntradayDataError("GEX_INTRADAY_TICKER_INVALID")
        massive_symbol = self._INDEX_TICKERS.get(symbol, symbol)
        today = datetime.now(ET).date()
        start = today - timedelta(days=self.lookback_calendar_days)
        encoded = quote(massive_symbol, safe="")
        url = (
            f"{self.base_url}/v2/aggs/ticker/{encoded}/range/1/minute/"
            f"{start.isoformat()}/{today.isoformat()}"
        )
        own_session = self.session is None
        session = self.session or aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
            connector=aiohttp.TCPConnector(ssl=verified_ssl_context()),
        )
        try:
            try:
                async with session.get(
                    url,
                    params={"adjusted": "true", "sort": "asc", "limit": "50000"},
                ) as response:
                    if response.status in {401, 403}:
                        raise GexIntradayDataError("MASSIVE_AUTH_FAILED")
                    if response.status == 429:
                        raise GexIntradayDataError("MASSIVE_RATE_LIMITED")
                    if response.status == 404:
                        raise GexIntradayDataError("GEX_INTRADAY_EMPTY")
                    if response.status != 200:
                        raise GexIntradayDataError("GEX_INTRADAY_UNAVAILABLE")
                    payload = await response.json(content_type=None)
            except GexIntradayDataError:
                raise
            except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
                raise GexIntradayDataError("GEX_INTRADAY_UNAVAILABLE") from exc
        finally:
            if own_session:
                await session.close()
        bars = self._normalize(payload)
        if not bars:
            raise GexIntradayDataError("GEX_INTRADAY_EMPTY")
        session_date = max(item.timestamp_et.date() for item in bars)
        selected = tuple(item for item in bars if item.timestamp_et.date() == session_date)[
            -bar_count:
        ]
        if not selected:
            raise GexIntradayDataError("GEX_INTRADAY_EMPTY")
        return GexIntradayResult(
            ticker=symbol,
            provider=self.name,
            session_date=session_date,
            source_timestamp=selected[-1].timestamp_et,
            bars=selected,
        )

    @staticmethod
    def _normalize(payload: Any) -> tuple[GexIntradayBar, ...]:
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise GexIntradayDataError("GEX_INTRADAY_RESPONSE_INVALID")
        rows: list[GexIntradayBar] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                timestamp = datetime.fromtimestamp(int(item["t"]) / 1000, tz=UTC).astimezone(ET)
                if not time(9, 30) <= timestamp.time() <= time(16, 0):
                    continue
                volume = float(item.get("v") or 0)
                rows.append(
                    GexIntradayBar(
                        timestamp_et=timestamp,
                        open=float(item["o"]),
                        high=float(item["h"]),
                        low=float(item["l"]),
                        close=float(item["c"]),
                        volume=volume if math.isfinite(volume) and volume >= 0 else 0,
                    )
                )
            except (KeyError, OSError, OverflowError, TypeError, ValueError):
                continue
        by_timestamp = {item.timestamp_et: item for item in rows}
        return tuple(by_timestamp[value] for value in sorted(by_timestamp))


class MoomooGexIntradayProvider:
    """Latest regular-session 1-minute candles through the local OpenD connection."""

    name = "moomoo"
    _INDEX_CODES = {
        "SPX": "US..SPX",
        "NDX": "US..NDX",
        "DJI": "US..DJI",
    }

    def __init__(self, *, host: str, port: int) -> None:
        self.host = host
        self.port = port

    async def fetch(self, ticker: str, *, bar_count: int) -> GexIntradayResult:
        if bar_count <= 0 or bar_count > 1000:
            raise GexIntradayDataError("GEX_INTRADAY_POLICY_INVALID")
        return await asyncio.to_thread(self._fetch_sync, ticker, bar_count)

    def _fetch_sync(self, ticker: str, bar_count: int) -> GexIntradayResult:
        try:
            from moomoo import RET_OK, AuType, KLType, OpenQuoteContext, SubType, SysConfig
        except Exception as exc:
            raise GexIntradayDataError("GEX_MOOMOO_SDK_UNAVAILABLE") from exc

        symbol = ticker.strip().upper().removeprefix("US.")
        if not symbol:
            raise GexIntradayDataError("GEX_INTRADAY_TICKER_INVALID")
        code = self._INDEX_CODES.get(symbol, f"US.{symbol}")
        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            ret, message = context.subscribe([code], [SubType.K_1M])
            if ret != RET_OK:
                raise GexIntradayDataError("GEX_INTRADAY_SUBSCRIPTION_FAILED")
            ret, frame = context.get_cur_kline(
                code,
                1000,
                KLType.K_1M,
                AuType.QFQ,
            )
            if ret != RET_OK or not hasattr(frame, "iterrows"):
                raise GexIntradayDataError("GEX_INTRADAY_UNAVAILABLE")
            bars = self._normalize(frame)
            if not bars:
                raise GexIntradayDataError("GEX_INTRADAY_EMPTY")
            session_date = max(item.timestamp_et.date() for item in bars)
            session = tuple(item for item in bars if item.timestamp_et.date() == session_date)[
                -bar_count:
            ]
            if not session:
                raise GexIntradayDataError("GEX_INTRADAY_EMPTY")
            return GexIntradayResult(
                ticker=symbol,
                provider=self.name,
                session_date=session_date,
                source_timestamp=session[-1].timestamp_et,
                bars=session,
            )
        except GexIntradayDataError:
            raise
        except Exception as exc:
            raise GexIntradayDataError("GEX_INTRADAY_UNAVAILABLE") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    @staticmethod
    def _normalize(frame: Any) -> tuple[GexIntradayBar, ...]:
        rows: list[GexIntradayBar] = []
        for _, item in frame.iterrows():
            try:
                timestamp = datetime.strptime(
                    str(item["time_key"])[:19], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=ET)
                if not time(9, 30) <= timestamp.time() <= time(16, 0):
                    continue
                volume = float(item.get("volume") or 0)
                rows.append(
                    GexIntradayBar(
                        timestamp_et=timestamp,
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=volume if math.isfinite(volume) and volume >= 0 else 0,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        by_timestamp = {item.timestamp_et: item for item in rows}
        return tuple(by_timestamp[value] for value in sorted(by_timestamp))
