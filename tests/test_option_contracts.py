from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.option_contracts import (
    ContractValidationStatus,
    ExpiryPrecision,
    ExpiryRequest,
    ExpiryResolutionStatus,
    ListedOptionContract,
    OptionContractResolver,
    extract_expiry_input,
    parse_fast_signal,
)


class FakeCatalog:
    def __init__(self, contracts: tuple[ListedOptionContract, ...]) -> None:
        self.contracts = contracts
        self.calls: list[tuple[str, date, date, Decimal, str]] = []

    async def list_option_contracts(
        self,
        *,
        underlying: str,
        start: date,
        end: date,
        strike: Decimal,
        option_side: str,
    ) -> tuple[ListedOptionContract, ...]:
        self.calls.append((underlying, start, end, strike, option_side))
        return tuple(
            contract
            for contract in self.contracts
            if contract.underlying == underlying
            and start <= contract.expiry <= end
            and contract.strike == strike
            and contract.option_side == option_side
        )


def contract(ticker: str, underlying: str, expiry: date, strike: str) -> ListedOptionContract:
    return ListedOptionContract(ticker, underlying, expiry, Decimal(strike), "CALL")


@pytest.mark.parametrize(
    ("raw", "expiry_input", "precision", "price"),
    [
        ("$RIVN 10/16 18C 1.07", "10/16", ExpiryPrecision.MONTH_DAY, "1.07"),
        ("$ACHR 1/2027 7C .9", "1/2027", ExpiryPrecision.MONTH_YEAR, "0.9"),
        ("RIVN 2026-10-16 18C 1.07", "2026-10-16", ExpiryPrecision.EXACT_DATE, "1.07"),
        ("SPY 0DTE 775C .48", "0DTE", ExpiryPrecision.ZERO_DTE, "0.48"),
        ("SPY 775C 0.48", None, None, "0.48"),
        ("SPY 775C .48", None, None, "0.48"),
        ("SPY 775C @ .48", None, None, "0.48"),
    ],
)
def test_fast_signal_accepts_natural_expiry_and_decimal_prices(
    raw: str,
    expiry_input: str | None,
    precision: ExpiryPrecision | None,
    price: str,
) -> None:
    parsed = parse_fast_signal(raw)

    assert parsed is not None
    assert parsed.expiry_input == expiry_input
    assert parsed.expiry_precision is precision
    assert parsed.entry_price == Decimal(price)


def test_integer_cents_shorthand_is_candidate_with_warning() -> None:
    candidate = parse_fast_signal("SPY 775C @ 48")
    ambiguous = parse_fast_signal("SPY 775C @ 125")

    assert candidate is not None and candidate.entry_price == Decimal("0.48")
    assert candidate.price_parse_confidence == Decimal("0.60")
    assert candidate.warning == "Interpreted 48 as $0.48 option premium."
    assert ambiguous is not None and ambiguous.entry_price is None
    assert ambiguous.warning == "Ambiguous integer option premium: 125."


def test_position_fraction_is_not_mistaken_for_expiry() -> None:
    assert extract_expiry_input("入场 1/8 仓位") == (None, None)


@pytest.mark.asyncio
async def test_month_day_is_year_inferred_only_after_contract_validation() -> None:
    listed = contract("O:RIVN261016C00018000", "RIVN", date(2026, 10, 16), "18")
    resolver = OptionContractResolver(FakeCatalog((listed,)), today=date(2026, 8, 30))

    result = await resolver.resolve(
        ExpiryRequest("10/16", ExpiryPrecision.MONTH_DAY, "RIVN", Decimal("18"), "CALL")
    )

    assert result.resolved_expiry == date(2026, 10, 16)
    assert result.validation_status is ContractValidationStatus.VALID
    assert result.resolution_status is ExpiryResolutionStatus.AUTO_RESOLVED


@pytest.mark.asyncio
async def test_auto_nearest_prefers_zero_dte_then_nearest_future() -> None:
    today = date(2026, 8, 30)
    zero_dte = contract("O:SPY260830C00775000", "SPY", today, "775")
    future = contract("O:SPY260901C00775000", "SPY", date(2026, 9, 1), "775")
    request = ExpiryRequest(None, ExpiryPrecision.AUTO_NEAREST, "SPY", Decimal("775"), "CALL")

    with_zero = await OptionContractResolver(
        FakeCatalog((future, zero_dte)), today=today
    ).resolve(request)
    without_zero = await OptionContractResolver(FakeCatalog((future,)), today=today).resolve(
        request
    )

    assert with_zero.resolved_expiry == today
    assert without_zero.resolved_expiry == date(2026, 9, 1)


@pytest.mark.asyncio
async def test_explicit_date_wins_over_zero_dte_default() -> None:
    today = date(2026, 8, 30)
    explicit = contract("O:SPY260904C00775000", "SPY", date(2026, 9, 4), "775")
    resolver = OptionContractResolver(FakeCatalog((explicit,)), today=today)

    result = await resolver.resolve(
        ExpiryRequest(
            "2026-09-04",
            ExpiryPrecision.EXACT_DATE,
            "SPY",
            Decimal("775"),
            "CALL",
        )
    )

    assert result.resolved_expiry == date(2026, 9, 4)
    assert result.resolution_status is ExpiryResolutionStatus.EXPLICIT


@pytest.mark.asyncio
async def test_month_year_single_auto_resolves_and_multiple_requires_manager() -> None:
    first = contract("O:ACHR270108C00007000", "ACHR", date(2027, 1, 8), "7")
    second = contract("O:ACHR270115C00007000", "ACHR", date(2027, 1, 15), "7")
    request = ExpiryRequest("1/2027", ExpiryPrecision.MONTH_YEAR, "ACHR", Decimal("7"), "CALL")

    single = await OptionContractResolver(
        FakeCatalog((second,)), today=date(2026, 8, 30)
    ).resolve(request)
    multiple = await OptionContractResolver(
        FakeCatalog((first, second)), today=date(2026, 8, 30)
    ).resolve(request)

    assert single.resolved_expiry == date(2027, 1, 15)
    assert single.validation_status is ContractValidationStatus.VALID
    assert multiple.resolved_expiry is None
    assert multiple.candidates == (date(2027, 1, 8), date(2027, 1, 15))
    assert multiple.warning == "MULTIPLE_EXPIRATIONS_REQUIRE_MANAGER"


@pytest.mark.asyncio
async def test_invalid_contract_is_not_resolved() -> None:
    resolver = OptionContractResolver(FakeCatalog(()), today=date(2026, 8, 30))

    result = await resolver.validate_exact(
        ticker="SPY",
        expiry=date(2026, 9, 4),
        strike=Decimal("775"),
        option_side="CALL",
    )

    assert result.resolved_expiry is None
    assert result.validation_status is ContractValidationStatus.NOT_FOUND
    assert result.warning == "OPTION_CONTRACT_NOT_FOUND"
