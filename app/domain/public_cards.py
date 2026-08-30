from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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
