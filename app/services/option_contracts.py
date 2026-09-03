from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol


class ExpiryPrecision(StrEnum):
    EXACT_DATE = "EXACT_DATE"
    MONTH_DAY = "MONTH_DAY"
    MONTH_YEAR = "MONTH_YEAR"
    ZERO_DTE = "ZERO_DTE"
    AUTO_NEAREST = "AUTO_NEAREST"


class ExpiryResolutionStatus(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    AUTO_RESOLVED = "AUTO_RESOLVED"
    MANAGER_CONFIRMED = "MANAGER_CONFIRMED"
    EXPLICIT = "EXPLICIT"


class ContractValidationStatus(StrEnum):
    UNVALIDATED = "UNVALIDATED"
    VALID = "VALID"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ListedOptionContract:
    ticker: str
    underlying: str
    expiry: date
    strike: Decimal
    option_side: str


class OptionContractCatalog(Protocol):
    async def list_option_contracts(
        self,
        *,
        underlying: str,
        start: date,
        end: date,
        strike: Decimal,
        option_side: str,
    ) -> tuple[ListedOptionContract, ...]: ...


@dataclass(frozen=True, slots=True)
class ExpiryRequest:
    expiry_input: str | None
    precision: ExpiryPrecision
    ticker: str
    strike: Decimal
    option_side: str


@dataclass(frozen=True, slots=True)
class ExpiryResolution:
    expiry_input: str | None
    precision: ExpiryPrecision
    resolved_expiry: date | None
    resolution_status: ExpiryResolutionStatus
    validation_status: ContractValidationStatus
    option_contract_code: str | None
    candidates: tuple[date, ...] = ()
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class FastSignalFields:
    ticker: str
    expiry_input: str | None
    expiry_precision: ExpiryPrecision | None
    strike: Decimal
    option_side: str
    entry_price: Decimal | None
    price_parse_confidence: Decimal | None
    warning: str | None


@dataclass(frozen=True, slots=True)
class SwingCloseFields:
    public_trade_id: str | None
    ticker: str | None
    expiry_input: str | None
    expiry_precision: ExpiryPrecision | None
    strike: Decimal | None
    option_side: str | None
    reference_price: Decimal | None


_EXACT_DATE = re.compile(r"(?<!\d)(20\d{2}-\d{1,2}-\d{1,2})(?!\d)", re.IGNORECASE)
_ZERO_DTE = re.compile(r"(?<![A-Z0-9])0\s*DTE(?![A-Z0-9])", re.IGNORECASE)
_MONTH_YEAR = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])/(20\d{2})(?!\d)")
_MONTH_DAY = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?![/\d])")
_LABELED_MONTH_DAY = re.compile(
    r"(?:EXPIRY|EXP|到期(?:日|日期)?)\s*[:：]?\s*"
    r"(?P<value>(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01]))",
    re.IGNORECASE,
)
_CONTRACT_MONTH_DAY = re.compile(
    r"(?P<value>(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01]))"
    r"\s+\d+(?:\.\d+)?\s*(?:C|P|CALL|PUT)\b",
    re.IGNORECASE,
)
_TRAILING_MONTH_DAY = re.compile(
    r"\d+(?:\.\d+)?\s*(?:C|P|CALL|PUT)\s+"
    r"(?P<value>(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01]))\b",
    re.IGNORECASE,
)
_FAST_SIGNAL = re.compile(
    r"^\s*\$?(?P<ticker>[A-Z][A-Z0-9.\-]{0,11})\s+"
    r"(?:(?P<expiry>20\d{2}-\d{1,2}-\d{1,2}|0\s*DTE|"
    r"(?:0?[1-9]|1[0-2])/(?:20\d{2}|0?[1-9]|[12]\d|3[01]))\s+)?"
    r"(?P<strike>\d+(?:\.\d+)?)\s*(?P<side>C|P|CALL|PUT)\b"
    r"(?:\s*(?P<at>@)?\s*(?P<price>(?:\d+\.\d+|\.\d+|\d+)))?"
    r"(?:\s+.*)?$",
    re.IGNORECASE,
)
_SWING_CLOSE_ID = re.compile(
    r"^\s*(?:CLOSE|平仓|关闭)\s+(?P<id>SW-\d{4,})"
    r"(?:\s*@?\s*(?P<price>\d+(?:\.\d+)?))?\s*$",
    re.IGNORECASE,
)
_SWING_CLOSE_CONTRACT = re.compile(
    r"^\s*(?:CLOSE|平仓|关闭)\s+\$?(?P<ticker>[A-Z][A-Z0-9.\-]{0,11})\s+"
    r"(?P<expiry>20\d{2}-\d{1,2}-\d{1,2}|(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01]))\s+"
    r"(?P<strike>\d+(?:\.\d+)?)\s*(?P<side>C|P|CALL|PUT)"
    r"(?:\s*@?\s*(?P<price>\d+(?:\.\d+)?))?\s*$",
    re.IGNORECASE,
)


def parse_expiry_input(value: str | None) -> tuple[str | None, ExpiryPrecision | None]:
    if value is None:
        return None, None
    normalized = value.strip().upper().replace(" ", "")
    if not normalized:
        return None, None
    if normalized == "NEAREST":
        return None, ExpiryPrecision.AUTO_NEAREST
    if normalized == "0DTE":
        return "0DTE", ExpiryPrecision.ZERO_DTE
    exact = _EXACT_DATE.fullmatch(normalized)
    if exact:
        try:
            parsed = date.fromisoformat(exact.group(1))
        except ValueError:
            return value.strip(), None
        return parsed.isoformat(), ExpiryPrecision.EXACT_DATE
    month_year = _MONTH_YEAR.fullmatch(normalized)
    if month_year:
        return f"{int(month_year.group(1))}/{month_year.group(2)}", ExpiryPrecision.MONTH_YEAR
    month_day = _MONTH_DAY.fullmatch(normalized)
    if month_day:
        try:
            date(2000, int(month_day.group(1)), int(month_day.group(2)))
        except ValueError:
            return value.strip(), None
        return f"{int(month_day.group(1))}/{int(month_day.group(2))}", ExpiryPrecision.MONTH_DAY
    return value.strip(), None


def extract_expiry_input(raw_text: str | None) -> tuple[str | None, ExpiryPrecision | None]:
    if not raw_text:
        return None, None
    for pattern in (_EXACT_DATE, _ZERO_DTE, _MONTH_YEAR):
        match = pattern.search(raw_text)
        if match:
            return parse_expiry_input(match.group(0))
    for pattern in (_LABELED_MONTH_DAY, _CONTRACT_MONTH_DAY, _TRAILING_MONTH_DAY):
        match = pattern.search(raw_text)
        if match:
            return parse_expiry_input(match.group("value"))
    return None, None


def parse_fast_signal(raw_text: str | None) -> FastSignalFields | None:
    if not raw_text:
        return None
    match = _FAST_SIGNAL.fullmatch(raw_text.strip())
    if match is None:
        return None
    try:
        strike = Decimal(match.group("strike"))
    except InvalidOperation:
        return None
    expiry_input, precision = parse_expiry_input(match.group("expiry"))
    side = match.group("side").upper()
    option_side = "CALL" if side in {"C", "CALL"} else "PUT"
    raw_price = match.group("price")
    entry_price: Decimal | None = None
    confidence: Decimal | None = None
    warning: str | None = None
    if raw_price is not None:
        try:
            parsed_price = Decimal(raw_price)
        except InvalidOperation:
            parsed_price = Decimal("-1")
        if match.group("at") and "." not in raw_price:
            cents = int(parsed_price) if parsed_price >= 0 else -1
            if 0 < cents < 100:
                entry_price = parsed_price / Decimal("100")
                confidence = Decimal("0.60")
                warning = f"Interpreted {cents} as ${entry_price:.2f} option premium."
            else:
                confidence = Decimal("0.20")
                warning = f"Ambiguous integer option premium: {raw_price}."
        elif parsed_price > 0:
            entry_price = parsed_price
            confidence = Decimal("1.00")
    return FastSignalFields(
        ticker=match.group("ticker").upper(),
        expiry_input=expiry_input,
        expiry_precision=precision,
        strike=strike,
        option_side=option_side,
        entry_price=entry_price,
        price_parse_confidence=confidence,
        warning=warning,
    )


def parse_swing_close(raw_text: str | None) -> SwingCloseFields | None:
    """Parse the intentionally small Manager close grammar without guessing."""

    if not raw_text:
        return None
    identifier = _SWING_CLOSE_ID.fullmatch(raw_text.strip())
    if identifier is not None:
        raw_price = identifier.group("price")
        return SwingCloseFields(
            public_trade_id=identifier.group("id").upper(),
            ticker=None,
            expiry_input=None,
            expiry_precision=None,
            strike=None,
            option_side=None,
            reference_price=Decimal(raw_price) if raw_price else None,
        )
    contract = _SWING_CLOSE_CONTRACT.fullmatch(raw_text.strip())
    if contract is None:
        return None
    expiry_input, precision = parse_expiry_input(contract.group("expiry"))
    side = contract.group("side").upper()
    raw_price = contract.group("price")
    return SwingCloseFields(
        public_trade_id=None,
        ticker=contract.group("ticker").upper(),
        expiry_input=expiry_input,
        expiry_precision=precision,
        strike=Decimal(contract.group("strike")),
        option_side="CALL" if side in {"C", "CALL"} else "PUT",
        reference_price=Decimal(raw_price) if raw_price else None,
    )


class OptionContractResolver:
    def __init__(self, catalog: OptionContractCatalog, *, today: date | None = None) -> None:
        self.catalog = catalog
        self._today = today

    @property
    def today(self) -> date:
        return self._today or date.today()

    async def resolve(self, request: ExpiryRequest) -> ExpiryResolution:
        if request.precision is ExpiryPrecision.EXACT_DATE:
            try:
                candidate = date.fromisoformat(request.expiry_input or "")
            except ValueError:
                return self._unresolved(request, ContractValidationStatus.NOT_FOUND)
            return await self._resolve_exact(request, candidate, explicit=True)

        if request.precision is ExpiryPrecision.ZERO_DTE:
            return await self._resolve_exact(request, self.today, explicit=True)

        if request.precision is ExpiryPrecision.MONTH_DAY:
            parsed_input, parsed_precision = parse_expiry_input(request.expiry_input)
            if parsed_precision is not ExpiryPrecision.MONTH_DAY or parsed_input is None:
                return self._unresolved(request, ContractValidationStatus.NOT_FOUND)
            month, day = (int(part) for part in parsed_input.split("/"))
            candidates = []
            for year in range(self.today.year, self.today.year + 3):
                try:
                    candidate = date(year, month, day)
                except ValueError:
                    continue
                if candidate >= self.today:
                    candidates.append(candidate)
            for candidate in candidates:
                resolved = await self._resolve_exact(request, candidate, explicit=False)
                if resolved.resolved_expiry is not None:
                    return resolved
                if resolved.validation_status is ContractValidationStatus.UNAVAILABLE:
                    return resolved
            return self._unresolved(
                request,
                ContractValidationStatus.NOT_FOUND,
                warning="OPTION_CONTRACT_NOT_FOUND",
            )

        if request.precision is ExpiryPrecision.MONTH_YEAR:
            parsed_input, parsed_precision = parse_expiry_input(request.expiry_input)
            if parsed_precision is not ExpiryPrecision.MONTH_YEAR or parsed_input is None:
                return self._unresolved(request, ContractValidationStatus.NOT_FOUND)
            month, year = (int(part) for part in parsed_input.split("/"))
            start = date(year, month, 1)
            end = date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
            contracts = await self._contracts(request, start, end)
            if contracts is None:
                return self._unresolved(request, ContractValidationStatus.UNAVAILABLE)
            expirations = tuple(sorted({contract.expiry for contract in contracts}))
            if len(expirations) == 1:
                return self._resolved(
                    request,
                    contracts,
                    expirations[0],
                    ExpiryResolutionStatus.AUTO_RESOLVED,
                    candidates=expirations,
                )
            return self._unresolved(
                request,
                ContractValidationStatus.UNVALIDATED,
                candidates=expirations,
                warning=(
                    "MULTIPLE_EXPIRATIONS_REQUIRE_MANAGER"
                    if expirations
                    else "OPTION_CONTRACT_NOT_FOUND"
                ),
            )

        contracts = await self._contracts(request, self.today, self.today + timedelta(days=400))
        if contracts is None:
            return self._unresolved(request, ContractValidationStatus.UNAVAILABLE)
        expirations = tuple(sorted({contract.expiry for contract in contracts}))
        if not expirations:
            return self._unresolved(
                request,
                ContractValidationStatus.NOT_FOUND,
                warning="OPTION_CONTRACT_NOT_FOUND",
            )
        return self._resolved(
            request,
            contracts,
            expirations[0],
            ExpiryResolutionStatus.AUTO_RESOLVED,
            candidates=expirations[:24],
        )

    async def validate_exact(
        self,
        *,
        ticker: str,
        expiry: date,
        strike: Decimal,
        option_side: str,
        manager_confirmed: bool = False,
    ) -> ExpiryResolution:
        request = ExpiryRequest(
            expiry_input=expiry.isoformat(),
            precision=ExpiryPrecision.EXACT_DATE,
            ticker=ticker,
            strike=strike,
            option_side=option_side,
        )
        return await self._resolve_exact(
            request,
            expiry,
            explicit=not manager_confirmed,
            manager_confirmed=manager_confirmed,
        )

    async def _resolve_exact(
        self,
        request: ExpiryRequest,
        candidate: date,
        *,
        explicit: bool,
        manager_confirmed: bool = False,
    ) -> ExpiryResolution:
        if candidate < self.today:
            return self._unresolved(
                request,
                ContractValidationStatus.NOT_FOUND,
                warning="EXPIRY_IN_PAST_REQUIRES_REVIEW",
            )
        contracts = await self._contracts(request, candidate, candidate)
        if contracts is None:
            return self._unresolved(request, ContractValidationStatus.UNAVAILABLE)
        if not contracts:
            return self._unresolved(
                request,
                ContractValidationStatus.NOT_FOUND,
                warning="OPTION_CONTRACT_NOT_FOUND",
            )
        status = (
            ExpiryResolutionStatus.MANAGER_CONFIRMED
            if manager_confirmed
            else ExpiryResolutionStatus.EXPLICIT
            if explicit
            else ExpiryResolutionStatus.AUTO_RESOLVED
        )
        return self._resolved(request, contracts, candidate, status, candidates=(candidate,))

    async def _contracts(
        self, request: ExpiryRequest, start: date, end: date
    ) -> tuple[ListedOptionContract, ...] | None:
        try:
            return await self.catalog.list_option_contracts(
                underlying=request.ticker,
                start=start,
                end=end,
                strike=request.strike,
                option_side=request.option_side,
            )
        except Exception:
            return None

    @staticmethod
    def _resolved(
        request: ExpiryRequest,
        contracts: tuple[ListedOptionContract, ...],
        expiry: date,
        status: ExpiryResolutionStatus,
        *,
        candidates: tuple[date, ...],
    ) -> ExpiryResolution:
        matching = [contract for contract in contracts if contract.expiry == expiry]
        contract = matching[0]
        return ExpiryResolution(
            expiry_input=request.expiry_input,
            precision=request.precision,
            resolved_expiry=expiry,
            resolution_status=status,
            validation_status=ContractValidationStatus.VALID,
            option_contract_code=contract.ticker,
            candidates=candidates,
        )

    @staticmethod
    def _unresolved(
        request: ExpiryRequest,
        validation_status: ContractValidationStatus,
        *,
        candidates: tuple[date, ...] = (),
        warning: str | None = "OPTION_CHAIN_UNAVAILABLE",
    ) -> ExpiryResolution:
        return ExpiryResolution(
            expiry_input=request.expiry_input,
            precision=request.precision,
            resolved_expiry=None,
            resolution_status=ExpiryResolutionStatus.UNRESOLVED,
            validation_status=validation_status,
            option_contract_code=None,
            candidates=candidates,
            warning=warning,
        )
