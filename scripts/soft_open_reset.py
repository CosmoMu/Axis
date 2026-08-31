#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import ssl
import sys
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aiohttp  # noqa: E402
import certifi  # noqa: E402
import discord  # noqa: E402

from app.config import ConfigurationError, Settings  # noqa: E402
from app.db.bootstrap import load_discord_ids  # noqa: E402
from app.db.session import Database  # noqa: E402

RESET_ACTION = "SOFT_OPEN_RESET_APPLIED"
PRESERVED_AUDIT_ACTIONS = {"MENTOR_CREATED", RESET_ACTION}
PERSISTENT_MESSAGE_FIELDS = (
    "mentor_panel_message_id",
    "member_panel_message_id",
    "welcome_message_id",
    "subscription_message_id",
    "results_guide_message_id",
    "lobby_guide_message_id",
    "member_wins_guide_message_id",
    "short_term_notice_message_id",
)


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _cutoff() -> tuple[date, datetime]:
    raw_date = os.getenv("PRODUCTION_DATA_START_DATE", "2026-08-31").strip()
    timezone_name = os.getenv("PRODUCTION_DATA_START_TIMEZONE", "America/New_York").strip()
    try:
        production_date = date.fromisoformat(raw_date)
        cutoff = datetime.combine(
            production_date,
            datetime.min.time(),
            tzinfo=ZoneInfo(timezone_name),
        )
    except (ValueError, KeyError) as exc:
        raise ConfigurationError("Production cutoff 配置无效。") from exc
    return production_date, cutoff


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Protected AXIS Soft Open reset.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-guild-id", type=int, required=True)
    parser.add_argument(
        "--phase",
        choices=("database", "discord"),
        required=True,
    )
    return parser.parse_args()


async def _scalar(session, query: str, values: dict[str, object]) -> int:
    value = await session.scalar(text(query), values)
    return int(value or 0)


async def _assert_reset_allowed(session, guild_id: int, cutoff: datetime) -> None:
    marker = await _scalar(
        session,
        "SELECT COUNT(*) FROM audit_logs WHERE guild_id=:guild_id AND action_type=:action_type",
        {"guild_id": guild_id, "action_type": RESET_ACTION},
    )
    if marker:
        raise ConfigurationError("Soft Open Reset 已执行；禁止第二次 Reset。")

    guarded = {
        "trades": "SELECT COUNT(*) FROM trades WHERE guild_id=:guild_id AND created_at>=:cutoff",
        "analysis": (
            "SELECT COUNT(*) FROM analysis_drafts WHERE guild_id=:guild_id AND created_at>=:cutoff"
        ),
        "sources": (
            "SELECT COUNT(*) FROM source_messages WHERE guild_id=:guild_id AND created_at>=:cutoff"
        ),
        "daily_results": (
            "SELECT COUNT(*) FROM daily_results_publications "
            "WHERE guild_id=:guild_id AND session_date>=CAST(:cutoff AS date)"
        ),
        "daily_summaries": (
            "SELECT COUNT(*) FROM daily_summary_publications "
            "WHERE guild_id=:guild_id AND session_date>=CAST(:cutoff AS date)"
        ),
    }
    values = {"guild_id": guild_id, "cutoff": cutoff}
    found = {name: await _scalar(session, query, values) for name, query in guarded.items()}
    if any(found.values()):
        summary = ",".join(f"{name}:{count}" for name, count in found.items() if count)
        raise ConfigurationError(f"检测到 Production cutoff 后的数据：{summary}")


async def _database_counts(session, guild_id: int) -> dict[str, int]:
    values = {"guild_id": guild_id}
    queries = {
        "short_term_trades": (
            "SELECT COUNT(*) FROM trades WHERE guild_id=:guild_id AND category='SHORT_TERM'"
        ),
        "swing_trades": (
            "SELECT COUNT(*) FROM trades WHERE guild_id=:guild_id AND category='SWING'"
        ),
        "leaps_trades": (
            "SELECT COUNT(*) FROM trades WHERE guild_id=:guild_id AND category='LEAPS'"
        ),
        "trade_drafts": "SELECT COUNT(*) FROM trade_drafts WHERE guild_id=:guild_id",
        "trade_events": (
            "SELECT COUNT(*) FROM trade_events e JOIN trades t ON t.id=e.trade_id "
            "WHERE t.guild_id=:guild_id"
        ),
        "trade_publications": ("SELECT COUNT(*) FROM trade_publications WHERE guild_id=:guild_id"),
        "short_term_tracking": (
            "SELECT COUNT(*) FROM short_term_tracking WHERE guild_id=:guild_id"
        ),
        "short_term_tracking_events": (
            "SELECT COUNT(*) FROM short_term_tracking_events WHERE guild_id=:guild_id"
        ),
        "short_term_daily_snapshots": (
            "SELECT COUNT(*) FROM short_term_daily_snapshots WHERE guild_id=:guild_id"
        ),
        "analysis_drafts": ("SELECT COUNT(*) FROM analysis_drafts WHERE guild_id=:guild_id"),
        "mentor_analyses": ("SELECT COUNT(*) FROM mentor_analyses WHERE guild_id=:guild_id"),
        "analysis_publications": (
            "SELECT COUNT(*) FROM analysis_publications WHERE guild_id=:guild_id"
        ),
        "daily_results": (
            "SELECT COUNT(*) FROM daily_results_publications WHERE guild_id=:guild_id"
        ),
        "daily_summaries": (
            "SELECT COUNT(*) FROM daily_summary_publications WHERE guild_id=:guild_id"
        ),
        "membership_entitlements": (
            "SELECT COUNT(*) FROM membership_entitlements WHERE guild_id=:guild_id"
        ),
        "mentors": "SELECT COUNT(*) FROM mentors WHERE guild_id=:guild_id",
    }
    return {name: await _scalar(session, query, values) for name, query in queries.items()}


async def _delete(session, query: str, values: dict[str, object]) -> int:
    result = await session.execute(text(query), values)
    return int(result.rowcount or 0)


async def reset_database(settings: Settings, *, apply: bool) -> None:
    production_date, cutoff = _cutoff()
    database = Database(settings.require_database_url())
    try:
        async with database.session() as session:
            await _assert_reset_allowed(session, settings.discord_guild_id, cutoff)
            counts = await _database_counts(session, settings.discord_guild_id)
            print("database_dry_run=" + ",".join(f"{k}:{v}" for k, v in counts.items()))
            if not apply:
                return

            values: dict[str, object] = {
                "guild_id": settings.discord_guild_id,
                "cutoff": cutoff,
            }
            deleted: dict[str, int] = {}
            statements: Iterable[tuple[str, str]] = (
                (
                    "daily_results_publications",
                    "DELETE FROM daily_results_publications WHERE guild_id=:guild_id",
                ),
                (
                    "daily_summary_publications",
                    "DELETE FROM daily_summary_publications WHERE guild_id=:guild_id",
                ),
                (
                    "market_quote_snapshots",
                    "DELETE FROM market_quote_snapshots WHERE guild_id=:guild_id",
                ),
                (
                    "short_term_daily_snapshots",
                    "DELETE FROM short_term_daily_snapshots WHERE guild_id=:guild_id",
                ),
                (
                    "short_term_tracking_events",
                    "DELETE FROM short_term_tracking_events WHERE guild_id=:guild_id",
                ),
                ("short_term_tracking", "DELETE FROM short_term_tracking WHERE guild_id=:guild_id"),
                ("trade_publications", "DELETE FROM trade_publications WHERE guild_id=:guild_id"),
                (
                    "trade_events",
                    "DELETE FROM trade_events USING trades "
                    "WHERE trade_events.trade_id=trades.id "
                    "AND trades.guild_id=:guild_id",
                ),
                (
                    "analysis_publications",
                    "DELETE FROM analysis_publications WHERE guild_id=:guild_id",
                ),
                (
                    "analysis_prediction_points",
                    "DELETE FROM analysis_prediction_points USING mentor_analyses "
                    "WHERE analysis_prediction_points.analysis_id=mentor_analyses.id "
                    "AND mentor_analyses.guild_id=:guild_id",
                ),
                (
                    "analysis_scenarios",
                    "DELETE FROM analysis_scenarios USING mentor_analyses "
                    "WHERE analysis_scenarios.analysis_id=mentor_analyses.id "
                    "AND mentor_analyses.guild_id=:guild_id",
                ),
                (
                    "analysis_indicators",
                    "DELETE FROM analysis_indicators USING mentor_analyses "
                    "WHERE analysis_indicators.analysis_id=mentor_analyses.id "
                    "AND mentor_analyses.guild_id=:guild_id",
                ),
                (
                    "analysis_points",
                    "DELETE FROM analysis_points USING mentor_analyses "
                    "WHERE analysis_points.analysis_id=mentor_analyses.id "
                    "AND mentor_analyses.guild_id=:guild_id",
                ),
                (
                    "analysis_key_levels",
                    "DELETE FROM analysis_key_levels USING mentor_analyses "
                    "WHERE analysis_key_levels.analysis_id=mentor_analyses.id "
                    "AND mentor_analyses.guild_id=:guild_id",
                ),
                (
                    "analysis_symbols",
                    "DELETE FROM analysis_symbols USING mentor_analyses "
                    "WHERE analysis_symbols.analysis_id=mentor_analyses.id "
                    "AND mentor_analyses.guild_id=:guild_id",
                ),
                ("mentor_analyses", "DELETE FROM mentor_analyses WHERE guild_id=:guild_id"),
                (
                    "analysis_draft_revisions",
                    "DELETE FROM analysis_draft_revisions USING analysis_drafts "
                    "WHERE analysis_draft_revisions.draft_id=analysis_drafts.id "
                    "AND analysis_drafts.guild_id=:guild_id",
                ),
                ("analysis_drafts", "DELETE FROM analysis_drafts WHERE guild_id=:guild_id"),
                ("trade_drafts", "DELETE FROM trade_drafts WHERE guild_id=:guild_id"),
                ("trades", "DELETE FROM trades WHERE guild_id=:guild_id"),
                ("llm_invocations", "DELETE FROM llm_invocations WHERE guild_id=:guild_id"),
                (
                    "source_attachments",
                    "DELETE FROM source_attachments USING source_messages "
                    "WHERE source_attachments.source_message_id=source_messages.id "
                    "AND source_messages.guild_id=:guild_id",
                ),
                ("source_messages", "DELETE FROM source_messages WHERE guild_id=:guild_id"),
                (
                    "payment_events",
                    "DELETE FROM payment_events WHERE membership_id IN "
                    "(SELECT id FROM membership_entitlements WHERE guild_id=:guild_id)",
                ),
                (
                    "payment_webhook_events",
                    "DELETE FROM payment_webhook_events WHERE membership_session_id IN "
                    "(SELECT session_id FROM membership_sessions WHERE guild_id=:guild_id)",
                ),
                ("membership_trials", "DELETE FROM membership_trials WHERE guild_id=:guild_id"),
                (
                    "membership_events",
                    "DELETE FROM membership_events USING memberships "
                    "WHERE membership_events.membership_id=memberships.id "
                    "AND memberships.guild_id=:guild_id",
                ),
                ("memberships", "DELETE FROM memberships WHERE guild_id=:guild_id"),
                ("subscriptions", "DELETE FROM subscriptions WHERE guild_id=:guild_id"),
                ("membership_sessions", "DELETE FROM membership_sessions WHERE guild_id=:guild_id"),
                (
                    "membership_acknowledgements",
                    "DELETE FROM membership_acknowledgements WHERE guild_id=:guild_id",
                ),
                (
                    "membership_entitlements",
                    "DELETE FROM membership_entitlements WHERE guild_id=:guild_id",
                ),
                ("scheduled_jobs", "DELETE FROM scheduled_jobs WHERE guild_id=:guild_id"),
                ("system_alerts", "DELETE FROM system_alerts WHERE guild_id=:guild_id"),
            )
            for name, query in statements:
                deleted[name] = await _delete(session, query, values)

            deleted["audit_logs"] = await _delete(
                session,
                "DELETE FROM audit_logs WHERE guild_id=:guild_id "
                "AND action_type NOT IN ('MENTOR_CREATED','SOFT_OPEN_RESET_APPLIED')",
                {"guild_id": settings.discord_guild_id},
            )
            await session.execute(
                text(
                    "UPDATE input_code_counters SET next_value=1 "
                    "WHERE guild_id=:guild_id AND input_kind IN ('SIGNAL','ANALYSIS')"
                ),
                values,
            )
            assignments = ",".join(f"{field}=NULL" for field in PERSISTENT_MESSAGE_FIELDS)
            await session.execute(
                text(f"UPDATE guild_config SET {assignments} WHERE guild_id=:guild_id"),
                values,
            )
            actor_user_id = settings.discord_owner_user_id or settings.discord_guild_id
            await session.execute(
                text(
                    "INSERT INTO audit_logs "
                    "(id,guild_id,actor_user_id,action_type,entity_type,entity_id,"
                    "before_json,after_json,discord_interaction_id,created_at) "
                    "VALUES (:id,:guild_id,:actor_user_id,:action_type,'guild',:entity_id,"
                    "NULL,CAST(:after_json AS json),NULL,CURRENT_TIMESTAMP)"
                ),
                {
                    "id": uuid.uuid4(),
                    "guild_id": settings.discord_guild_id,
                    "actor_user_id": actor_user_id,
                    "action_type": RESET_ACTION,
                    "entity_id": str(settings.discord_guild_id),
                    "after_json": (
                        '{"production_data_start_date":"'
                        + production_date.isoformat()
                        + '","deployment_stage":"SOFT_OPEN"}'
                    ),
                },
            )
            await session.commit()
            print("database_reset=PASS")
            print("database_deleted=" + ",".join(f"{k}:{v}" for k, v in deleted.items()))
    finally:
        await database.dispose()


async def reset_discord(settings: Settings, *, apply: bool) -> None:
    discord_ids = load_discord_ids(settings.ids_path, settings.discord_guild_id)
    intents = discord.Intents.none()
    intents.guilds = True
    client = discord.Client(
        intents=intents,
        connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())),
    )
    connect_task = None
    try:
        await client.login(settings.require_token())
        connect_task = asyncio.create_task(client.connect(reconnect=False))
        await client.wait_until_ready()
        guild = client.get_guild(settings.discord_guild_id)
        if guild is None:
            raise ConfigurationError("Discord Guild 不存在。")
        deleted: dict[str, int] = {}
        for key, channel_id in discord_ids["channels"].items():
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                raise ConfigurationError(f"Discord Channel 缺失：{key}")
            messages = [message async for message in channel.history(limit=None)]
            deleted[key] = len(messages)
            if apply:
                for offset in range(0, len(messages), 100):
                    batch = messages[offset : offset + 100]
                    if len(batch) == 1:
                        await batch[0].delete()
                    elif batch:
                        await channel.delete_messages(batch)
        print("discord_messages=" + ",".join(f"{k}:{v}" for k, v in deleted.items()))
        if apply:
            print("discord_reset=PASS")
    finally:
        await client.close()
        if connect_task is not None:
            await asyncio.gather(connect_task, return_exceptions=True)


async def run() -> None:
    args = _parse_args()
    settings = Settings.load(PROJECT_ROOT)
    if args.confirm_guild_id != settings.discord_guild_id:
        raise ConfigurationError("Guild confirmation mismatch。")
    if args.apply:
        if not _enabled("SOFT_OPEN_RESET_APPLY"):
            raise ConfigurationError("SOFT_OPEN_RESET_APPLY 未启用。")
        if _enabled("SOFT_OPEN_RESET_DRY_RUN"):
            raise ConfigurationError("SOFT_OPEN_RESET_DRY_RUN 必须关闭后才能 Apply。")
    if args.phase == "database":
        await reset_database(settings, apply=args.apply)
    else:
        await reset_discord(settings, apply=args.apply)


def main() -> int:
    try:
        asyncio.run(run())
    except Exception as exc:
        print(f"soft_open_reset=FAIL error_type={type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
