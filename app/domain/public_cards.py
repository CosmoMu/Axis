from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PublicTradeCard:
    """Strict whitelist for data that may appear in a member signal card."""

    public_trade_id: str | None
    category: str
    action: str
    action_stage: str | None
    ticker: str | None
    expiry: date | None
    strike: Decimal | None
    option_side: str | None
    entry_low: Decimal | None
    entry_high: Decimal | None
    action_price: Decimal | None
    avg_cost: Decimal | None
    sl: Decimal | None
    tp1: Decimal | None
    tp2: Decimal | None
    position_delta_eighths: int | None
    position_after_eighths: int
    pnl_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class ActivePublicTrade:
    """The complete and intentionally small payload for the Active View."""

    public_trade_id: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    last_public_action: str
    position_eighths: int


@dataclass(frozen=True, slots=True)
class DailyActiveTrade:
    """Member-safe Active row in a post-close category summary."""

    public_trade_id: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    position_eighths: int
    avg_cost: Decimal | None
    reference_price: Decimal | None
    unrealized_pnl_pct: Decimal | None
    quote_time: datetime | None


@dataclass(frozen=True, slots=True)
class DailyClosedTrade:
    """Member-safe Closed row in a post-close category summary."""

    public_trade_id: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    final_return_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class DailyCategorySummary:
    category: str
    session_date: date
    active: tuple[DailyActiveTrade, ...]
    closed: tuple[DailyClosedTrade, ...]


@dataclass(frozen=True, slots=True)
class PublicAnalysisCard:
    analysis_code: str
    analysis_type: str
    symbols: tuple[str, ...]
    sector: str | None
    stance: str
    time_horizon: str
    title: str | None
    summary: str | None
    core_thesis: str | None
    why_now: tuple[str, ...]
    supporting_points: tuple[str, ...]
    engine_observations: tuple[str, ...]
    key_levels: tuple[dict[str, object], ...]
    projection_path: tuple[dict[str, object], ...]
    invalidation: str | None
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    market_conditions: tuple[str, ...]
    related_symbols: tuple[str, ...]
    observed_at: datetime
