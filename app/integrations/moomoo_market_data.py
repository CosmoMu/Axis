from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

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
