from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.integrations.massive_market_data import (
    MarketDataProviderError,
    MarketPrice,
    MarketPriceFailure,
    MarketPriceRequest,
    massive_option_ticker,
)
from app.services.option_contracts import ListedOptionContract

ET = ZoneInfo("America/New_York")
POST_CLOSE_STATES = frozenset({"CLOSED", "AFTER_HOURS_BEGIN", "AFTER_HOURS_END"})


class MarketDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OptionQuoteRequest:
    key: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    instrument_code: str | None = None


@dataclass(frozen=True, slots=True)
class OptionQuote:
    key: str
    instrument_code: str | None
    last_price: Decimal | None
    quote_time: datetime | None
    error_code: str | None = None
    price_type: str = "LAST"


@dataclass(frozen=True, slots=True)
class PostCloseQuoteBatch:
    session_date: date
    market_state: str
    is_trading_session: bool
    quotes: tuple[OptionQuote, ...]
    provider: str = "UNKNOWN"


class PostCloseMarketData(Protocol):
    async def fetch_post_close(
        self,
        requests: tuple[OptionQuoteRequest, ...],
        *,
        session_date: date,
    ) -> PostCloseQuoteBatch: ...


def normalize_us_underlying(ticker: str) -> str:
    normalized = ticker.strip().upper().removeprefix("$")
    if not normalized:
        raise MarketDataError("UNDERLYING_INVALID")
    if "." in normalized:
        market, _, symbol = normalized.partition(".")
        if market != "US" or not symbol:
            raise MarketDataError("ONLY_US_OPTIONS_SUPPORTED")
        return normalized
    return f"US.{normalized}"


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    return parsed


def _quote_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for format_string in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), format_string).replace(tzinfo=ET)
        except ValueError:
            continue
    return None


def moomoo_option_code(option_ticker: str) -> str:
    """Translate AXIS' canonical OCC ticker into a Moomoo US option code."""

    canonical = option_ticker.strip().upper()
    if not canonical.startswith("O:"):
        raise MarketDataProviderError("OPTION_CONTRACT_INVALID")
    body = canonical[2:]
    if len(body) <= 15:
        raise MarketDataProviderError("OPTION_CONTRACT_INVALID")
    root = body[:-15]
    expiry_code = body[-15:-9]
    side = body[-9]
    strike_code = body[-8:]
    if (
        not root
        or not expiry_code.isdigit()
        or side not in {"C", "P"}
        or not strike_code.isdigit()
    ):
        raise MarketDataProviderError("OPTION_CONTRACT_INVALID")
    return f"US.{root}{expiry_code}{side}{int(strike_code)}"


def _moomoo_underlying_code(ticker: str) -> str:
    normalized = ticker.strip().upper().removeprefix("$").removeprefix("US.")
    if normalized in {"SPX", "SPXW", ".SPX"}:
        return "US..SPX"
    if not normalized:
        raise MarketDataProviderError("UNDERLYING_INVALID")
    return f"US.{normalized}"


class MoomooOptionMarketDataProvider:
    """Drop-in, read-only option quote/catalog provider backed by local OpenD.

    AXIS continues to persist canonical OCC tickers (``O:...``). The Moomoo
    instrument code is an internal adapter detail, so callers do not become
    coupled to either vendor.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        price_source: str,
        max_quote_age_seconds: int,
        last_trade_quote_guard_pct: Decimal,
    ) -> None:
        if price_source not in {"BID", "MID", "LAST"}:
            raise MarketDataProviderError("PRICE_SOURCE_INVALID")
        self.host = host
        self.port = port
        self.price_source = price_source
        self.max_quote_age = timedelta(seconds=max_quote_age_seconds)
        self.last_trade_quote_guard_pct = last_trade_quote_guard_pct
        self.last_failures: tuple[MarketPriceFailure, ...] = ()

    async def fetch_prices(
        self, requests: tuple[MarketPriceRequest, ...]
    ) -> tuple[MarketPrice, ...]:
        return await asyncio.to_thread(self._fetch_prices_sync, requests)

    def _fetch_prices_sync(
        self, requests: tuple[MarketPriceRequest, ...]
    ) -> tuple[MarketPrice, ...]:
        self.last_failures = ()
        if not requests:
            return ()
        try:
            from moomoo import RET_OK, OpenQuoteContext, SysConfig
        except Exception as exc:
            raise MarketDataProviderError("MOOMOO_SDK_UNAVAILABLE") from exc

        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            market_status = "unknown"
            state_ret, state = context.get_global_state()
            if state_ret == RET_OK and isinstance(state, dict):
                market_status = str(state.get("market_us") or "unknown")

            request_codes: dict[str, str] = {}
            failures: list[MarketPriceFailure] = []
            for request in requests:
                try:
                    request_codes[request.key] = moomoo_option_code(request.option_ticker)
                except MarketDataProviderError as exc:
                    failures.append(
                        MarketPriceFailure(request.key, request.option_ticker, exc.code)
                    )

            rows: dict[str, dict[str, Any]] = {}
            codes = tuple(dict.fromkeys(request_codes.values()))
            for offset in range(0, len(codes), 400):
                ret, frame = context.get_market_snapshot(list(codes[offset : offset + 400]))
                if ret != RET_OK or not hasattr(frame, "iterrows"):
                    raise MarketDataProviderError("MOOMOO_MARKET_SNAPSHOT_UNAVAILABLE")
                for _, row in frame.iterrows():
                    code = row.get("code")
                    if isinstance(code, str):
                        rows[code] = row.to_dict()

            received_at = datetime.now(UTC)
            prices: list[MarketPrice] = []
            failed_keys = {failure.key for failure in failures}
            for request in requests:
                if request.key in failed_keys:
                    continue
                code = request_codes[request.key]
                row = rows.get(code)
                try:
                    prices.append(
                        self._normalize_tracking_snapshot(
                            request,
                            row,
                            received_at=received_at,
                            market_status=market_status,
                        )
                    )
                except MarketDataProviderError as exc:
                    failures.append(
                        MarketPriceFailure(request.key, request.option_ticker, exc.code)
                    )

            self.last_failures = tuple(failures)
            if not prices:
                first_error = failures[0].error_code if failures else "MOOMOO_BATCH_FAILED"
                raise MarketDataProviderError(first_error)
            return tuple(prices)
        except MarketDataProviderError:
            raise
        except Exception as exc:
            raise MarketDataProviderError("MOOMOO_CONNECTION_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()


    def _normalize_tracking_snapshot(
        self,
        request: MarketPriceRequest,
        row: dict[str, Any] | None,
        *,
        received_at: datetime,
        market_status: str,
    ) -> MarketPrice:
        if row is None:
            raise MarketDataProviderError("OPTION_CONTRACT_NOT_FOUND")
        bid = _decimal(row.get("bid_price"))
        ask = _decimal(row.get("ask_price"))
        last = _decimal(row.get("last_price"))
        if self.price_source == "BID":
            price = bid
        elif self.price_source == "MID":
            price = (bid + ask) / 2 if bid is not None and ask is not None else None
        else:
            price = last
            if price is not None and bid is not None and ask is not None:
                guard = self.last_trade_quote_guard_pct / Decimal("100")
                if price < bid * (Decimal("1") - guard) or price > ask * (
                    Decimal("1") + guard
                ):
                    raise MarketDataProviderError("LAST_TRADE_OUTLIER")
        source_timestamp = _quote_time(row.get("update_time"))
        if price is None or source_timestamp is None:
            raise MarketDataProviderError("MOOMOO_PRICE_UNAVAILABLE")
        if received_at - source_timestamp.astimezone(UTC) > self.max_quote_age:
            raise MarketDataProviderError("MOOMOO_QUOTE_STALE")
        return MarketPrice(
            key=request.key,
            option_ticker=request.option_ticker,
            price=price,
            price_source=self.price_source,
            source_timestamp=source_timestamp,
            received_at=received_at,
            market_status=market_status,
        )

    async def list_option_contracts(
        self,
        *,
        underlying: str,
        start: date,
        end: date,
        strike: Decimal,
        option_side: str,
    ) -> tuple[ListedOptionContract, ...]:
        return await asyncio.to_thread(
            self._list_option_contracts_sync,
            underlying,
            start,
            end,
            strike,
            option_side,
        )

    def _list_option_contracts_sync(
        self,
        underlying: str,
        start: date,
        end: date,
        strike: Decimal,
        option_side: str,
    ) -> tuple[ListedOptionContract, ...]:
        try:
            from moomoo import RET_OK, OpenQuoteContext, OptionType, SysConfig
        except Exception as exc:
            raise MarketDataProviderError("MOOMOO_SDK_UNAVAILABLE") from exc
        option_type = {"CALL": OptionType.CALL, "PUT": OptionType.PUT}.get(option_side)
        if option_type is None or strike <= 0 or start > end:
            raise MarketDataProviderError("OPTION_CONTRACT_INVALID")
        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            ret, frame = context.get_option_chain(
                _moomoo_underlying_code(underlying),
                start=start.isoformat(),
                end=end.isoformat(),
                option_type=option_type,
            )
            if ret != RET_OK or not hasattr(frame, "iterrows"):
                raise MarketDataProviderError("OPTION_CHAIN_UNAVAILABLE")
            contracts: dict[str, ListedOptionContract] = {}
            for _, row in frame.iterrows():
                try:
                    expiry = date.fromisoformat(str(row["strike_time"])[:10])
                    row_strike = Decimal(str(row["strike_price"]))
                    row_side = str(row["option_type"])
                    code = str(row["code"])
                except (InvalidOperation, KeyError, TypeError, ValueError):
                    continue
                if row_strike != strike or row_side != option_side or not start <= expiry <= end:
                    continue
                side_code = "C" if option_side == "CALL" else "P"
                suffix = f"{expiry:%y%m%d}{side_code}{int(strike * 1000)}"
                value = code.removeprefix("US.")
                root = value[: -len(suffix)] if value.endswith(suffix) else underlying.upper()
                canonical = massive_option_ticker(root, expiry, row_strike, option_side)
                contracts[canonical] = ListedOptionContract(
                    ticker=canonical,
                    underlying=underlying.strip().upper().removeprefix("US."),
                    expiry=expiry,
                    strike=row_strike,
                    option_side=option_side,
                )
            return tuple(sorted(contracts.values(), key=lambda item: (item.expiry, item.ticker)))
        except MarketDataProviderError:
            raise
        except Exception as exc:
            raise MarketDataProviderError("OPTION_CHAIN_UNAVAILABLE") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()


class MoomooOptionOrderBookProvider:
    """Persistent read-only MID quotes from Moomoo ORDER_BOOK pushes.

    This provider is intended for shadow acceptance first. Unlike snapshot
    ``update_time``, order-book pushes expose bid/ask server timestamps and
    therefore match AXIS' MID freshness requirement.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        price_source: str,
        max_quote_age_seconds: int,
    ) -> None:
        if price_source not in {"BID", "MID"}:
            raise MarketDataProviderError("PRICE_SOURCE_INVALID")
        self.host = host
        self.port = port
        self.price_source = price_source
        self.max_quote_age = timedelta(seconds=max_quote_age_seconds)
        self.last_failures: tuple[MarketPriceFailure, ...] = ()
        self._lock = threading.Lock()
        self._context: Any | None = None
        self._codes: set[str] = set()
        self._books: dict[str, tuple[Decimal, Decimal, datetime, datetime]] = {}

    async def prepare(self, requests: tuple[MarketPriceRequest, ...]) -> None:
        await asyncio.to_thread(self._prepare_sync, requests)

    def _prepare_sync(self, requests: tuple[MarketPriceRequest, ...]) -> None:
        try:
            from moomoo import (
                RET_ERROR,
                RET_OK,
                OpenQuoteContext,
                OrderBookHandlerBase,
                SubType,
                SysConfig,
            )
        except Exception as exc:
            raise MarketDataProviderError("MOOMOO_SDK_UNAVAILABLE") from exc

        requested_codes = {moomoo_option_code(request.option_ticker) for request in requests}
        with self._lock:
            new_codes = tuple(sorted(requested_codes - self._codes))
        if not new_codes:
            return
        SysConfig.enable_console_log(False)
        try:
            if self._context is None:
                provider = self

                class Handler(OrderBookHandlerBase):
                    def on_recv_rsp(self, rsp_pb: object) -> tuple[int, object]:
                        ret, payload = super().on_recv_rsp(rsp_pb)
                        if ret != RET_OK:
                            return RET_ERROR, payload
                        provider._record_order_book(payload)
                        return RET_OK, payload

                self._context = OpenQuoteContext(host=self.host, port=self.port)
                self._context.set_handler(Handler())
            ret, _detail = self._context.subscribe(
                list(new_codes),
                [SubType.ORDER_BOOK],
                is_first_push=True,
                subscribe_push=True,
            )
            if ret != RET_OK:
                raise MarketDataProviderError("MOOMOO_ORDER_BOOK_SUBSCRIBE_FAILED")
            with self._lock:
                self._codes.update(new_codes)
        except MarketDataProviderError:
            raise
        except Exception as exc:
            raise MarketDataProviderError("MOOMOO_CONNECTION_FAILED") from exc

    def _record_order_book(self, payload: object) -> None:
        normalized = self._normalize_order_book_payload(payload)
        if normalized is None:
            return
        code, bid, ask, source_timestamp = normalized
        with self._lock:
            self._books[code] = (bid, ask, source_timestamp, datetime.now(UTC))

    @staticmethod
    def _normalize_order_book_payload(
        payload: object,
    ) -> tuple[str, Decimal, Decimal, datetime] | None:
        if not isinstance(payload, dict):
            return None
        code = payload.get("code")
        bids = payload.get("Bid")
        asks = payload.get("Ask")
        if not isinstance(code, str) or not isinstance(bids, list) or not isinstance(asks, list):
            return None
        if (
            not bids
            or not asks
            or not isinstance(bids[0], (list, tuple))
            or not isinstance(asks[0], (list, tuple))
        ):
            return None
        bid = _decimal(bids[0][0] if bids[0] else None)
        ask = _decimal(asks[0][0] if asks[0] else None)
        bid_time = _quote_time(payload.get("svr_recv_time_bid"))
        ask_time = _quote_time(payload.get("svr_recv_time_ask"))
        timestamps = tuple(value for value in (bid_time, ask_time) if value is not None)
        if bid is None or ask is None or not timestamps:
            return None
        return code, bid, ask, max(timestamps)

    async def fetch_prices(
        self, requests: tuple[MarketPriceRequest, ...]
    ) -> tuple[MarketPrice, ...]:
        needs_subscription = any(
            moomoo_option_code(request.option_ticker) not in self._codes
            for request in requests
        )
        if needs_subscription:
            await self.prepare(requests)
        received_at = datetime.now(UTC)
        prices = []
        failures = []
        with self._lock:
            books = dict(self._books)
        for request in requests:
            code = moomoo_option_code(request.option_ticker)
            book = books.get(code)
            if book is None:
                failures.append(
                    MarketPriceFailure(
                        request.key,
                        request.option_ticker,
                        "MOOMOO_ORDER_BOOK_UNAVAILABLE",
                    )
                )
                continue
            bid, ask, source_timestamp, callback_received_at = book
            if received_at - source_timestamp.astimezone(UTC) > self.max_quote_age:
                failures.append(
                    MarketPriceFailure(
                        request.key,
                        request.option_ticker,
                        "MOOMOO_QUOTE_STALE",
                    )
                )
                continue
            price = bid if self.price_source == "BID" else (bid + ask) / 2
            prices.append(
                MarketPrice(
                    key=request.key,
                    option_ticker=request.option_ticker,
                    price=price,
                    price_source=self.price_source,
                    source_timestamp=source_timestamp,
                    received_at=callback_received_at,
                    market_status="ORDER_BOOK_PUSH",
                )
            )
        self.last_failures = tuple(failures)
        if not prices:
            error = failures[0].error_code if failures else "MOOMOO_ORDER_BOOK_UNAVAILABLE"
            raise MarketDataProviderError(error)
        return tuple(prices)

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        context = self._context
        with self._lock:
            self._context = None
            self._codes.clear()
            self._books.clear()
        if context is not None:
            with suppress(Exception):
                context.close()


class MoomooMarketDataClient:
    """Read-only US option snapshots through a local Moomoo OpenD instance."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    async def fetch_post_close(
        self,
        requests: tuple[OptionQuoteRequest, ...],
        *,
        session_date: date,
    ) -> PostCloseQuoteBatch:
        return await asyncio.to_thread(self._fetch_post_close_sync, requests, session_date)

    def _fetch_post_close_sync(
        self,
        requests: tuple[OptionQuoteRequest, ...],
        session_date: date,
    ) -> PostCloseQuoteBatch:
        try:
            from moomoo import RET_OK, OpenQuoteContext, OptionType, SysConfig
        except Exception as exc:
            raise MarketDataError("MOOMOO_SDK_UNAVAILABLE") from exc

        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            state_ret, state = context.get_global_state()
            if state_ret != RET_OK or not isinstance(state, dict):
                raise MarketDataError("MOOMOO_STATE_UNAVAILABLE")
            market_state = str(state.get("market_us") or "UNKNOWN")
            if market_state not in POST_CLOSE_STATES:
                raise MarketDataError("US_MARKET_NOT_POST_CLOSE")

            anchor = self._snapshots(context, ("US.SPY",), RET_OK).get("US.SPY")
            anchor_time = _quote_time(anchor.get("update_time")) if anchor else None
            if anchor_time is None:
                raise MarketDataError("TRADING_SESSION_UNVERIFIED")
            if anchor_time.date() != session_date:
                return PostCloseQuoteBatch(
                    session_date=session_date,
                    market_state=market_state,
                    is_trading_session=False,
                    quotes=(),
                    provider="MOOMOO",
                )

            resolved: dict[str, str] = {}
            failures: dict[str, str] = {}
            for request in requests:
                if request.instrument_code:
                    resolved[request.key] = request.instrument_code
                    continue
                try:
                    resolved[request.key] = self._resolve_option_code(
                        context,
                        request,
                        option_type={"CALL": OptionType.CALL, "PUT": OptionType.PUT}.get(
                            request.option_side
                        ),
                        ret_ok=RET_OK,
                    )
                except MarketDataError as exc:
                    failures[request.key] = exc.code

            codes = tuple(dict.fromkeys(resolved.values()))
            rows: dict[str, dict[str, Any]] = {}
            for offset in range(0, len(codes), 400):
                rows.update(self._snapshots(context, codes[offset : offset + 400], RET_OK))

            quotes = []
            for request in requests:
                code = resolved.get(request.key)
                if code is None:
                    quotes.append(
                        OptionQuote(
                            key=request.key,
                            instrument_code=None,
                            last_price=None,
                            quote_time=None,
                            error_code=failures.get(request.key, "OPTION_CODE_UNAVAILABLE"),
                        )
                    )
                    continue
                row = rows.get(code)
                price = _decimal(row.get("last_price")) if row else None
                updated_at = _quote_time(row.get("update_time")) if row else None
                quotes.append(
                    OptionQuote(
                        key=request.key,
                        instrument_code=code,
                        last_price=price,
                        quote_time=updated_at,
                        error_code=(
                            None
                            if price is not None and updated_at is not None
                            else "QUOTE_UNAVAILABLE"
                        ),
                    )
                )
            return PostCloseQuoteBatch(
                session_date=session_date,
                market_state=market_state,
                is_trading_session=True,
                quotes=tuple(quotes),
                provider="MOOMOO",
            )
        except MarketDataError:
            raise
        except Exception as exc:
            raise MarketDataError("MOOMOO_CONNECTION_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    @staticmethod
    def _resolve_option_code(
        context: Any,
        request: OptionQuoteRequest,
        *,
        option_type: object | None,
        ret_ok: int,
    ) -> str:
        if option_type is None:
            raise MarketDataError("OPTION_SIDE_INVALID")
        underlying = normalize_us_underlying(request.ticker)
        expiry = request.expiry.isoformat()
        ret, frame = context.get_option_chain(
            underlying,
            start=expiry,
            end=expiry,
            option_type=option_type,
        )
        if ret != ret_ok or not hasattr(frame, "iterrows"):
            raise MarketDataError("OPTION_CHAIN_UNAVAILABLE")
        matches: list[str] = []
        for _, row in frame.iterrows():
            try:
                strike = Decimal(str(row["strike_price"]))
            except (InvalidOperation, KeyError, TypeError, ValueError):
                continue
            if (
                str(row.get("strike_time"))[:10] == expiry
                and str(row.get("option_type")) == request.option_side
                and strike == request.strike
                and isinstance(row.get("code"), str)
            ):
                matches.append(str(row["code"]))
        unique_matches = tuple(dict.fromkeys(matches))
        if len(unique_matches) != 1:
            raise MarketDataError(
                "OPTION_CONTRACT_NOT_FOUND" if not unique_matches else "OPTION_CONTRACT_AMBIGUOUS"
            )
        return unique_matches[0]

    @staticmethod
    def _snapshots(context: Any, codes: tuple[str, ...], ret_ok: int) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}
        ret, frame = context.get_market_snapshot(list(codes))
        if ret != ret_ok or not hasattr(frame, "iterrows"):
            raise MarketDataError("MARKET_SNAPSHOT_UNAVAILABLE")
        rows: dict[str, dict[str, Any]] = {}
        for _, row in frame.iterrows():
            code = row.get("code")
            if isinstance(code, str):
                rows[code] = row.to_dict()
        return rows
