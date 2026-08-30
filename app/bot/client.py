from __future__ import annotations

from typing import Any

from discord.ext import commands

from app.bot.cogs.analysis_pipeline import AnalysisPipelineCog
from app.bot.cogs.card_review import CardReviewCog
from app.bot.cogs.daily_summary import DailySummaryCog
from app.bot.cogs.draft_worker import DraftWorkerCog
from app.bot.cogs.manager_control import ManagerControlCog
from app.bot.cogs.signal_input import SignalInputCog
from app.bot.intents import axis_intents
from app.config import ConfigurationError, Settings
from app.services.analysis_pipeline import AnalysisPipelineService
from app.services.card_review import CardReviewService
from app.services.daily_summary import DailySummaryService
from app.services.draft_generation import DraftGenerationService
from app.services.membership_management import MembershipManagementService
from app.services.mentor_management import MentorManagementService
from app.services.official_results import OfficialResultsService
from app.services.signal_input import SignalInputService
from app.services.trade_publication import TradePublicationService


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
        trade_publication_service: TradePublicationService,
        mentor_service: MentorManagementService,
        membership_service: MembershipManagementService,
        results_service: OfficialResultsService,
        analysis_service: AnalysisPipelineService | None,
        daily_summary_service: DailySummaryService | None,
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
            publication_service=trade_publication_service,
            guild_id=settings.discord_guild_id,
            channel_id=_required_snowflake(channels, "card_review"),
            manager_role_id=_required_snowflake(roles, "manager"),
            member_role_id=_required_snowflake(roles, "member"),
            owner_user_id=settings.discord_owner_user_id,
        )
        self._manager_control_cog = ManagerControlCog(
            self,
            guild_id=settings.discord_guild_id,
            owner_user_id=settings.discord_owner_user_id,
            manager_role_id=_required_snowflake(roles, "manager"),
            member_role_id=_required_snowflake(roles, "member"),
            mentor_channel_id=_required_snowflake(channels, "mentor_control"),
            member_channel_id=_required_snowflake(channels, "member_control"),
            mentor_service=mentor_service,
            membership_service=membership_service,
            results_service=results_service,
        )
        self._analysis_cog = (
            AnalysisPipelineCog(
                self,
                guild_id=settings.discord_guild_id,
                input_channel_id=_required_snowflake(channels, "analysis_input"),
                review_channel_id=_required_snowflake(channels, "analysis_review"),
                manager_role_id=_required_snowflake(roles, "manager"),
                owner_user_id=settings.discord_owner_user_id,
                input_service=signal_input_service,
                service=analysis_service,
            )
            if analysis_service is not None
            else None
        )
        self._daily_summary_cog = (
            DailySummaryCog(
                self,
                service=daily_summary_service,
                guild_id=settings.discord_guild_id,
                schedule_hhmm=settings.daily_summary_time_et,
            )
            if daily_summary_service is not None
            else None
        )

    async def setup_hook(self) -> None:
        await self.add_cog(self._signal_cog)
        if self._draft_worker_cog is not None:
            await self.add_cog(self._draft_worker_cog)
        await self.add_cog(self._card_review_cog)
        await self.add_cog(self._manager_control_cog)
        if self._analysis_cog is not None:
            await self.add_cog(self._analysis_cog)
        if self._daily_summary_cog is not None:
            await self.add_cog(self._daily_summary_cog)
