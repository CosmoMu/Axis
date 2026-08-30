from __future__ import annotations

from typing import Any

from discord.ext import commands

from app.bot.cogs.card_review import CardReviewCog
from app.bot.cogs.draft_worker import DraftWorkerCog
from app.bot.cogs.signal_input import SignalInputCog
from app.bot.intents import axis_intents
from app.config import ConfigurationError, Settings
from app.services.card_review import CardReviewService
from app.services.draft_generation import DraftGenerationService
from app.services.signal_input import SignalInputService


def _required_snowflake(section: dict[str, Any], key: str) -> int:
    value = section.get(key)
    if not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"Discord ID 文件缺少有效的 {key} ID。")
    return value


class AxisBot(commands.Bot):
    def __init__(
        self,
        *,
        settings: Settings,
        discord_ids: dict[str, Any],
        signal_input_service: SignalInputService,
        draft_generation_service: DraftGenerationService | None,
        card_review_service: CardReviewService,
    ) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=axis_intents(),
            help_command=None,
        )
        roles = discord_ids.get("roles")
        channels = discord_ids.get("channels")
        if not isinstance(roles, dict) or not isinstance(channels, dict):
            raise ConfigurationError("Discord ID 文件缺少 roles 或 channels。")
        self._signal_cog = SignalInputCog(
            self,
            service=signal_input_service,
            guild_id=settings.discord_guild_id,
            channel_id=_required_snowflake(channels, "signal_input"),
            manager_role_id=_required_snowflake(roles, "manager"),
            owner_user_id=settings.discord_owner_user_id,
            draft_processing_enabled=draft_generation_service is not None,
        )
        self._draft_worker_cog = (
            DraftWorkerCog(self, service=draft_generation_service)
            if draft_generation_service is not None
            else None
        )
        self._card_review_cog = CardReviewCog(
            self,
            service=card_review_service,
            guild_id=settings.discord_guild_id,
            channel_id=_required_snowflake(channels, "card_review"),
            manager_role_id=_required_snowflake(roles, "manager"),
            owner_user_id=settings.discord_owner_user_id,
        )

    async def setup_hook(self) -> None:
        await self.add_cog(self._signal_cog)
        if self._draft_worker_cog is not None:
            await self.add_cog(self._draft_worker_cog)
        await self.add_cog(self._card_review_cog)
