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
    current_stock: Decimal | None = None
    starter: Decimal | None = None
    add_zone_low: Decimal | None = None
    add_zone_high: Decimal | None = None
    stock_sl: Decimal | None = None
    stock_pt1: Decimal | None = None
    stock_pt2: Decimal | None = None
    stock_pt3: Decimal | None = None
    fib_0618: Decimal | None = None
    public_thesis: str | None = None


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
    avg_cost: Decimal | None


@dataclass(frozen=True, slots=True)
class ShortTermEntryCard:
    """Public Short-Term entry boundary; intentionally excludes all Mentor fields."""

    public_trade_id: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    entry_price: Decimal


@dataclass(frozen=True, slots=True)
class ShortTermTrackingCard:
    """Public TP, RUNNER, or tracking-stop boundary."""

    public_trade_id: str
    card_type: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    price: Decimal
    return_pct: Decimal
    highest_return_pct: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ShortTermActiveTrade:
    public_trade_id: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    current_price: Decimal | None
    current_return_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class ShortTermDailyRow:
    public_trade_id: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    current_return_pct: Decimal | None
    tracking_end_return_pct: Decimal | None
    highest_return_pct: Decimal
    lowest_return_pct: Decimal


@dataclass(frozen=True, slots=True)
class ShortTermDailySummary:
    category: str
    session_date: date
    active: tuple[ShortTermDailyRow, ...]
    ended: tuple[ShortTermDailyRow, ...]


@dataclass(frozen=True, slots=True)
class DailyResultRow:
    public_trade_id: str
    ticker: str
    strike: Decimal
    option_side: str
    tracking_end_return_pct: Decimal | None = None
    maximum_return_pct: Decimal | None = None
    maximum_drawdown_pct: Decimal | None = None
    mentor_final_return_pct: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DailyResultsCard:
    session_date: date
    short_term: tuple[DailyResultRow, ...]
    swing: tuple[DailyResultRow, ...]
    leaps: tuple[DailyResultRow, ...]


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
    title: str | None
    summary: str | None
    core_thesis: str | None
    key_levels: tuple[dict[str, object], ...]
    indicators: tuple[dict[str, object], ...]
    market_profile: dict[str, object]
    top_scenario: dict[str, object] | None
    prediction_path: tuple[dict[str, object], ...]
    invalidation: str | None
    risks: tuple[str, ...]
    market_conditions: tuple[str, ...]
    methodology_notice: str | None
    market_as_of: str | None
    observed_at: datetime
