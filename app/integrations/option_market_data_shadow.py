from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.integrations.massive_market_data import (
    MarketDataProvider,
    MarketPrice,
    MarketPriceRequest,
)


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    provider: str
    price: Decimal | None
    price_source: str | None
    source_timestamp: datetime | None
    market_status: str | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class OptionMarketComparison:
    key: str
    option_ticker: str
    observations: tuple[ProviderObservation, ...]
    absolute_price_difference: Decimal | None
    primary_relative_difference_pct: Decimal | None
    timestamp_difference_seconds: Decimal | None


class OptionMarketDataShadowBox:
    """Runs identical option requests against providers without selecting production data."""

    def __init__(
        self,
        providers: Mapping[str, MarketDataProvider],
        *,
        primary_provider: str,
        candidate_provider: str,
    ) -> None:
        normalized = {name.strip().upper(): provider for name, provider in providers.items()}
        primary = primary_provider.strip().upper()
        candidate = candidate_provider.strip().upper()
        if primary not in normalized or candidate not in normalized or primary == candidate:
            raise ValueError("SHADOW_PROVIDER_CONFIG_INVALID")
        self.providers = normalized
        self.primary_provider = primary
        self.candidate_provider = candidate

    async def compare(
        self, requests: Sequence[MarketPriceRequest]
    ) -> tuple[OptionMarketComparison, ...]:
        request_tuple = tuple(requests)
        results = await asyncio.gather(
            *(provider.fetch_prices(request_tuple) for provider in self.providers.values()),
            return_exceptions=True,
        )
        observations: dict[str, dict[str, ProviderObservation]] = {
            request.key: {} for request in request_tuple
        }
        for (provider_name, provider), result in zip(
            self.providers.items(), results, strict=True
        ):
            prices = () if isinstance(result, BaseException) else result
            price_by_key = {price.key: price for price in prices}
            failure_by_key = {
                failure.key: failure.error_code
                for failure in getattr(provider, "last_failures", ())
            }
            provider_error = (
                str(getattr(result, "code", type(result).__name__))
                if isinstance(result, BaseException)
                else None
            )
            for request in request_tuple:
                price = price_by_key.get(request.key)
                observations[request.key][provider_name] = self._observation(
                    provider_name,
                    price,
                    failure_by_key.get(request.key) or (provider_error if price is None else None),
                )

        comparisons = []
        for request in request_tuple:
            by_provider = observations[request.key]
            primary = by_provider[self.primary_provider]
            candidate = by_provider[self.candidate_provider]
            absolute_difference = None
            relative_difference = None
            timestamp_difference = None
            if primary.price is not None and candidate.price is not None:
                absolute_difference = abs(candidate.price - primary.price)
                if primary.price > 0:
                    relative_difference = (
                        absolute_difference / primary.price * Decimal("100")
                    )
            if primary.source_timestamp is not None and candidate.source_timestamp is not None:
                timestamp_difference = Decimal(
                    str(
                        abs(
                            (
                                candidate.source_timestamp
                                - primary.source_timestamp
                            ).total_seconds()
                        )
                    )
                )
            comparisons.append(
                OptionMarketComparison(
                    key=request.key,
                    option_ticker=request.option_ticker,
                    observations=tuple(by_provider.values()),
                    absolute_price_difference=absolute_difference,
                    primary_relative_difference_pct=relative_difference,
                    timestamp_difference_seconds=timestamp_difference,
                )
            )
        return tuple(comparisons)

    @staticmethod
    def _observation(
        provider: str,
        price: MarketPrice | None,
        error_code: str | None,
    ) -> ProviderObservation:
        return ProviderObservation(
            provider=provider,
            price=price.price if price is not None else None,
            price_source=price.price_source if price is not None else None,
            source_timestamp=price.source_timestamp if price is not None else None,
            market_status=price.market_status if price is not None else None,
            error_code=error_code,
        )
