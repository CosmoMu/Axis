from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.integrations.massive_close_data import MassiveClosingPriceClient
from app.integrations.moomoo_market_data import MarketDataError

SESSION_DATE = date(2026, 8, 31)
TIMESTAMP_MS = int(datetime(2026, 8, 31, 4, 0, tzinfo=UTC).timestamp() * 1000)


def test_massive_daily_bar_normalizes_official_option_close() -> None:
    quote = MassiveClosingPriceClient._normalize(
        "trade-1",
        "O:AAPL260918C00200000",
        SESSION_DATE,
        {"results": [{"c": 1.75, "t": TIMESTAMP_MS}]},
    )

    assert quote.last_price == Decimal("1.75")
    assert quote.price_type == "CLOSE"
    assert quote.instrument_code == "O:AAPL260918C00200000"
    assert quote.error_code is None


def test_massive_daily_bar_does_not_substitute_another_session() -> None:
    quote = MassiveClosingPriceClient._normalize(
        "trade-1",
        "O:AAPL260918C00200000",
        SESSION_DATE,
        {"results": [{"c": 1.75, "t": TIMESTAMP_MS - 86_400_000}]},
    )

    assert quote.last_price is None
    assert quote.error_code == "CLOSE_UNAVAILABLE"
    assert quote.price_type == "CLOSE"


def test_massive_daily_bar_rejects_malformed_payload() -> None:
    with pytest.raises(MarketDataError, match="MASSIVE_CLOSE_RESPONSE_INVALID"):
        MassiveClosingPriceClient._normalize(
            "trade-1",
            "O:AAPL260918C00200000",
            SESSION_DATE,
            {"results": None},
        )
