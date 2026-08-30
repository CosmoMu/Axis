from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ConfigurationError
from app.db.models import GuildConfig


def load_discord_ids(path: Path, expected_guild_id: int) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("无法读取本地 Discord ID 文件。") from exc
    if not isinstance(payload, dict) or payload.get("guild_id") != expected_guild_id:
        raise ConfigurationError("Discord ID 文件与目标 Guild 不匹配。")
    return payload


def _snowflake(section: dict[str, Any], key: str) -> int | None:
    value = section.get(key)
    return value if isinstance(value, int) and value > 0 else None


async def seed_guild_config(
    session: AsyncSession,
    *,
    guild_id: int,
    discord_ids: dict[str, Any],
) -> GuildConfig:
    roles = discord_ids.get("roles", {})
    channels = discord_ids.get("channels", {})
    if not isinstance(roles, dict) or not isinstance(channels, dict):
        raise ConfigurationError("Discord ID 文件缺少 roles 或 channels。")

    values = {
        "manager_role_id": _snowflake(roles, "manager"),
        "member_role_id": _snowflake(roles, "member"),
        "results_channel_id": _snowflake(channels, "official_results"),
        "short_term_channel_id": _snowflake(channels, "short_term_alerts"),
        "swing_channel_id": _snowflake(channels, "swing_alerts"),
        "leaps_channel_id": _snowflake(channels, "leaps_alerts"),
        "member_lounge_channel_id": _snowflake(channels, "member_chat"),
        "mentor_control_channel_id": _snowflake(channels, "mentor_control"),
        "member_control_channel_id": _snowflake(channels, "member_control"),
    }
    config = await session.get(GuildConfig, guild_id)
    if config is None:
        config = GuildConfig(guild_id=guild_id, **values)
        session.add(config)
    else:
        for name, value in values.items():
            setattr(config, name, value)
    await session.flush()
    return config
