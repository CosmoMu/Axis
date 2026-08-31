#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import ssl
import sys
from pathlib import Path

import aiohttp
import certifi
import discord
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from app.config import Settings  # noqa: E402
from app.db.bootstrap import load_discord_ids  # noqa: E402
from app.db.models import GuildConfig  # noqa: E402
from app.db.session import Database  # noqa: E402

GUIDE_TITLES = {
    "welcome": ("welcome_message_id", "WELCOME TO AXIS"),
    "subscriptions": ("subscription_message_id", "AXIS MEMBERSHIP"),
    "official_results": ("results_guide_message_id", "AXIS RESULTS"),
    "member_wins": ("member_wins_guide_message_id", "COMMUNITY WINS"),
    "short_term_alerts": ("short_term_notice_message_id", "RISK NOTICE"),
}
TEST_COMMANDS = {
    "test-signal-card",
    "test-analysis-card",
    "test-entry-card",
    "test-add-card",
    "test-tp-card",
    "test-runner-card",
    "test-close-card",
    "test-general-card",
    "test-payment-ui",
    "test-short-entry",
    "test-short-tp",
    "test-short-stop",
    "test-results-review",
}
REMOVED_COMMANDS = {"test-short-runner", "test-short-daily"}


def _check(condition: bool, label: str, failures: list[str]) -> None:
    if not condition:
        failures.append(label)


async def verify() -> list[str]:
    settings = Settings.load(PROJECT_ROOT)
    discord_ids = load_discord_ids(settings.ids_path, settings.discord_guild_id)
    roles = discord_ids["roles"]
    channel_ids = discord_ids["channels"]
    failures: list[str] = []

    database = Database(settings.require_database_url())
    try:
        async with database.session() as session:
            config = await session.scalar(
                select(GuildConfig).where(GuildConfig.guild_id == settings.discord_guild_id)
            )
    finally:
        await database.dispose()
    _check(config is not None, "guild_config_missing", failures)

    intents = discord.Intents.none()
    intents.guilds = True
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    client = discord.Client(
        intents=intents,
        connector=aiohttp.TCPConnector(ssl=ssl_context),
    )
    connect_task = None
    try:
        await client.login(settings.require_token())
        connect_task = asyncio.create_task(client.connect(reconnect=False))
        await client.wait_until_ready()
        guild = client.get_guild(settings.discord_guild_id)
        _check(guild is not None, "guild_missing", failures)
        if guild is None:
            return failures
        everyone = guild.default_role
        member = guild.get_role(roles["member"])
        manager = guild.get_role(roles["manager"])
        bot_member = guild.me
        owner = guild.get_member(settings.discord_owner_user_id or guild.owner_id)
        if owner is None:
            owner = await guild.fetch_member(settings.discord_owner_user_id or guild.owner_id)
        _check(member is not None, "member_role_missing", failures)
        _check(manager is not None, "manager_role_missing", failures)
        _check(bot_member is not None, "bot_member_missing", failures)
        if member is None or manager is None or bot_member is None:
            return failures

        def channel(key: str) -> discord.TextChannel:
            resolved = guild.get_channel(channel_ids[key])
            if not isinstance(resolved, discord.TextChannel):
                raise RuntimeError(f"channel_missing:{key}")
            return resolved

        welcome = channel("welcome")
        lobby = channel("lobby")
        member_wins = channel("member_wins")
        member_lounge = channel("member_chat")
        short_term = channel("short_term_alerts")
        system_alerts = channel("system_alerts")
        card_testing = channel("card_testing")
        results_review = channel("results_review")
        mentor_control = channel("mentor_control")

        _check(welcome.permissions_for(everyone).view_channel, "public_welcome_view", failures)
        _check(not welcome.permissions_for(everyone).send_messages, "public_welcome_send", failures)
        _check(lobby.permissions_for(everyone).send_messages, "public_lobby_send", failures)
        _check(member_wins.permissions_for(everyone).view_channel, "public_wins_view", failures)
        _check(
            not member_wins.permissions_for(everyone).send_messages,
            "public_wins_send",
            failures,
        )
        _check(member_wins.permissions_for(member).send_messages, "member_wins_send", failures)
        _check(member_wins.permissions_for(member).attach_files, "member_wins_attach", failures)
        _check(member_lounge.permissions_for(member).view_channel, "member_lounge_view", failures)
        _check(short_term.permissions_for(member).view_channel, "member_signal_view", failures)
        _check(not short_term.permissions_for(member).send_messages, "member_signal_send", failures)
        _check(
            short_term.permissions_for(bot_member).pin_messages,
            "bot_short_term_pin",
            failures,
        )
        for key, owner_only in (
            ("system_alerts", system_alerts),
            ("card_testing", card_testing),
        ):
            manager_permissions = owner_only.permissions_for(manager)
            _check(not manager_permissions.view_channel, f"manager_{key}_view", failures)
            owner_overwrite = owner_only.overwrites_for(owner)
            _check(owner_overwrite.view_channel is True, f"owner_{key}_view", failures)
            _check(owner_overwrite.send_messages is True, f"owner_{key}_send", failures)
            _check(
                owner_overwrite.use_application_commands is True,
                f"owner_{key}_interact",
                failures,
            )
            bot_permissions = owner_only.permissions_for(bot_member)
            _check(bot_permissions.view_channel, f"bot_{key}_view", failures)
            _check(bot_permissions.send_messages, f"bot_{key}_send", failures)
            _check(bot_permissions.manage_messages, f"bot_{key}_manage", failures)
        _check(
            not results_review.permissions_for(everyone).view_channel,
            "everyone_results_review_view",
            failures,
        )
        _check(
            not results_review.permissions_for(member).view_channel,
            "member_results_review_view",
            failures,
        )
        manager_results = results_review.permissions_for(manager)
        _check(manager_results.view_channel, "manager_results_review_view", failures)
        _check(not manager_results.send_messages, "manager_results_review_send", failures)
        _check(
            manager_results.use_application_commands,
            "manager_results_review_interact",
            failures,
        )
        _check(
            results_review.permissions_for(bot_member).send_messages,
            "bot_results_review_send",
            failures,
        )

        if config is not None:
            for channel_key, (field_name, title) in GUIDE_TITLES.items():
                guide_channel = channel(channel_key)
                saved_id = getattr(config, field_name)
                _check(saved_id is not None, f"{field_name}_missing", failures)
                matching = []
                async for message in guide_channel.history(limit=100):
                    if any(embed.title == title for embed in message.embeds):
                        matching.append(message)
                _check(len(matching) == 1, f"{channel_key}_guide_count", failures)
                if matching and saved_id is not None:
                    _check(matching[0].id == saved_id, f"{field_name}_mismatch", failures)
                if channel_key == "welcome" and matching:
                    payload = str(matching[0].embeds[0].to_dict())
                    _check("NO ACCESS" in payload, "welcome_no_access_missing", failures)
                    for linked_key in (
                        "subscriptions",
                        "official_results",
                        "lobby",
                        "member_wins",
                        "short_term_alerts",
                        "swing_alerts",
                        "leaps_alerts",
                        "member_chat",
                    ):
                        expected_url = (
                            f"https://discord.com/channels/{guild.id}/{channel_ids[linked_key]}"
                        )
                        _check(
                            expected_url in payload,
                            f"welcome_{linked_key}_link_missing",
                            failures,
                        )
                if channel_key == "subscriptions" and matching:
                    payload = str(matching[0].embeds[0].to_dict())
                    labels = {
                        getattr(component, "label", None)
                        for row in matching[0].components
                        for component in getattr(row, "children", ())
                    }
                    _check(
                        "Auto-renews monthly until canceled" in payload,
                        "monthly_auto_renew_copy_missing",
                        failures,
                    )
                    _check("CANCEL MONTHLY" in labels, "cancel_monthly_button_missing", failures)
                if channel_key in {"member_wins", "short_term_alerts"} and matching:
                    _check(matching[0].pinned, f"{channel_key}_guide_not_pinned", failures)
            lobby = channel("lobby")
            _check(
                lobby.topic
                == "Open community discussion for markets, AXIS, and general questions.",
                "lobby_topic_mismatch",
                failures,
            )
            _check(config.lobby_guide_message_id is None, "lobby_guide_should_be_absent", failures)
            _check(
                config.mentor_panel_message_id is not None,
                "mentor_panel_message_id_missing",
                failures,
            )
            if config.mentor_panel_message_id is not None:
                try:
                    mentor_panel = await mentor_control.fetch_message(
                        config.mentor_panel_message_id
                    )
                except (discord.NotFound, discord.Forbidden):
                    failures.append("mentor_panel_message_missing")
                else:
                    mentor_labels = {
                        getattr(component, "label", None)
                        for row in mentor_panel.components
                        for component in getattr(row, "children", ())
                    }
                    _check(
                        mentor_labels == {"选择 Mentor", "新增 Mentor"},
                        "mentor_panel_buttons_mismatch",
                        failures,
                    )
            _check(
                config.member_panel_message_id is not None,
                "member_panel_message_id_missing",
                failures,
            )
            if config.member_panel_message_id is not None:
                member_panel_channel = channel("member_control")
                try:
                    member_panel = await member_panel_channel.fetch_message(
                        config.member_panel_message_id
                    )
                except (discord.NotFound, discord.Forbidden):
                    failures.append("member_panel_message_missing")
                else:
                    member_custom_ids = {
                        getattr(component, "custom_id", None)
                        for row in member_panel.components
                        for component in getattr(row, "children", ())
                    }
                    _check(
                        member_custom_ids == {"axis:member:user-select:v2"},
                        "member_panel_user_select_mismatch",
                        failures,
                    )

        application_id = client.application_id
        _check(application_id is not None, "application_id_missing", failures)
        if application_id is not None:
            commands = await client.http.get_guild_commands(application_id, guild.id)
            command_names = {item["name"] for item in commands}
            _check(command_names >= TEST_COMMANDS, "owner_test_commands_missing", failures)
            _check(
                command_names.isdisjoint(REMOVED_COMMANDS),
                "removed_short_term_commands_present",
                failures,
            )
    finally:
        await client.close()
        if connect_task is not None:
            await asyncio.gather(connect_task, return_exceptions=True)
    return failures


def main() -> int:
    try:
        failures = asyncio.run(verify())
    except Exception as exc:
        print(f"discord_runtime=FAIL check={type(exc).__name__}", file=sys.stderr)
        return 2
    if failures:
        print("discord_runtime=FAIL checks=" + ",".join(sorted(failures)))
        return 2
    print("discord_runtime=PASS")
    print("permissions=public,member,manager,owner,bot")
    print("general_guides=idempotent")
    print("mentor_control=select,add")
    print("member_control=searchable_user_select")
    print(f"owner_test_commands={len(TEST_COMMANDS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
