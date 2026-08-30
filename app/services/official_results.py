from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.models import AuditLog, GuildConfig, Trade, TradeEvent, utc_now
from app.db.session import Database
from app.domain.enums import TradeCategory, TradeState


class ResultsError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OfficialResult:
    trade_id: uuid.UUID
    guild_id: int
    public_trade_id: str
    ticker: str
    expiry: date
    strike: Decimal
    option_side: str
    entry_cost: Decimal
    exit_value: Decimal
    final_return_pct: Decimal
    channel_id: int
    message_id: int | None


class OfficialResultsService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def next_unpublished(self, guild_id: int) -> uuid.UUID | None:
        async with self.database.session() as session:
            return await session.scalar(
                select(Trade.id)
                .where(
                    Trade.guild_id == guild_id,
                    Trade.category != TradeCategory.SHORT_TERM.value,
                    Trade.state == TradeState.CLOSED.value,
                    Trade.result_message_id.is_(None),
                )
                .order_by(Trade.closed_at, Trade.id)
                .limit(1)
            )

    async def calculate(self, trade_id: uuid.UUID) -> OfficialResult:
        async with self.database.session() as session:
            trade = await session.get(Trade, trade_id)
            if (
                trade is None
                or trade.category == TradeCategory.SHORT_TERM.value
                or trade.state != TradeState.CLOSED.value
            ):
                raise ResultsError("CLOSED_TRADE_NOT_FOUND")
            config = await session.get(GuildConfig, trade.guild_id)
            if config is None or config.results_channel_id is None:
                raise ResultsError("RESULTS_CHANNEL_NOT_CONFIGURED")
            events = (
                await session.scalars(
                    select(TradeEvent)
                    .where(TradeEvent.trade_id == trade.id)
                    .order_by(TradeEvent.created_at, TradeEvent.id)
                )
            ).all()
            entry_cost = Decimal("0")
            exit_value = Decimal("0")
            net_units = 0
            for event in events:
                delta = event.position_delta_eighths
                net_units += delta
                if delta == 0:
                    continue
                if event.price is None:
                    raise ResultsError("EVENT_PRICE_MISSING")
                if delta > 0:
                    entry_cost += event.price * delta
                else:
                    exit_value += event.price * abs(delta)
            if entry_cost <= 0:
                raise ResultsError("ENTRY_COST_INVALID")
            if net_units != 0:
                raise ResultsError("POSITION_HISTORY_INCOMPLETE")
            final_return = ((exit_value - entry_cost) / entry_cost) * Decimal("100")
            return OfficialResult(
                trade_id=trade.id,
                guild_id=trade.guild_id,
                public_trade_id=trade.public_trade_id,
                ticker=trade.ticker,
                expiry=trade.expiry,
                strike=trade.strike,
                option_side=trade.option_side,
                entry_cost=entry_cost,
                exit_value=exit_value,
                final_return_pct=final_return,
                channel_id=config.results_channel_id,
                message_id=trade.result_message_id,
            )

    async def attach_message(
        self,
        trade_id: uuid.UUID,
        *,
        message_id: int,
        final_return_pct: Decimal,
        actor_user_id: int,
    ) -> OfficialResult:
        async with self.database.session() as session:
            trade = await session.scalar(
                select(Trade).where(Trade.id == trade_id).with_for_update()
            )
            if trade is None or trade.state != TradeState.CLOSED.value:
                raise ResultsError("CLOSED_TRADE_NOT_FOUND")
            if trade.result_message_id is None:
                trade.result_message_id = message_id
                trade.final_return_pct = final_return_pct
                trade.result_published_at = utc_now()
                trade.version += 1
                session.add(
                    AuditLog(
                        guild_id=trade.guild_id,
                        actor_user_id=actor_user_id,
                        action_type="OFFICIAL_RESULT_PUBLISHED",
                        entity_type="trade",
                        entity_id=str(trade.id),
                        before_json=None,
                        after_json={
                            "message_id": message_id,
                            "final_return_pct": str(final_return_pct),
                        },
                        discord_interaction_id=None,
                    )
                )
                await session.commit()
        return await self.calculate(trade_id)
