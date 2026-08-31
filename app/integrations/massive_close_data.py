from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp

from app.integrations.massive_market_data import massive_option_ticker, verified_ssl_context
from app.integrations.moomoo_market_data import (
    MarketDataError,
    OptionQuote,
    OptionQuoteRequest,
    PostCloseQuoteBatch,
)

ET = ZoneInfo("America/New_York")


class MassiveClosingPriceClient:
    """Read-only official daily option closes from Massive aggregate bars."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.massive.com",
        timeout_seconds: int = 15,
        concurrency: int = 8,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if not api_key:
            raise MarketDataError("MASSIVE_API_KEY_MISSING")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.session = session

    async def fetch_post_close(
        self,
        requests: tuple[OptionQuoteRequest, ...],
        *,
        session_date: date,
    ) -> PostCloseQuoteBatch:
        if not requests:
            return PostCloseQuoteBatch(
                session_date=session_date,
                market_state="CLOSED",
                is_trading_session=True,
                quotes=(),
                provider="MASSIVE",
            )
        own_session = self.session is None
        session = self.session or aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
            connector=aiohttp.TCPConnector(ssl=verified_ssl_context()),
        )
        try:
            results = await asyncio.gather(
                *(self._fetch_one(session, request, session_date) for request in requests),
                return_exceptions=True,
            )
        finally:
            if own_session:
                await session.close()
        for result in results:
            if isinstance(result, MarketDataError) and result.code in {
                "MASSIVE_AUTH_FAILED",
                "MASSIVE_RATE_LIMITED",
            }:
                raise result
        quotes = tuple(
            result
            if isinstance(result, OptionQuote)
            else OptionQuote(
                key=request.key,
                instrument_code=massive_option_ticker(
                    request.ticker,
                    request.expiry,
                    request.strike,
                    request.option_side,
                ),
                last_price=None,
                quote_time=None,
                error_code=(result.code if isinstance(result, MarketDataError) else "CLOSE_FAILED"),
                price_type="CLOSE",
            )
            for request, result in zip(requests, results, strict=True)
        )
        return PostCloseQuoteBatch(
            session_date=session_date,
            market_state="CLOSED",
            is_trading_session=True,
            quotes=quotes,
            provider="MASSIVE",
        )

    async def _fetch_one(
        self,
        session: aiohttp.ClientSession,
        request: OptionQuoteRequest,
        session_date: date,
    ) -> OptionQuote:
        option_ticker = massive_option_ticker(
            request.ticker,
            request.expiry,
            request.strike,
            request.option_side,
        )
        encoded = quote(option_ticker, safe=":")
        day = session_date.isoformat()
        url = f"{self.base_url}/v2/aggs/ticker/{encoded}/range/1/day/{day}/{day}"
        try:
            async with self.semaphore, session.get(
                url,
                params={"adjusted": "true", "sort": "asc", "limit": "10"},
            ) as response:
                if response.status in {401, 403}:
                    raise MarketDataError("MASSIVE_AUTH_FAILED")
                if response.status == 429:
                    raise MarketDataError("MASSIVE_RATE_LIMITED")
                if response.status == 404:
                    return self._unavailable(request.key, option_ticker, "CLOSE_UNAVAILABLE")
                if response.status != 200:
                    raise MarketDataError("MASSIVE_CLOSE_REQUEST_FAILED")
                payload = await response.json(content_type=None)
        except MarketDataError:
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            raise MarketDataError("MASSIVE_CLOSE_REQUEST_FAILED") from exc
        return self._normalize(request.key, option_ticker, session_date, payload)

    @classmethod
    def _normalize(
        cls,
        key: str,
        option_ticker: str,
        session_date: date,
        payload: Any,
    ) -> OptionQuote:
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise MarketDataError("MASSIVE_CLOSE_RESPONSE_INVALID")
        matching: list[tuple[datetime, Decimal]] = []
        for bar in payload["results"]:
            if not isinstance(bar, dict):
                continue
            try:
                closing_price = Decimal(str(bar["c"]))
                timestamp = datetime.fromtimestamp(int(bar["t"]) / 1000, tz=UTC)
            except (InvalidOperation, KeyError, OSError, OverflowError, TypeError, ValueError):
                continue
            if closing_price > 0 and timestamp.astimezone(ET).date() == session_date:
                matching.append((timestamp, closing_price))
        if not matching:
            return cls._unavailable(key, option_ticker, "CLOSE_UNAVAILABLE")
        timestamp, closing_price = max(matching, key=lambda item: item[0])
        return OptionQuote(
            key=key,
            instrument_code=option_ticker,
            last_price=closing_price,
            quote_time=timestamp,
            price_type="CLOSE",
        )

    @staticmethod
    def _unavailable(key: str, option_ticker: str, error_code: str) -> OptionQuote:
        return OptionQuote(
            key=key,
            instrument_code=option_ticker,
            last_price=None,
            quote_time=None,
            error_code=error_code,
            price_type="CLOSE",
        )
