#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
import discord  # noqa: E402

from app.bot.client import AxisBot  # noqa: E402
from app.config import ConfigurationError, Settings  # noqa: E402
from app.db.bootstrap import load_discord_ids, seed_guild_config  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.integrations.openai_trade_parser import (  # noqa: E402
    OpenAITradeParser,
    load_trade_prompt,
    load_trade_schema,
)
from app.services.attachment_storage import LocalAttachmentStore  # noqa: E402
from app.services.draft_generation import DraftGenerationService  # noqa: E402
from app.services.signal_input import SignalInputService  # noqa: E402


async def run() -> None:
    settings = Settings.load(PROJECT_ROOT)
    token = settings.require_token()
    database = Database(settings.require_database_url())
    discord_ids = load_discord_ids(settings.ids_path, settings.discord_guild_id)
    try:
        async with database.session() as session:
            await seed_guild_config(
                session,
                guild_id=settings.discord_guild_id,
                discord_ids=discord_ids,
            )
            await session.commit()

        attachment_store = LocalAttachmentStore(
            settings.attachment_storage_path,
            max_bytes=settings.max_attachment_bytes,
        )
        draft_generation_service = None
        if settings.llm_api_key:
            parser = OpenAITradeParser(
                api_key=settings.require_llm_api_key(),
                model=settings.llm_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
                schema=load_trade_schema(settings.llm_schema_path),
                prompt=load_trade_prompt(settings.llm_prompt_path),
            )
            draft_generation_service = DraftGenerationService(
                database,
                attachment_store,
                parser,
            )
        bot = AxisBot(
            settings=settings,
            discord_ids=discord_ids,
            signal_input_service=SignalInputService(database, attachment_store),
            draft_generation_service=draft_generation_service,
        )
        async with bot:
            await bot.start(token, reconnect=True)
    finally:
        await database.dispose()


def main() -> int:
    try:
        asyncio.run(run())
    except ConfigurationError as exc:
        print(f"AXIS BOT 未启动：{exc}", file=sys.stderr)
        return 2
    except discord.LoginFailure:
        print("AXIS BOT 登录失败；请检查本地 .env，Token 未被输出。", file=sys.stderr)
        return 2
    except discord.PrivilegedIntentsRequired:
        print(
            "AXIS BOT 缺少 Server Members 或 Message Content Intent。",
            file=sys.stderr,
        )
        return 2
    except (aiohttp.ClientError, TimeoutError):
        print("AXIS BOT 无法连接 Discord；网络详情未写入日志。", file=sys.stderr)
        return 2
    except Exception:
        print("AXIS BOT 启动失败；敏感异常详情未写入日志。", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
