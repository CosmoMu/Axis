"""Option-chain provider boundary for the read-only AXIS GEX Explorer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import aiohttp

from app.integrations.massive_market_data import (
    MarketDataProviderError,
    massive_underlying_ticker,
    verified_ssl_context,
)
from app.market_intelligence.gex_explorer.models import GexOptionContract, OptionSide


class GexFetchPolicy(Protocol):
    expiration_count: int
    expiration_candidates: int
    expiration_horizon_days: int
    minimum_contracts_per_expiry: int
    strike_range_pct: float
    snapshot_page_limit: int
    snapshot_max_pages: int


@dataclass(frozen=True, slots=True)
class GexProviderResult:
    ticker: str
    provider: str
    spot: float
    contracts: tuple[GexOptionContract, ...]
    candidate_expirations: tuple[date, ...]
    used_expirations: tuple[date, ...]
    failed_expirations: tuple[tuple[date, str], ...]
    source_timestamp: datetime
    fetched_at: datetime
    market_status: str


@dataclass(frozen=True, slots=True)
class _ExpiryResult:
    expiration: date
    contracts: tuple[GexOptionContract, ...]
    source_timestamps: tuple[datetime, ...]


class GexMarketDataProvider(Protocol):
    name: str

    async def fetch(self, ticker: str, policy: GexFetchPolicy) -> GexProviderResult: ...


class MassiveGexMarketDataProvider:
    """Massive snapshots normalized into the provider-independent GEX contract model."""

    name = "massive"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.massive.com",
        timeout_seconds: int = 18,
        concurrency: int = 4,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if not api_key:
            raise MarketDataProviderError("MASSIVE_API_KEY_MISSING")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.session = session

    async def fetch(self, ticker: str, policy: GexFetchPolicy) -> GexProviderResult:
        symbol = massive_underlying_ticker(ticker)
        fetched_at = datetime.now(UTC)
        own_session = self.session is None
        session = self.session or aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
            connector=aiohttp.TCPConnector(ssl=verified_ssl_context()),
        )
        try:
            session_date = fetched_at.astimezone(ZoneInfo("America/New_York")).date()
            candidates = await self._expirations(session, symbol, session_date, policy)
            if not candidates:
                raise MarketDataProviderError("GEX_NO_EXPIRATIONS")
            try:
                spot, spot_timestamp, market_status = await self._spot(session, symbol)
            except MarketDataProviderError as exc:
                if symbol != "SPX" or exc.code != "MASSIVE_AUTH_FAILED":
                    raise
                spot, spot_timestamp, market_status = await self._spx_chain_spot(
                    session, candidates[0]
                )
            strike_min = max(0.01, spot * (1 - policy.strike_range_pct))
            strike_max = spot * (1 + policy.strike_range_pct)
            valid: list[_ExpiryResult] = []
            failed: list[tuple[date, str]] = []
            batch_size = max(1, min(4, policy.expiration_count))
            for offset in range(0, len(candidates), batch_size):
                batch = candidates[offset : offset + batch_size]
                results = await asyncio.gather(
                    *(
                        self._expiry_chain(
                            session,
                            symbol,
                            expiration,
                            strike_min,
                            strike_max,
                            policy,
                        )
                        for expiration in batch
                    ),
                    return_exceptions=True,
                )
                for expiration, result in zip(batch, results, strict=True):
                    if isinstance(result, _ExpiryResult):
                        valid.append(result)
                    elif isinstance(result, MarketDataProviderError):
                        failed.append((expiration, result.code))
                    else:
                        failed.append((expiration, "GEX_EXPIRY_FETCH_FAILED"))
                if len(valid) >= policy.expiration_count:
                    break
            selected = valid[: policy.expiration_count]
            contracts = tuple(contract for item in selected for contract in item.contracts)
            if not contracts:
                raise MarketDataProviderError("GEX_OPTION_CHAIN_EMPTY")
            timestamps = [spot_timestamp]
            timestamps.extend(
                timestamp for item in selected for timestamp in item.source_timestamps
            )
            return GexProviderResult(
                ticker=symbol,
                provider=self.name,
                spot=spot,
                contracts=contracts,
                candidate_expirations=candidates,
                used_expirations=tuple(item.expiration for item in selected),
                failed_expirations=tuple(failed),
                source_timestamp=max(timestamps),
                fetched_at=fetched_at,
                market_status=market_status,
            )
        finally:
            if own_session:
                await session.close()

    async def _request(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self.semaphore, session.get(url, params=params) as response:
                if response.status in {401, 403}:
                    raise MarketDataProviderError("MASSIVE_AUTH_FAILED")
                if response.status == 404:
                    raise MarketDataProviderError("GEX_TICKER_NOT_FOUND")
                if response.status == 429:
                    raise MarketDataProviderError("MASSIVE_RATE_LIMITED")
                if response.status != 200:
                    raise MarketDataProviderError("GEX_PROVIDER_UNAVAILABLE")
                payload = await response.json(content_type=None)
        except MarketDataProviderError:
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            raise MarketDataProviderError("GEX_PROVIDER_UNAVAILABLE") from exc
        if not isinstance(payload, dict):
            raise MarketDataProviderError("GEX_PROVIDER_RESPONSE_INVALID")
        return payload

    async def _spot(
        self, session: aiohttp.ClientSession, ticker: str
    ) -> tuple[float, datetime, str]:
        if ticker == "SPX":
            payload = await self._request(
                session,
                f"{self.base_url}/v3/snapshot/indices",
                {"ticker": "I:SPX", "limit": "10"},
            )
            rows = payload.get("results")
            root = rows[0] if isinstance(rows, list) and rows else None
        else:
            payload = await self._request(
                session,
                f"{self.base_url}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
            )
            root = payload.get("ticker") or payload.get("results")
        if not isinstance(root, dict):
            raise MarketDataProviderError("GEX_TICKER_NOT_FOUND")
        price = self._first_number(
            root.get("lastTrade"),
            root.get("last_trade"),
            root.get("value"),
            root.get("min"),
            root.get("minute"),
            root.get("day"),
        )
        if price is None or price <= 0:
            raise MarketDataProviderError("GEX_SPOT_UNAVAILABLE")
        source_timestamp = self._timestamp_from(root) or datetime.now(UTC)
        status = str(root.get("market_status") or payload.get("market_status") or "").lower()
        return price, source_timestamp, status or self._derived_market_status()

    async def _expirations(
        self,
        session: aiohttp.ClientSession,
        ticker: str,
        start: date,
        policy: GexFetchPolicy,
    ) -> tuple[date, ...]:
        end = start + timedelta(days=policy.expiration_horizon_days)
        cursor = start
        expirations: list[date] = []
        while cursor <= end and len(expirations) < policy.expiration_candidates:
            payload = await self._request(
                session,
                f"{self.base_url}/v3/reference/options/contracts",
                {
                    "underlying_ticker": ticker,
                    "expiration_date.gte": cursor.isoformat(),
                    "expiration_date.lte": end.isoformat(),
                    "expired": "false",
                    "order": "asc",
                    "sort": "expiration_date",
                    "limit": "250",
                },
            )
            page_dates = []
            for row in payload.get("results") or ():
                try:
                    expiration = date.fromisoformat(str(row["expiration_date"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if cursor <= expiration <= end:
                    page_dates.append(expiration)
            unique = sorted(set(page_dates))
            if not unique:
                break
            for expiration in unique:
                if expiration not in expirations:
                    expirations.append(expiration)
            cursor = unique[-1] + timedelta(days=1)
        return tuple(expirations[: policy.expiration_candidates])

    async def _spx_chain_spot(
        self,
        session: aiohttp.ClientSession,
        expiration: date,
    ) -> tuple[float, datetime, str]:
        try:
            payload = await self._request(
                session,
                f"{self.base_url}/v3/snapshot/options/SPX",
                {
                    "expiration_date": expiration.isoformat(),
                    "order": "asc",
                    "sort": "strike_price",
                    "limit": "1",
                },
            )
        except MarketDataProviderError as exc:
            raise MarketDataProviderError("GEX_SPX_UNSUPPORTED") from exc
        rows = payload.get("results")
        first = rows[0] if isinstance(rows, list) and rows else None
        underlying = first.get("underlying_asset") if isinstance(first, dict) else None
        price = self._first_number(underlying)
        if price is None or price <= 0:
            raise MarketDataProviderError("GEX_SPX_UNSUPPORTED")
        timestamp = self._timestamp_from(first) if isinstance(first, dict) else None
        market_status = (
            str(payload.get("market_status") or "").lower() or self._derived_market_status()
        )
        return price, timestamp or datetime.now(UTC), market_status

    async def _expiry_chain(
        self,
        session: aiohttp.ClientSession,
        ticker: str,
        expiration: date,
        strike_min: float,
        strike_max: float,
        policy: GexFetchPolicy,
    ) -> _ExpiryResult:
        url = f"{self.base_url}/v3/snapshot/options/{ticker}"
        params: dict[str, str] | None = {
            "expiration_date": expiration.isoformat(),
            "strike_price.gte": f"{strike_min:.6f}",
            "strike_price.lte": f"{strike_max:.6f}",
            "order": "asc",
            "sort": "strike_price",
            "limit": str(policy.snapshot_page_limit),
        }
        rows: list[Any] = []
        pages = 0
        while url and pages < policy.snapshot_max_pages:
            payload = await self._request(session, url, params)
            results = payload.get("results")
            if not isinstance(results, list):
                raise MarketDataProviderError("GEX_PROVIDER_RESPONSE_INVALID")
            rows.extend(results)
            next_url = payload.get("next_url")
            url = str(next_url) if isinstance(next_url, str) and next_url else ""
            params = None
            pages += 1
        if url:
            raise MarketDataProviderError("GEX_EXPIRY_PARTIAL")
        contracts = []
        timestamps = []
        sides: set[OptionSide] = set()
        for row in rows:
            normalized = self._normalize_contract(row, expiration)
            if normalized is None:
                continue
            contract, timestamp = normalized
            contracts.append(contract)
            sides.add(contract.side)
            if timestamp is not None:
                timestamps.append(timestamp)
        if len(contracts) < policy.minimum_contracts_per_expiry or sides != set(OptionSide):
            raise MarketDataProviderError("GEX_EXPIRY_INCOMPLETE")
        return _ExpiryResult(expiration, tuple(contracts), tuple(timestamps))

    @classmethod
    def _normalize_contract(
        cls, payload: Any, expiration: date
    ) -> tuple[GexOptionContract, datetime | None] | None:
        if not isinstance(payload, dict):
            return None
        details = payload.get("details")
        greeks = payload.get("greeks")
        if not isinstance(details, dict):
            return None
        try:
            symbol = str(details["ticker"])
            strike = float(details["strike_price"])
            side = OptionSide(str(details["contract_type"]).upper())
            item_expiry = date.fromisoformat(str(details.get("expiration_date") or expiration))
            open_interest = int(payload["open_interest"])
            gamma_value = greeks.get("gamma") if isinstance(greeks, dict) else None
            gamma = float(gamma_value) if gamma_value is not None else None
            iv_value = payload.get("implied_volatility")
            implied_volatility = float(iv_value) if iv_value is not None else None
            volume_value = (payload.get("day") or {}).get("volume")
            volume = int(volume_value) if volume_value is not None else None
        except (KeyError, TypeError, ValueError):
            return None
        if not symbol or strike <= 0 or item_expiry != expiration or open_interest < 0:
            return None
        timestamp = cls._timestamp_from(payload)
        return (
            GexOptionContract(
                symbol=symbol,
                expiration=item_expiry,
                strike=strike,
                side=side,
                open_interest=open_interest,
                gamma=gamma,
                implied_volatility=implied_volatility,
                volume=volume,
            ),
            timestamp,
        )

    @staticmethod
    def _first_number(*containers: Any) -> float | None:
        for container in containers:
            if isinstance(container, (int, float)):
                return float(container)
            if not isinstance(container, dict):
                continue
            for key in ("p", "price", "c", "close", "value"):
                try:
                    value = float(container[key])
                except (KeyError, TypeError, ValueError):
                    continue
                if value > 0:
                    return value
        return None

    @staticmethod
    def _timestamp_from(container: dict[str, Any]) -> datetime | None:
        candidates: list[Any] = []
        for key in ("last_quote", "lastQuote", "last_trade", "lastTrade", "day"):
            nested = container.get(key)
            if isinstance(nested, dict):
                candidates.extend(
                    nested.get(name)
                    for name in ("last_updated", "sip_timestamp", "participant_timestamp", "t")
                )
        candidates.extend((container.get("updated"), container.get("timestamp")))
        for raw in candidates:
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            if number <= 0:
                continue
            divisor = 1_000_000_000 if number > 10**17 else 1_000 if number > 10**11 else 1
            try:
                return datetime.fromtimestamp(number / divisor, UTC)
            except (OverflowError, OSError, ValueError):
                continue
        return None

    @staticmethod
    def _derived_market_status() -> str:
        now = datetime.now(UTC)
        # This is display-only; provider timestamps still drive freshness checks.
        return "closed" if now.weekday() >= 5 else "unknown"
