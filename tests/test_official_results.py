from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.bot.cards import build_official_result_embed
from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, Mentor, Trade, TradeEvent
from app.db.session import Database
from app.domain.enums import TradeState
from app.services.official_results import OfficialResultsService

GUILD_ID = 1543309921066684567


@pytest.mark.asyncio
async def test_weighted_result_and_idempotent_official_publication() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = OfficialResultsService(database)
    try:
        async with database.session() as session:
            session.add(GuildConfig(guild_id=GUILD_ID, results_channel_id=501))
            mentor = Mentor(guild_id=GUILD_ID, name="Private Mentor", short_code="PM")
            session.add(mentor)
            await session.flush()
            trade = Trade(
                guild_id=GUILD_ID,
                public_trade_id="SW-0001",
                category="SWING",
                mentor_id=mentor.id,
                ticker="TSLA",
                expiry=date(2026, 9, 18),
                strike=Decimal("400"),
                option_side="CALL",
                state=TradeState.CLOSED.value,
                position_eighths=0,
                max_position_eighths=2,
                opened_at=datetime.now(UTC),
                closed_at=datetime.now(UTC),
            )
            session.add(trade)
            await session.flush()
            for action, price, delta, after in (
                ("ENTRY", "2", 1, 1),
                ("ADD", "1", 1, 2),
                ("TP1", "3", -1, 1),
                ("CLOSE", "4", -1, 0),
            ):
                session.add(
                    TradeEvent(
                        trade_id=trade.id,
                        action=action,
                        action_stage="FIRST" if action == "ADD" else "NONE",
                        price=Decimal(price),
                        position_delta_eighths=delta,
                        position_after_eighths=after,
                        approved_by=101,
                    )
                )
            await session.commit()

        result = await service.calculate(trade.id)
        assert result.entry_cost == Decimal("3")
        assert result.exit_value == Decimal("7")
        assert result.final_return_pct == Decimal("133.3333333333333333333333333")
        public_text = str(build_official_result_embed(result).to_dict())
        assert "Private Mentor" not in public_text
        assert "加权最终收益" in public_text

        first = await service.attach_message(
            trade.id,
            message_id=601,
            final_return_pct=result.final_return_pct,
            actor_user_id=999,
        )
        repeated = await service.attach_message(
            trade.id,
            message_id=602,
            final_return_pct=result.final_return_pct,
            actor_user_id=999,
        )
        assert first.message_id == repeated.message_id == 601
        assert await service.next_unpublished(GUILD_ID) is None
        async with database.session() as session:
            stored = await session.get(Trade, trade.id)
            audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
        assert stored is not None and stored.result_message_id == 601
        assert stored.final_return_pct == result.final_return_pct.quantize(Decimal("0.0001"))
        assert audit_count == 1
    finally:
        await database.dispose()
