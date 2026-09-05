"""Read-only Massive/Moomoo one-minute comparison for the GEX black box."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.integrations.gex_intraday_data import (
    GexIntradayDataProvider,
    GexIntradayResult,
)


@dataclass(frozen=True, slots=True)
class GexIntradayShadowComparison:
    ticker: str
    primary_provider: str
    candidate_provider: str
    primary_bar_count: int
    candidate_bar_count: int
    overlapping_bar_count: int
    compared_at: datetime
    common_timestamp: datetime | None
    close_absolute_difference: float | None
    close_relative_difference_pct: float | None
    source_timestamp_difference_seconds: float | None
    candidate_error_code: str | None


class GexIntradayShadowBox:
    """Compares a candidate feed without allowing it to select production candles."""

    def __init__(self, candidate_provider: GexIntradayDataProvider) -> None:
        self.candidate_provider = candidate_provider

    async def compare(
        self,
        *,
        ticker: str,
        bar_count: int,
        primary: GexIntradayResult,
        compared_at: datetime,
    ) -> GexIntradayShadowComparison:
        try:
            candidate = await self.candidate_provider.fetch(ticker, bar_count=bar_count)
        except Exception as exc:
            return GexIntradayShadowComparison(
                ticker=ticker,
                primary_provider=primary.provider,
                candidate_provider=self.candidate_provider.name,
                primary_bar_count=len(primary.bars),
                candidate_bar_count=0,
                overlapping_bar_count=0,
                compared_at=compared_at,
                common_timestamp=None,
                close_absolute_difference=None,
                close_relative_difference_pct=None,
                source_timestamp_difference_seconds=None,
                candidate_error_code=str(getattr(exc, "code", type(exc).__name__)),
            )

        primary_by_time = {bar.timestamp_et: bar for bar in primary.bars}
        candidate_by_time = {bar.timestamp_et: bar for bar in candidate.bars}
        common = sorted(primary_by_time.keys() & candidate_by_time.keys())
        common_timestamp = common[-1] if common else None
        absolute_difference = None
        relative_difference = None
        if common_timestamp is not None:
            primary_close = primary_by_time[common_timestamp].close
            candidate_close = candidate_by_time[common_timestamp].close
            absolute_difference = abs(candidate_close - primary_close)
            if primary_close > 0:
                relative_difference = absolute_difference / primary_close * 100
        return GexIntradayShadowComparison(
            ticker=ticker,
            primary_provider=primary.provider,
            candidate_provider=candidate.provider,
            primary_bar_count=len(primary.bars),
            candidate_bar_count=len(candidate.bars),
            overlapping_bar_count=len(common),
            compared_at=compared_at,
            common_timestamp=common_timestamp,
            close_absolute_difference=absolute_difference,
            close_relative_difference_pct=relative_difference,
            source_timestamp_difference_seconds=abs(
                (candidate.source_timestamp - primary.source_timestamp).total_seconds()
            ),
            candidate_error_code=None,
        )
