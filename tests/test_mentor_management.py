from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, Trade
from app.db.session import Database
from app.domain.enums import TradeState
from app.services.mentor_management import MentorManagementService

GUILD_ID = 1543309921066684567


@pytest.mark.asyncio
async def test_mentor_registry_create_edit_toggle_and_trade_reassignment() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = MentorManagementService(database)
    try:
        async with database.session() as session:
            session.add(GuildConfig(guild_id=GUILD_ID))
            await session.commit()
        first = await service.create(
            GUILD_ID,
            name="Vincent",
            short_code="vin",
            aliases=["V", "  Vincent  ", "V"],
            actor_user_id=101,
            interaction_id=201,
        )
        second = await service.create(
            GUILD_ID,
            name="Cosmo",
            short_code="COS",
            aliases=[],
            actor_user_id=101,
            interaction_id=202,
        )
        assert first.short_code == "VIN"
        assert first.aliases == ("V", "Vincent")

        edited = await service.edit(
            first.id,
            name="Vincent X",
            short_code="VX",
            aliases=["Vince"],
            actor_user_id=101,
            interaction_id=203,
        )
        assert edited.name == "Vincent X"
        assert edited.aliases == ("Vince",)
        inactive = await service.set_active(
            first.id,
            is_active=False,
            actor_user_id=101,
            interaction_id=204,
        )
        restored = await service.set_active(
            first.id,
            is_active=True,
            actor_user_id=101,
            interaction_id=205,
        )
        assert inactive.is_active is False
        assert restored.is_active is True

        async with database.session() as session:
            trade = Trade(
                guild_id=GUILD_ID,
                public_trade_id="ST-0001",
                category="SHORT_TERM",
                mentor_id=first.id,
                ticker="TSLA",
                expiry=date(2026, 9, 18),
                strike=Decimal("400"),
                option_side="CALL",
                state=TradeState.ACTIVE.value,
                position_eighths=1,
                max_position_eighths=1,
            )
            session.add(trade)
            await session.commit()
        target = await service.reassign_trade(
            trade.id,
            mentor_id=second.id,
            actor_user_id=101,
            interaction_id=206,
        )
        assert [item.public_trade_id for item in target.active_trades] == ["ST-0001"]
        async with database.session() as session:
            stored_trade = await session.get(Trade, trade.id)
            actions = (
                await session.scalars(
                    select(AuditLog.action_type).order_by(AuditLog.created_at, AuditLog.id)
                )
            ).all()
        assert stored_trade is not None and stored_trade.mentor_id == second.id
        assert actions == [
            "MENTOR_CREATED",
            "MENTOR_CREATED",
            "MENTOR_EDITED",
            "MENTOR_DEACTIVATED",
            "MENTOR_REACTIVATED",
            "TRADE_MENTOR_REASSIGNED",
        ]
    finally:
        await database.dispose()
