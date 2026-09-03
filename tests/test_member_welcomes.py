from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.bot.cogs.manager_control import ManagerControlCog
from app.db.base import Base
from app.db.models import AuditLog, GuildConfig
from app.db.session import Database

GUILD_ID = 1543309921066684567
USER_ID = 900000000000000001


class FakeMember:
    def __init__(self) -> None:
        self.roles: list[object] = []

    async def add_roles(self, role: object, *, reason: str) -> None:
        self.roles.append(role)

    async def remove_roles(self, role: object, *, reason: str) -> None:
        self.roles.remove(role)


class FakeChannel:
    def __init__(self) -> None:
        self.messages: list[tuple[str, object]] = []

    async def send(self, content: str, *, allowed_mentions: object) -> object:
        self.messages.append((content, allowed_mentions))
        return SimpleNamespace(id=701)


@pytest.mark.asyncio
async def test_member_role_activation_sends_one_premium_lounge_welcome() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        await session.commit()

    role = SimpleNamespace(id=55)
    member = FakeMember()
    channel = FakeChannel()
    guild = SimpleNamespace(
        get_role=lambda role_id: role if role_id == 55 else None,
        get_member=lambda user_id: member if user_id == USER_ID else None,
    )
    bot = SimpleNamespace(
        user=SimpleNamespace(id=99),
        get_guild=lambda guild_id: guild if guild_id == GUILD_ID else None,
        get_channel=lambda channel_id: channel if channel_id == 77 else None,
    )
    controller = object.__new__(ManagerControlCog)
    controller.bot = bot
    controller.guild_id = GUILD_ID
    controller.owner_user_id = None
    controller.member_role_id = 55
    controller.member_lounge_channel_id = 77
    controller.short_term_channel_id = 201
    controller.swing_channel_id = 202
    controller.leaps_channel_id = 203
    controller.membership_service = SimpleNamespace(database=database)
    controller._role_expectations = {}

    try:
        await controller.sync_member_role(USER_ID, True)
        await controller.sync_member_role(USER_ID, True)

        assert role in member.roles
        assert len(channel.messages) == 1
        assert f"<@{USER_ID}>" in channel.messages[0][0]
        assert "保持独立判断" in channel.messages[0][0]
        assert "尊重风险，尊重市场" in channel.messages[0][0]
        assert "<#201>" in channel.messages[0][0]
        assert "<#202>" in channel.messages[0][0]
        assert "<#203>" in channel.messages[0][0]
        async with database.session() as session:
            audits = list(await session.scalars(select(AuditLog)))
        assert [item.action_type for item in audits] == ["MEMBER_ROLE_ADDED"]
    finally:
        await database.dispose()
