from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.db.models import GuildConfig, SystemAlert
from app.db.session import Database
from app.services.system_alerts import SystemAlertService

GUILD_ID = 1543309921066684567


@pytest.mark.asyncio
async def test_system_alert_deduplicates_and_sends_one_recovery() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = SystemAlertService(database)
    try:
        async with database.session() as session:
            session.add(GuildConfig(guild_id=GUILD_ID))
            await session.commit()
        first = await service.report_failure(
            GUILD_ID,
            severity="ERROR",
            service="OpenAI API",
            error_type="TIMEOUT",
            affected="Signal Parsing",
            detail="Request timeout after 45 seconds",
        )
        await service.mark_notified(first.alert.id)
        repeated = await service.report_failure(
            GUILD_ID,
            severity="ERROR",
            service="OpenAI API",
            error_type="TIMEOUT",
            affected="Signal Parsing",
        )
        recovery = await service.report_recovery(
            GUILD_ID,
            service="OpenAI API",
            error_type="TIMEOUT",
            affected="Signal Parsing",
        )
        duplicate_recovery = await service.report_recovery(
            GUILD_ID,
            service="OpenAI API",
            error_type="TIMEOUT",
            affected="Signal Parsing",
        )

        assert first.action == "ALERT"
        assert repeated.action == "SUPPRESSED"
        assert repeated.alert.occurrence_count == 2
        assert recovery is not None and recovery.action == "RECOVERY"
        assert duplicate_recovery is None
        async with database.session() as session:
            row = await session.scalar(select(SystemAlert))
        assert row is not None
        assert row.first_seen <= row.last_seen <= row.resolved_at
        assert row.occurrence_count == 2

        restarted = await service.report_failure(
            GUILD_ID,
            severity="WARNING",
            service="OpenAI API",
            error_type="TIMEOUT",
            affected="Signal Parsing",
        )
        assert restarted.action == "ALERT"
        assert restarted.alert.occurrence_count == 1
        assert restarted.alert.resolved_at is None
    finally:
        await database.dispose()
