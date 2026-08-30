from __future__ import annotations

import pytest

from app.db.base import Base
from app.db.models import GuildConfig
from app.db.session import Database
from app.services.input_codes import next_input_code

GUILD_ID = 1543309921066684567


@pytest.mark.asyncio
async def test_signal_and_analysis_codes_increment_independently() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with database.session() as session:
            session.add(GuildConfig(guild_id=GUILD_ID))
            await session.commit()

        async with database.session() as session:
            assert await next_input_code(session, GUILD_ID, "SIGNAL") == "S-00001"
            assert await next_input_code(session, GUILD_ID, "SIGNAL") == "S-00002"
            assert await next_input_code(session, GUILD_ID, "ANALYSIS") == "A-00001"
            await session.commit()

        async with database.session() as session:
            assert await next_input_code(session, GUILD_ID, "ANALYSIS") == "A-00002"
            assert await next_input_code(session, GUILD_ID, "SIGNAL") == "S-00003"
            await session.commit()
    finally:
        await database.dispose()
