"""Typed, provider-independent data for AXIS Stock Analyst."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class DailyBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("daily bar timestamp must be timezone-aware")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("daily bar prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("daily bar high/low must contain open and close")


@dataclass(frozen=True, slots=True)
class PriceLevel:
    price: float
    kind: str
    strength: float
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VolumeProfileNode:
    price_low: float
    price_high: float
    midpoint: float
    volume: float
    volume_share: float
    rank: int


@dataclass(frozen=True, slots=True)
class MoneyFlowProxy:
    score: float
    label: str
    signed_volume_ratio: float
    accumulation_distribution_slope: float
    on_balance_volume_slope: float
    close_location_20: float
    note: str


@dataclass(frozen=True, slots=True)
class StockScenario:
    scenario_id: str
    label_zh: str
    direction: str | None
    model_weight_percent: float
    trigger_zh: str
    targets: tuple[float, ...]
    invalidation: float | None
    rationale_zh: str


@dataclass(frozen=True, slots=True)
class StockAnalysis:
    ticker: str
    as_of: date
    data_timestamp: datetime
    history_sessions: int
    history_mode: str
    current_price: float
    direction: str
    trend_score: float
    trend_label: str
    indicator_scores: tuple[tuple[str, float], ...]
    support_levels: tuple[PriceLevel, ...]
    resistance_levels: tuple[PriceLevel, ...]
    volume_profile_nodes: tuple[VolumeProfileNode, ...]
    point_of_control: float
    value_area_low: float
    value_area_high: float
    money_flow: MoneyFlowProxy
    sector_etf: str
    sector_name_zh: str
    sector_strength_score: float | None
    sector_rotation_phase: str | None
    sector_leader_ticker: str | None
    sector_leader_basis_zh: str
    scenarios: tuple[StockScenario, ...]
    unavailable_data: tuple[str, ...]
    methodology_note: str

    def to_context(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["data_timestamp"] = self.data_timestamp.isoformat()
        payload["indicator_scores"] = dict(self.indicator_scores)
        payload["sector_rotation"] = (
            {
                "strength_score": self.sector_strength_score,
                "rotation_phase": self.sector_rotation_phase,
            }
            if self.sector_strength_score is not None
            else None
        )
        return payload


@dataclass(frozen=True, slots=True)
class StockMarketBundle:
    ticker: str
    bars: tuple[DailyBar, ...]
    sector_etf: str
    sector_bars: tuple[DailyBar, ...] | None
    benchmark_bars: tuple[DailyBar, ...] | None
    peer_bars: Mapping[str, tuple[DailyBar, ...]] | None = None
    sector_candidate_bars: Mapping[str, tuple[DailyBar, ...]] | None = None
    provider: str = "unknown"
    fetched_at: datetime = datetime.min.replace(tzinfo=UTC)
    source_timestamp: datetime = datetime.min.replace(tzinfo=UTC)
    market_status: str = "unknown"
    unavailable_data: tuple[str, ...] = ()
