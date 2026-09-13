"""Option-chain provider boundary for the read-only AXIS GEX Explorer."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from contextlib import suppress
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

_MOOMOO_CHAIN_LOCK = threading.Lock()
_MOOMOO_CHAIN_CALLS: deque[float] = deque()
_MOOMOO_CHAIN_WINDOW_SECONDS = 30.0
_MOOMOO_CHAIN_MAX_CALLS = 9


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
            open_interest_value = payload.get("open_interest")
            open_interest = int(open_interest_value) if open_interest_value is not None else None
            gamma_value = greeks.get("gamma") if isinstance(greeks, dict) else None
            gamma = float(gamma_value) if gamma_value is not None else None
            iv_value = payload.get("implied_volatility")
            implied_volatility = float(iv_value) if iv_value is not None else None
            volume_value = (payload.get("day") or {}).get("volume")
            volume = int(volume_value) if volume_value is not None else None
        except (KeyError, TypeError, ValueError):
            return None
        if (
            not symbol
            or strike <= 0
            or item_expiry != expiration
            or (open_interest is not None and open_interest < 0)
            or (volume is not None and volume < 0)
        ):
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


class MoomooGexMarketDataProvider:
    """Moomoo OpenD option surface normalized for the existing AXIS GEX engine."""

    name = "moomoo"
    _SNAPSHOT_BATCH_LIMIT = 400

    def __init__(self, *, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.last_metrics: dict[str, int] = {}

    async def fetch(self, ticker: str, policy: GexFetchPolicy) -> GexProviderResult:
        return await asyncio.to_thread(self._fetch_sync, ticker, policy)

    def _fetch_sync(self, ticker: str, policy: GexFetchPolicy) -> GexProviderResult:
        try:
            from moomoo import RET_OK, OpenQuoteContext, SysConfig
        except Exception as exc:
            raise MarketDataProviderError("MOOMOO_SDK_UNAVAILABLE") from exc

        symbol = ticker.strip().upper().removeprefix("US.")
        if symbol in {"SPX", "SPXW", ".SPX"}:
            code = "US..SPX"
            normalized_symbol = "SPX"
        elif symbol:
            code = f"US.{symbol}"
            normalized_symbol = symbol
        else:
            raise MarketDataProviderError("GEX_TICKER_INVALID")

        SysConfig.enable_console_log(False)
        context = None
        fetched_at = datetime.now(UTC)
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            spot, spot_timestamp = self._spot(context, code, RET_OK, normalized_symbol)
            market_status = self._market_status(context, RET_OK)
            start = fetched_at.astimezone(ZoneInfo("America/New_York")).date()
            end = start + timedelta(days=policy.expiration_horizon_days)
            strike_min = max(0.01, spot * (1 - policy.strike_range_pct))
            strike_max = spot * (1 + policy.strike_range_pct)
            rows_by_expiry: dict[date, list[dict[str, Any]]] = {}
            chain_calls = 0
            window_start = start
            while (
                window_start <= end
                and len(rows_by_expiry) < policy.expiration_candidates
            ):
                window_end = min(end, window_start + timedelta(days=29))
                chain_calls += 1
                ret, chain = self._get_option_chain(
                    context,
                    code,
                    window_start,
                    window_end,
                )
                if ret != RET_OK or not hasattr(chain, "iterrows"):
                    raise MarketDataProviderError("MOOMOO_OPTION_CHAIN_UNAVAILABLE")
                for _, row in chain.iterrows():
                    try:
                        expiry = date.fromisoformat(str(row["strike_time"])[:10])
                        strike = float(row["strike_price"])
                        option_type = str(row["option_type"]).upper()
                        option_code = str(row["code"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if (
                        start <= expiry <= end
                        and strike_min <= strike <= strike_max
                        and option_type in {"CALL", "PUT"}
                        and option_code.startswith("US.")
                    ):
                        rows_by_expiry.setdefault(expiry, []).append(
                            {
                                "code": option_code,
                                "expiry": expiry,
                                "strike": strike,
                                "side": option_type,
                            }
                        )
                window_start = window_end + timedelta(days=1)

            candidates = tuple(sorted(rows_by_expiry))[: policy.expiration_candidates]
            if not candidates:
                raise MarketDataProviderError("GEX_NO_EXPIRATIONS")
            metadata = [row for expiry in candidates for row in rows_by_expiry[expiry]]
            requested_codes = tuple(dict.fromkeys(str(row["code"]) for row in metadata))
            snapshots: dict[str, dict[str, Any]] = {}
            batch_size = max(1, min(self._SNAPSHOT_BATCH_LIMIT, policy.snapshot_page_limit))
            snapshot_calls = 0
            for offset in range(0, len(requested_codes), batch_size):
                snapshot_calls += 1
                ret, frame = context.get_market_snapshot(
                    list(requested_codes[offset : offset + batch_size])
                )
                if ret != RET_OK or not hasattr(frame, "iterrows"):
                    raise MarketDataProviderError("MOOMOO_MARKET_SNAPSHOT_UNAVAILABLE")
                for _, row in frame.iterrows():
                    row_code = row.get("code")
                    if isinstance(row_code, str):
                        snapshots[row_code] = row.to_dict()

            valid: list[_ExpiryResult] = []
            failed: list[tuple[date, str]] = []
            metadata_by_code = {str(row["code"]): row for row in metadata}
            for expiry in candidates:
                contracts: list[GexOptionContract] = []
                timestamps: list[datetime] = []
                sides: set[OptionSide] = set()
                for item in rows_by_expiry[expiry]:
                    normalized = self._normalize_contract(
                        metadata_by_code[str(item["code"])],
                        snapshots.get(str(item["code"])),
                    )
                    if normalized is None:
                        continue
                    contract, timestamp = normalized
                    contracts.append(contract)
                    sides.add(contract.side)
                    if timestamp is not None:
                        timestamps.append(timestamp)
                if (
                    len(contracts) >= policy.minimum_contracts_per_expiry
                    and sides == set(OptionSide)
                ):
                    valid.append(_ExpiryResult(expiry, tuple(contracts), tuple(timestamps)))
                    if len(valid) >= policy.expiration_count:
                        break
                else:
                    failed.append((expiry, "MOOMOO_GEX_DATA_QUALITY_FAILURE"))

            selected = valid[: policy.expiration_count]
            contracts = tuple(contract for result in selected for contract in result.contracts)
            self.last_metrics = {
                "chain_calls": chain_calls,
                "snapshot_calls": snapshot_calls + 1,
                "requested_contracts": len(requested_codes),
                "received_contracts": len(snapshots),
                "usable_contracts": len(contracts),
            }
            if len(selected) < policy.minimum_valid_expirations or not contracts:
                raise MarketDataProviderError("MOOMOO_GEX_MIN_COVERAGE_FAILURE")
            timestamps = [spot_timestamp]
            timestamps.extend(ts for result in selected for ts in result.source_timestamps)
            return GexProviderResult(
                ticker=normalized_symbol,
                provider=self.name,
                spot=spot,
                contracts=contracts,
                candidate_expirations=candidates,
                used_expirations=tuple(result.expiration for result in selected),
                failed_expirations=tuple(failed),
                source_timestamp=max(timestamps),
                fetched_at=fetched_at,
                market_status=market_status,
            )
        except MarketDataProviderError:
            raise
        except Exception as exc:
            raise MarketDataProviderError("MOOMOO_CONNECTION_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    @staticmethod
    def _get_option_chain(
        context: Any,
        code: str,
        start: date,
        end: date,
    ) -> tuple[int, Any]:
        with _MOOMOO_CHAIN_LOCK:
            now = time.monotonic()
            while (
                _MOOMOO_CHAIN_CALLS
                and now - _MOOMOO_CHAIN_CALLS[0] >= _MOOMOO_CHAIN_WINDOW_SECONDS
            ):
                _MOOMOO_CHAIN_CALLS.popleft()
            if len(_MOOMOO_CHAIN_CALLS) >= _MOOMOO_CHAIN_MAX_CALLS:
                delay = _MOOMOO_CHAIN_WINDOW_SECONDS - (now - _MOOMOO_CHAIN_CALLS[0]) + 0.1
                time.sleep(max(0.0, delay))
                now = time.monotonic()
                while (
                    _MOOMOO_CHAIN_CALLS
                    and now - _MOOMOO_CHAIN_CALLS[0] >= _MOOMOO_CHAIN_WINDOW_SECONDS
                ):
                    _MOOMOO_CHAIN_CALLS.popleft()
            result = context.get_option_chain(
                code,
                start=start.isoformat(),
                end=end.isoformat(),
            )
            _MOOMOO_CHAIN_CALLS.append(time.monotonic())
            return result

    @staticmethod
    def _spot(context: Any, code: str, ret_ok: int, symbol: str) -> tuple[float, datetime]:
        ret, frame = context.get_market_snapshot([code])
        if ret != ret_ok or not hasattr(frame, "iloc") or frame.empty:
            error = (
                "SPX_PROVIDER_UNSUPPORTED"
                if symbol == "SPX"
                else "MOOMOO_MARKET_SNAPSHOT_UNAVAILABLE"
            )
            raise MarketDataProviderError(error)
        row = frame.iloc[0]
        try:
            spot = float(row.get("last_price"))
        except (TypeError, ValueError):
            spot = 0
        timestamp = MoomooGexMarketDataProvider._timestamp(row.get("update_time"))
        if spot <= 0 or timestamp is None:
            error = "SPX_PROVIDER_UNSUPPORTED" if symbol == "SPX" else "GEX_SPOT_UNAVAILABLE"
            raise MarketDataProviderError(error)
        return spot, timestamp

    @staticmethod
    def _market_status(context: Any, ret_ok: int) -> str:
        ret, state = context.get_global_state()
        if ret == ret_ok and isinstance(state, dict):
            return str(state.get("market_us") or "unknown").lower()
        return "unknown"

    @staticmethod
    def _timestamp(raw: object) -> datetime | None:
        if not isinstance(raw, str) or not raw.strip():
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            with suppress(ValueError):
                return datetime.strptime(raw.strip(), fmt).replace(
                    tzinfo=ZoneInfo("America/New_York")
                )
        return None

    @classmethod
    def _normalize_contract(
        cls,
        metadata: dict[str, Any],
        snapshot: dict[str, Any] | None,
    ) -> tuple[GexOptionContract, datetime | None] | None:
        if snapshot is None:
            return None
        try:
            symbol = str(metadata["code"])
            expiration = metadata["expiry"]
            strike = float(metadata["strike"])
            side = OptionSide(str(metadata["side"]))
            open_interest = int(snapshot["option_open_interest"])
            gamma = float(snapshot["option_gamma"])
            iv_percent = float(snapshot["option_implied_volatility"])
            volume = int(snapshot["volume"])
        except (KeyError, TypeError, ValueError):
            return None
        if (
            not isinstance(expiration, date)
            or strike <= 0
            or open_interest < 0
            or gamma <= 0
            or iv_percent <= 0
            or volume < 0
        ):
            return None
        return (
            GexOptionContract(
                symbol=symbol,
                expiration=expiration,
                strike=strike,
                side=side,
                open_interest=open_interest,
                gamma=gamma,
                implied_volatility=iv_percent / 100,
                volume=volume,
            ),
            cls._timestamp(snapshot.get("update_time")),
        )
