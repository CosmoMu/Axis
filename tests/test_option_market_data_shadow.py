from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.integrations.massive_market_data import (
    MarketPrice,
    MarketPriceFailure,
    MarketPriceRequest,
)
from app.integrations.option_market_data_shadow import OptionMarketDataShadowBox


class FakeProvider:
    def __init__(
        self,
        prices: tuple[MarketPrice, ...],
        failures: tuple[MarketPriceFailure, ...] = (),
    ) -> None:
        self.prices = prices
        self.last_failures = failures

    async def fetch_prices(
        self, requests: tuple[MarketPriceRequest, ...]
    ) -> tuple[MarketPrice, ...]:
        return self.prices


def price(key: str, value: str, timestamp: datetime) -> MarketPrice:
    return MarketPrice(
        key=key,
        option_ticker="O:QQQ260904C00717000",
        price=Decimal(value),
        price_source="MID",
        source_timestamp=timestamp,
        received_at=timestamp,
        market_status="open",
    )


@pytest.mark.asyncio
async def test_shadow_box_compares_price_and_timestamp_without_selecting_candidate() -> None:
    now = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    request = MarketPriceRequest("ST-0001", "QQQ", "O:QQQ260904C00717000")
    box = OptionMarketDataShadowBox(
        {
            "MASSIVE": FakeProvider((price(request.key, "0.90", now),)),
            "MOOMOO": FakeProvider(
                (price(request.key, "0.91", now + timedelta(seconds=2)),)
            ),
        },
        primary_provider="MASSIVE",
        candidate_provider="MOOMOO",
    )

    result = (await box.compare((request,)))[0]

    assert result.absolute_price_difference == Decimal("0.01")
    assert result.primary_relative_difference_pct == Decimal("1.111111111111111111111111111")
    assert result.timestamp_difference_seconds == Decimal("2.0")


@pytest.mark.asyncio
async def test_shadow_box_keeps_provider_specific_partial_failure() -> None:
    now = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    request = MarketPriceRequest("ST-0001", "QQQ", "O:QQQ260904C00717000")
    box = OptionMarketDataShadowBox(
        {
            "MASSIVE": FakeProvider(
                (),
                (
                    MarketPriceFailure(
                        request.key,
                        request.option_ticker,
                        "MASSIVE_QUOTE_STALE",
                    ),
                ),
            ),
            "MOOMOO": FakeProvider((price(request.key, "0.91", now),)),
        },
        primary_provider="MASSIVE",
        candidate_provider="MOOMOO",
    )

    result = (await box.compare((request,)))[0]
    observations = {item.provider: item for item in result.observations}

    assert observations["MASSIVE"].error_code == "MASSIVE_QUOTE_STALE"
    assert observations["MOOMOO"].price == Decimal("0.91")
    assert result.absolute_price_difference is None
