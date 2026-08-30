from datetime import date
from decimal import Decimal

import pytest

from app.integrations.moomoo_market_data import (
    MarketDataError,
    MoomooMarketDataClient,
    OptionQuoteRequest,
    _quote_time,
    normalize_us_underlying,
)


class FakeRow(dict[str, object]):
    pass


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def iterrows(self):  # type: ignore[no-untyped-def]
        for index, row in enumerate(self.rows):
            yield index, FakeRow(row)


class FakeContext:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def get_option_chain(self, *args: object, **kwargs: object) -> tuple[int, FakeFrame]:
        return 0, FakeFrame(self.rows)


def request() -> OptionQuoteRequest:
    return OptionQuoteRequest(
        key="trade-1",
        ticker="$aapl",
        expiry=date(2026, 9, 18),
        strike=Decimal("200"),
        option_side="CALL",
    )


def test_us_underlying_normalization_is_strict() -> None:
    assert normalize_us_underlying("$aapl") == "US.AAPL"
    assert normalize_us_underlying("US.SPY") == "US.SPY"
    with pytest.raises(MarketDataError, match="ONLY_US_OPTIONS_SUPPORTED"):
        normalize_us_underlying("HK.00700")


def test_moomoo_snapshot_time_accepts_fractional_seconds() -> None:
    parsed = _quote_time("2026-08-28 20:02:33.982")
    assert parsed is not None
    assert parsed.isoformat() == "2026-08-28T20:02:33.982000-04:00"


def test_option_contract_is_resolved_from_exact_chain_match() -> None:
    context = FakeContext(
        [
            {
                "code": "US.AAPL260918C200000",
                "strike_time": "2026-09-18",
                "strike_price": 200.0,
                "option_type": "CALL",
            },
            {
                "code": "US.AAPL260918P200000",
                "strike_time": "2026-09-18",
                "strike_price": 200.0,
                "option_type": "PUT",
            },
        ]
    )
    code = MoomooMarketDataClient._resolve_option_code(
        context,
        request(),
        option_type="CALL",
        ret_ok=0,
    )
    assert code == "US.AAPL260918C200000"


def test_option_contract_resolution_rejects_missing_or_ambiguous_matches() -> None:
    with pytest.raises(MarketDataError, match="OPTION_CONTRACT_NOT_FOUND"):
        MoomooMarketDataClient._resolve_option_code(
            FakeContext([]), request(), option_type="CALL", ret_ok=0
        )

    duplicate = {
        "strike_time": "2026-09-18",
        "strike_price": 200,
        "option_type": "CALL",
    }
    with pytest.raises(MarketDataError, match="OPTION_CONTRACT_AMBIGUOUS"):
        MoomooMarketDataClient._resolve_option_code(
            FakeContext(
                [
                    {**duplicate, "code": "US.ONE"},
                    {**duplicate, "code": "US.TWO"},
                ]
            ),
            request(),
            option_type="CALL",
            ret_ok=0,
        )
