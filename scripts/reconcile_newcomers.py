#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import discord  # noqa: E402

from app.config import ConfigurationError, Settings  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.services.membership_access import MembershipAcknowledgementService  # noqa: E402
from app.services.newcomer_access import NewcomerAccessService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply AXIS Newcomer production baseline and role eligibility."
    )
    parser.add_argument(
        "--baseline-existing",
        action="store_true",
        help="Treat current pre-gate server users as approved without granting a Trial.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-guild-id", type=int)
    return parser.parse_args()


class InventoryClient(discord.Client):
    def __init__(self, guild_id: int) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        super().__init__(intents=intents)
        self.guild_id = guild_id
        self.result: asyncio.Future[discord.Guild] | None = None

    async def on_ready(self) -> None:
        if self.result is not None and not self.result.done():
            guild = self.get_guild(self.guild_id)
            if guild is None:
                self.result.set_exception(RuntimeError("TARGET_GUILD_NOT_FOUND"))
            else:
                self.result.set_result(guild)


async def inventory(settings: Settings, args: argparse.Namespace) -> int:
    if args.apply and (
        not args.baseline_existing or args.confirm_guild_id != settings.discord_guild_id
    ):
        raise ConfigurationError(
            "Apply requires --baseline-existing and the exact --confirm-guild-id."
        )
    database = Database(settings.require_database_url())
    service = NewcomerAccessService(database, MembershipAcknowledgementService(database))
    client = InventoryClient(settings.discord_guild_id)
    try:
        async with client:
            client.result = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(client.start(settings.require_token(), reconnect=False))
            guild = await asyncio.wait_for(client.result, timeout=30)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await client.close()

        receive_newcomer: list[discord.Member] = []
        do_not_receive: list[discord.Member] = []
        baseline: list[discord.Member] = []
        for member in sorted(guild.members, key=lambda item: item.id):
            if member.bot:
                continue
            profile = await service.profile(guild.id, member.id)
            if profile is not None and profile.approved:
                do_not_receive.append(member)
            elif profile is None and args.baseline_existing:
                baseline.append(member)
                do_not_receive.append(member)
            else:
                receive_newcomer.append(member)

        print(f"guild_id={guild.id}")
        print(f"mode={'APPLY' if args.apply else 'DRY_RUN'}")
        print(f"existing_users_to_baseline={len(baseline)}")
        print(f"users_that_would_receive_newcomer={len(receive_newcomer)}")
        for member in receive_newcomer:
            print(f"  NEWCOMER {member.id} {member}")
        print(f"users_that_would_not_receive_newcomer={len(do_not_receive)}")
        for member in do_not_receive:
            print(f"  NOT_NEWCOMER {member.id} {member}")

        if args.apply:
            actor_id = settings.discord_owner_user_id or guild.owner_id
            applied = 0
            for member in baseline:
                changed = await service.baseline_approved_user(
                    guild.id,
                    member.id,
                    username=str(member),
                    display_name=member.display_name,
                    joined_at=member.joined_at or datetime.now(UTC),
                    actor_user_id=actor_id,
                )
                applied += int(changed)
            activated_at = await service.activate_gate(guild.id, actor_user_id=actor_id)
            print(f"production_baseline_applied={applied}")
            print(f"newcomer_gate_activated_at={activated_at.isoformat()}")
        return 0
    finally:
        await database.dispose()


def main() -> int:
    try:
        settings = Settings.load(PROJECT_ROOT)
        return asyncio.run(inventory(settings, parse_args()))
    except (ConfigurationError, RuntimeError, TimeoutError):
        print("Newcomer reconciliation stopped; sensitive details were omitted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
