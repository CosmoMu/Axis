from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.bootstrap import seed_guild_config
from app.db.models import GuildConfig, Mentor, Trade
from app.db.session import Database
from app.domain.enums import OptionSide, TradeCategory, TradeState

EXPECTED_TABLES = {
    "guild_config",
    "mentors",
    "mentor_aliases",
    "source_messages",
    "source_attachments",
    "trade_drafts",
    "trades",
    "trade_events",
    "public_messages",
    "memberships",
    "membership_events",
    "subscriptions",
    "audit_logs",
    "scheduled_jobs",
}


def discord_ids() -> dict[str, object]:
    return {
        "guild_id": 1543309921066684567,
        "roles": {"manager": 101, "member": 102},
        "channels": {
            "official_results": 201,
            "short_term_alerts": 202,
            "swing_alerts": 203,
            "leaps_alerts": 204,
            "mentor_control": 205,
            "member_control": 206,
        },
    }


def test_metadata_contains_the_complete_mvp_schema() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    trades = Base.metadata.tables["trades"]
    assert {"position_eighths", "max_position_eighths", "version"} <= set(trades.columns.keys())
    assert "mentor_panel_message_id" in Base.metadata.tables["guild_config"].columns
    assert "member_panel_message_id" in Base.metadata.tables["guild_config"].columns


@pytest.mark.asyncio
async def test_database_seed_is_idempotent_and_position_constraint_is_enforced() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with database.session() as session:
            first = await seed_guild_config(
                session,
                guild_id=1543309921066684567,
                discord_ids=discord_ids(),
            )
            second = await seed_guild_config(
                session,
                guild_id=1543309921066684567,
                discord_ids=discord_ids(),
            )
            assert first is second
            await session.commit()

        async with database.session() as session:
            config = await session.get(GuildConfig, 1543309921066684567)
            assert config is not None
            assert config.short_term_channel_id == 202
            mentor = Mentor(
                guild_id=config.guild_id,
                name="Test Mentor",
                short_code="TEST",
            )
            session.add(mentor)
            await session.flush()
            session.add(
                Trade(
                    guild_id=config.guild_id,
                    public_trade_id="ST-0001",
                    category=TradeCategory.SHORT_TERM.value,
                    mentor_id=mentor.id,
                    ticker="AXIS",
                    expiry=date(2027, 1, 15),
                    strike=Decimal("100"),
                    option_side=OptionSide.CALL.value,
                    state=TradeState.ACTIVE.value,
                    position_eighths=1,
                    max_position_eighths=1,
                    opened_at=datetime.now(UTC),
                )
            )
            await session.commit()

        async with database.session() as session:
            mentor = Mentor(
                guild_id=1543309921066684567,
                name="Invalid Position Mentor",
                short_code="BADPOS",
            )
            session.add(mentor)
            await session.flush()
            session.add(
                Trade(
                    guild_id=1543309921066684567,
                    public_trade_id="ST-0002",
                    category=TradeCategory.SHORT_TERM.value,
                    mentor_id=mentor.id,
                    ticker="AXIS",
                    expiry=date(2027, 1, 15),
                    strike=Decimal("100"),
                    option_side=OptionSide.CALL.value,
                    state=TradeState.ACTIVE.value,
                    position_eighths=9,
                    max_position_eighths=9,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await database.dispose()
