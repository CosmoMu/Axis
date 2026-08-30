from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote

import aiohttp


class MarketDataProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class MarketPriceRequest:
    key: str
    underlying: str
    option_ticker: str


@dataclass(frozen=True, slots=True)
class MarketPrice:
    key: str
    option_ticker: str
    price: Decimal
    price_source: str
    source_timestamp: datetime
    received_at: datetime
    market_status: str


class MarketDataProvider(Protocol):
    async def fetch_prices(
        self, requests: Sequence[MarketPriceRequest]
    ) -> tuple[MarketPrice, ...]: ...


def massive_option_ticker(
    ticker: str,
    expiry: date,
    strike: Decimal,
    option_side: str,
) -> str:
    try:
        strike_code = int((strike * Decimal("1000")).to_integral_exact())
    except (InvalidOperation, ValueError) as exc:
        raise MarketDataProviderError("OPTION_CONTRACT_INVALID") from exc
    side = {"CALL": "C", "PUT": "P"}.get(option_side)
    root = ticker.strip().upper()
    if not root or side is None or strike_code <= 0 or strike_code > 99_999_999:
        raise MarketDataProviderError("OPTION_CONTRACT_INVALID")
    return f"O:{root}{expiry:%y%m%d}{side}{strike_code:08d}"


class MassiveMarketDataProvider:
    """Massive option snapshots normalized behind the provider boundary."""

    def __init__(
        self,
        *,
        api_key: str,
        price_source: str,
        max_quote_age_seconds: int,
        last_trade_quote_guard_pct: Decimal,
        base_url: str = "https://api.massive.com",
        timeout_seconds: int = 10,
        concurrency: int = 8,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if not api_key:
            raise MarketDataProviderError("MASSIVE_API_KEY_MISSING")
        if price_source not in {"BID", "MID", "LAST"}:
            raise MarketDataProviderError("PRICE_SOURCE_INVALID")
        self.api_key = api_key
        self.price_source = price_source
        self.max_quote_age = timedelta(seconds=max_quote_age_seconds)
        self.last_trade_quote_guard_pct = last_trade_quote_guard_pct
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.session = session

    async def fetch_prices(self, requests: Sequence[MarketPriceRequest]) -> tuple[MarketPrice, ...]:
        if not requests:
            return ()
        own_session = self.session is None
        session = self.session or aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        try:
            results = await asyncio.gather(
                *(self._fetch_one(session, request) for request in requests),
                return_exceptions=True,
            )
        finally:
            if own_session:
                await session.close()
        prices = tuple(item for item in results if isinstance(item, MarketPrice))
        if not prices:
            first_error = next(
                (item for item in results if isinstance(item, MarketDataProviderError)),
                None,
            )
            if first_error is not None:
                raise first_error
            raise MarketDataProviderError("MASSIVE_BATCH_FAILED")
        return prices

    async def _fetch_one(
        self,
        session: aiohttp.ClientSession,
        request: MarketPriceRequest,
    ) -> MarketPrice:
        path = (
            f"/v3/snapshot/options/{quote(request.underlying, safe='')}/"
            f"{quote(request.option_ticker, safe=':')}"
        )
        try:
            async with self.semaphore, session.get(f"{self.base_url}{path}") as response:
                if response.status in {401, 403}:
                    raise MarketDataProviderError("MASSIVE_AUTH_FAILED")
                if response.status == 404:
                    raise MarketDataProviderError("OPTION_CONTRACT_NOT_FOUND")
                if response.status == 429:
                    raise MarketDataProviderError("MASSIVE_RATE_LIMITED")
                if response.status != 200:
                    raise MarketDataProviderError("MASSIVE_REQUEST_FAILED")
                payload = await response.json(content_type=None)
        except MarketDataProviderError:
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            raise MarketDataProviderError("MASSIVE_REQUEST_FAILED") from exc
        return self._normalize(request, payload)

    def _normalize(self, request: MarketPriceRequest, payload: Any) -> MarketPrice:
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), dict):
            raise MarketDataProviderError("MASSIVE_RESPONSE_INVALID")
        result = payload["results"]
        quote_payload = (
            result.get("last_quote") if isinstance(result.get("last_quote"), dict) else {}
        )
        trade_payload = (
            result.get("last_trade") if isinstance(result.get("last_trade"), dict) else {}
        )
        bid = _positive_decimal(quote_payload.get("bid"))
        ask = _positive_decimal(quote_payload.get("ask"))
        midpoint = _positive_decimal(quote_payload.get("midpoint"))
        last = _positive_decimal(trade_payload.get("price"))
        if self.price_source == "BID":
            price = bid
            timestamp = _nanosecond_time(quote_payload.get("last_updated"))
        elif self.price_source == "MID":
            price = midpoint or ((bid + ask) / 2 if bid is not None and ask is not None else None)
            timestamp = _nanosecond_time(quote_payload.get("last_updated"))
        else:
            price = last
            timestamp = _nanosecond_time(trade_payload.get("sip_timestamp"))
            if price is not None and bid is not None and ask is not None:
                guard = self.last_trade_quote_guard_pct / Decimal("100")
                if price < bid * (Decimal("1") - guard) or price > ask * (Decimal("1") + guard):
                    raise MarketDataProviderError("LAST_TRADE_OUTLIER")
        if price is None or timestamp is None:
            raise MarketDataProviderError("MASSIVE_PRICE_UNAVAILABLE")
        received_at = datetime.now(UTC)
        if received_at - timestamp > self.max_quote_age:
            raise MarketDataProviderError("MASSIVE_QUOTE_STALE")
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        resolved_ticker = str(details.get("ticker") or request.option_ticker)
        return MarketPrice(
            key=request.key,
            option_ticker=resolved_ticker,
            price=price,
            price_source=self.price_source,
            source_timestamp=timestamp,
            received_at=received_at,
            market_status=str(result.get("market_status") or "unknown"),
        )


def _positive_decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed > 0 and parsed.is_finite() else None


def _nanosecond_time(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1_000_000_000, tz=UTC)
    except (OSError, OverflowError, TypeError, ValueError):
        return None
