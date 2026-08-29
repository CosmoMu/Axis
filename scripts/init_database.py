#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.config import ConfigurationError, Settings  # noqa: E402
from app.db.bootstrap import load_discord_ids, seed_guild_config  # noqa: E402
from app.db.session import Database  # noqa: E402


async def seed_runtime_config(
    settings: Settings,
    database_url: str,
    discord_ids: dict[str, object],
) -> None:
    database = Database(database_url)
    try:
        async with database.session() as session:
            await seed_guild_config(
                session,
                guild_id=settings.discord_guild_id,
                discord_ids=discord_ids,
            )
            await session.commit()
    finally:
        await database.dispose()


def main() -> int:
    try:
        settings = Settings.load(PROJECT_ROOT)
        database_url = settings.require_database_url()
        discord_ids = load_discord_ids(settings.ids_path, settings.discord_guild_id)
    except ConfigurationError as exc:
        print(f"Database initialization stopped: {exc}", file=sys.stderr)
        return 2

    try:
        os.environ["DATABASE_URL"] = database_url
        alembic_config = Config(PROJECT_ROOT / "alembic.ini")
        command.upgrade(alembic_config, "head")
        asyncio.run(seed_runtime_config(settings, database_url, discord_ids))
    except Exception:  # Database drivers can include connection details in their exception text.
        print(
            "Database initialization failed; connection details were omitted from output.",
            file=sys.stderr,
        )
        return 2
    print("AXIS database migrations are up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
