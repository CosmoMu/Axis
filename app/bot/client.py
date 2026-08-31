from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from app.bot.cogs.analysis_pipeline import AnalysisPipelineCog
from app.bot.cogs.card_review import CardReviewCog
from app.bot.cogs.card_testing import CardTestingCog
from app.bot.cogs.daily_results_review import DailyResultsReviewCog
from app.bot.cogs.daily_summary import DailySummaryCog
from app.bot.cogs.draft_worker import DraftWorkerCog
from app.bot.cogs.general_control import GeneralControlCog
from app.bot.cogs.manager_control import ManagerControlCog
from app.bot.cogs.payment_webhook import PaymentWebhookCog
from app.bot.cogs.short_term_tracking import ShortTermTrackingCog
from app.bot.cogs.signal_input import SignalInputCog
from app.bot.cogs.system_alerts import SystemAlertsCog
from app.bot.intents import axis_intents
from app.config import ConfigurationError, Settings
from app.domain.public_identity import PublicIdentityPolicy
from app.integrations.stripe_gateway import StripeGateway
from app.market_intelligence.trade_plan import SwingLeapsTradePlanService
from app.services.analysis_pipeline import AnalysisPipelineService
from app.services.card_review import CardReviewService
from app.services.daily_results_review import DailyResultsReviewService
from app.services.daily_summary import DailySummaryService
from app.services.draft_generation import DraftGenerationService
from app.services.membership_access import (
    MembershipAccessService,
    MembershipAcknowledgementService,
    MembershipPriceCatalog,
)
from app.services.membership_management import MembershipManagementService
from app.services.membership_stripe import MembershipStripeService
from app.services.mentor_management import MentorManagementService
from app.services.official_results import OfficialResultsService
from app.services.short_term_tracking import MarketTrackingService
from app.services.signal_input import SignalInputService
from app.services.system_alerts import SystemAlertService
from app.services.trade_publication import TradePublicationService

logger = logging.getLogger(__name__)


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
        short_term_tracking_service: MarketTrackingService,
        mentor_service: MentorManagementService,
        membership_service: MembershipManagementService,
        membership_access_service: MembershipAccessService,
        membership_acknowledgements: MembershipAcknowledgementService,
        membership_price_catalog: MembershipPriceCatalog,
        membership_stripe_service: MembershipStripeService,
        stripe_gateway: StripeGateway | None,
        public_identity: PublicIdentityPolicy,
        system_alert_service: SystemAlertService,
        results_service: OfficialResultsService,
        analysis_service: AnalysisPipelineService | None,
        daily_summary_service: DailySummaryService | None,
        daily_results_review_service: DailyResultsReviewService | None,
        swing_leaps_trade_plan_service: SwingLeapsTradePlanService | None,
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
            tracking_service=short_term_tracking_service,
            trade_plan_service=swing_leaps_trade_plan_service,
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
            publish_individual_results=not settings.results_review_enabled,
        )
        results_channel_id = _required_snowflake(channels, "official_results")
        self._general_control_cog = GeneralControlCog(
            self,
            guild_id=settings.discord_guild_id,
            welcome_channel_id=_required_snowflake(channels, "welcome"),
            subscriptions_channel_id=_required_snowflake(channels, "subscriptions"),
            results_channel_id=results_channel_id,
            lobby_channel_id=_required_snowflake(channels, "lobby"),
            member_wins_channel_id=_required_snowflake(channels, "member_wins"),
            short_term_channel_id=_required_snowflake(channels, "short_term_alerts"),
            swing_channel_id=_required_snowflake(channels, "swing_alerts"),
            leaps_channel_id=_required_snowflake(channels, "leaps_alerts"),
            member_chat_channel_id=_required_snowflake(channels, "member_chat"),
            access_service=membership_access_service,
            acknowledgements=membership_acknowledgements,
            price_catalog=membership_price_catalog,
            stripe_service=membership_stripe_service,
            public_identity=public_identity,
            sync_role=self._manager_control_cog.sync_member_role,
        )
        self._system_alerts_cog = SystemAlertsCog(
            self,
            guild_id=settings.discord_guild_id,
            channel_id=_required_snowflake(channels, "system_alerts"),
            service=system_alert_service,
            check_seconds=settings.system_alert_check_seconds,
            moomoo_enabled=settings.moomoo_enabled,
            moomoo_host=settings.moomoo_host,
            moomoo_port=settings.moomoo_port,
        )
        self._payment_webhook_cog = PaymentWebhookCog(
            self,
            guild_id=settings.discord_guild_id,
            host=settings.payment_webhook_host,
            port=settings.payment_webhook_port,
            gateway=stripe_gateway,
            payment_service=membership_stripe_service,
            sync_role=self._manager_control_cog.sync_member_role,
            reconciliation_minutes=settings.stripe_reconciliation_minutes,
            relay_url=(
                settings.stripe_live_webhook_relay_url
                if settings.stripe_mode.value == "live"
                else None
            ),
            relay_secret=(
                settings.stripe_live_webhook_relay_secret
                if settings.stripe_mode.value == "live"
                else ""
            ),
            relay_poll_seconds=settings.stripe_live_webhook_relay_poll_seconds,
        )
        self._card_testing_cog = CardTestingCog(
            self,
            guild_id=settings.discord_guild_id,
            owner_user_id=settings.discord_owner_user_id,
            channel_id=_required_snowflake(channels, "card_testing"),
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
                tracking_service=short_term_tracking_service,
                publish_legacy_results=not settings.results_review_enabled,
            )
            if daily_summary_service is not None
            else None
        )
        self._daily_results_review_cog = (
            DailyResultsReviewCog(
                self,
                service=daily_results_review_service,
                guild_id=settings.discord_guild_id,
                manager_role_id=_required_snowflake(roles, "manager"),
                owner_user_id=settings.discord_owner_user_id,
                draft_delay_minutes=settings.results_review_draft_delay_minutes,
            )
            if daily_results_review_service is not None
            else None
        )
        self._short_term_tracking_cog = ShortTermTrackingCog(
            self,
            service=short_term_tracking_service,
            guild_id=settings.discord_guild_id,
            poll_seconds=short_term_tracking_service.policy.poll_seconds,
        )
        self._guild_command_target = discord.Object(id=settings.discord_guild_id)
        self._guild_commands_synced = False

    async def setup_hook(self) -> None:
        await self.add_cog(self._signal_cog)
        if self._draft_worker_cog is not None:
            await self.add_cog(self._draft_worker_cog)
        await self.add_cog(self._card_review_cog)
        await self.add_cog(self._short_term_tracking_cog)
        await self.add_cog(self._manager_control_cog)
        await self.add_cog(self._system_alerts_cog)
        await self.add_cog(self._general_control_cog)
        await self.add_cog(self._payment_webhook_cog)
        await self.add_cog(self._card_testing_cog)
        if self._analysis_cog is not None:
            await self.add_cog(self._analysis_cog)
        if self._daily_summary_cog is not None:
            await self.add_cog(self._daily_summary_cog)
        if self._daily_results_review_cog is not None:
            await self.add_cog(self._daily_results_review_cog)
        self.tree.copy_global_to(guild=self._guild_command_target)
        await self._sync_guild_commands()

    async def on_ready(self) -> None:
        if not self._guild_commands_synced:
            await self._sync_guild_commands()

    async def _sync_guild_commands(self) -> None:
        try:
            await self.tree.sync(guild=self._guild_command_target)
        except discord.HTTPException as exc:
            logger.warning(
                "event=guild_command_sync_failed status=%s error_type=%s",
                exc.status,
                type(exc).__name__,
            )
            return
        self._guild_commands_synced = True
