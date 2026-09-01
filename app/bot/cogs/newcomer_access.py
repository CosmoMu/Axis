from __future__ import annotations

import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.db.models import GuildConfig
from app.domain.enums import AccessApplicationStatus
from app.services.membership_access import MembershipAccessError, MembershipAccessService
from app.services.newcomer_access import (
    DISCOVERY_SOURCES,
    INTEREST_LABELS,
    ApplicationSnapshot,
    NewcomerAccessError,
    NewcomerAccessService,
    NewcomerRiskScanner,
    RiskFlagSnapshot,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/Toronto")


def welcome_application_embed(*, trial_days: int = 7) -> discord.Embed:
    embed = discord.Embed(
        title="WELCOME TO AXIS",
        description=(
            "**Signals without the noise.**\n\n"
            "New members must complete a short access application before entering AXIS.\n\n"
            "Once approved, you will automatically receive:\n\n"
            f"**{trial_days} DAYS OF FULL MEMBER ACCESS**\n\n"
            "No credit card required.\nNo automatic renewal."
        ),
        color=0x86F7A8,
    )
    embed.add_field(
        name="MEMBER ACCESS INCLUDES",
        value="⚡ Short-Term\n〽️ Swing\n♾️ LEAPS\n🛋️ Member Lounge",
        inline=False,
    )
    embed.add_field(
        name="RISK NOTICE",
        value=(
            "AXIS provides market analysis, research, and educational content only.\n\n"
            "Nothing provided by AXIS constitutes investment or financial advice.\n\n"
            "Trading involves risk.\n\n**MY RISK IS NOT YOUR RISK.**"
        ),
        inline=False,
    )
    embed.add_field(
        name="SAFETY NOTICE",
        value=(
            "AXIS staff will never DM you first asking for private payment, passwords, "
            "brokerage credentials, crypto transfers, or remote access."
        ),
        inline=False,
    )
    embed.set_footer(text="AXIS Welcome v1")
    return embed


def access_required_embed() -> discord.Embed:
    return discord.Embed(
        title="AXIS ACCESS",
        description=(
            "Please complete the AXIS application first.\n\n"
            "Once approved, you will automatically receive\n"
            "7 days of full member access."
        ),
        color=0x111411,
    )


def risk_acknowledgement_embed() -> discord.Embed:
    return discord.Embed(
        title="RISK ACKNOWLEDGEMENT",
        description=(
            "AXIS provides content for market analysis, research, and "
            "educational purposes only.\n\n"
            "AXIS does not provide personalized investment, financial, or trading advice.\n\n"
            "Options and other financial markets involve significant risk and may result in "
            "partial or total loss of capital.\n\n"
            "All entries, exits, position sizing, and risk-management decisions remain the "
            "responsibility of the individual user.\n\n"
            "Past performance does not guarantee future results.\n\n"
            "**MY RISK IS NOT YOUR RISK.**"
        ),
        color=0x111411,
    )


def safety_agreement_embed() -> discord.Embed:
    return discord.Embed(
        title="COMMUNITY SAFETY AGREEMENT",
        description=(
            "I agree that I will not:\n\n"
            "- impersonate AXIS staff\n"
            "- scam or solicit AXIS members\n"
            "- request private payments from members\n"
            "- spam or maliciously DM members\n"
            "- redistribute or resell private AXIS content\n"
            "- request passwords or brokerage credentials\n"
            "- request remote account access"
        ),
        color=0x111411,
    )


class ApplyAccessView(discord.ui.View):
    def __init__(self, controller: NewcomerAccessCog) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        button = discord.ui.Button(
            label="APPLY TO JOIN AXIS",
            style=discord.ButtonStyle.success,
            custom_id="axis:newcomer:apply:v1",
        )
        button.callback = self.apply
        self.add_item(button)

    async def apply(self, interaction: discord.Interaction) -> None:
        await self.controller.begin_application(interaction)


@dataclass(slots=True)
class ApplicationAnswers:
    discovery_source: str | None = None
    interests: tuple[str, ...] = ()
    referred_by: str | None = None


class ApplicationFormView(discord.ui.View):
    def __init__(self, controller: NewcomerAccessCog, user_id: int) -> None:
        super().__init__(timeout=600)
        self.controller = controller
        self.user_id = user_id
        self.answers = ApplicationAnswers()
        source = discord.ui.Select(
            placeholder="How did you hear about AXIS?",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=label, value=value)
                for value, label in DISCOVERY_SOURCES.items()
            ],
        )
        source.callback = self.select_source
        self.source_select = source
        self.add_item(source)
        interests = discord.ui.Select(
            placeholder="What are you mainly interested in?",
            min_values=1,
            max_values=4,
            options=[
                discord.SelectOption(label=label, value=value)
                for value, label in INTEREST_LABELS.items()
            ],
        )
        interests.callback = self.select_interests
        self.interests_select = interests
        self.add_item(interests)
        continue_button = discord.ui.Button(label="CONTINUE", style=discord.ButtonStyle.success)
        continue_button.callback = self.continue_application
        self.add_item(continue_button)

    async def _belongs_to_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This application belongs to another user.", ephemeral=True
        )
        return False

    async def select_source(self, interaction: discord.Interaction) -> None:
        if not await self._belongs_to_user(interaction):
            return
        self.answers.discovery_source = self.source_select.values[0]
        await interaction.response.defer()

    async def select_interests(self, interaction: discord.Interaction) -> None:
        if not await self._belongs_to_user(interaction):
            return
        self.answers.interests = tuple(self.interests_select.values)
        await interaction.response.defer()

    async def continue_application(self, interaction: discord.Interaction) -> None:
        if not await self._belongs_to_user(interaction):
            return
        if self.answers.discovery_source is None or not self.answers.interests:
            await interaction.response.send_message(
                "Please select your source and at least one interest.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ReferralModal(self.controller, self.user_id, self.answers)
        )


class ReferralModal(discord.ui.Modal, title="AXIS ACCESS APPLICATION"):
    referred_by = discord.ui.TextInput(
        label="Who referred you to AXIS? (optional)",
        placeholder="Discord username, nickname, or referral name",
        required=False,
        max_length=200,
    )

    def __init__(
        self,
        controller: NewcomerAccessCog,
        user_id: int,
        answers: ApplicationAnswers,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.user_id = user_id
        self.answers = answers

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This application belongs to another user.", ephemeral=True
            )
            return
        self.answers.referred_by = str(self.referred_by.value).strip() or None
        await interaction.response.send_message(
            embed=risk_acknowledgement_embed(),
            view=RiskAgreementView(self.controller, self.user_id, self.answers),
            ephemeral=True,
        )


class RiskAgreementView(discord.ui.View):
    def __init__(
        self,
        controller: NewcomerAccessCog,
        user_id: int,
        answers: ApplicationAnswers,
    ) -> None:
        super().__init__(timeout=600)
        self.controller = controller
        self.user_id = user_id
        self.answers = answers
        button = discord.ui.Button(label="I AGREE", style=discord.ButtonStyle.success)
        button.callback = self.agree
        self.add_item(button)

    async def agree(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This agreement is not yours.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=safety_agreement_embed(),
            view=SafetyAgreementView(self.controller, self.user_id, self.answers),
        )


class SafetyAgreementView(discord.ui.View):
    def __init__(
        self,
        controller: NewcomerAccessCog,
        user_id: int,
        answers: ApplicationAnswers,
    ) -> None:
        super().__init__(timeout=600)
        self.controller = controller
        self.user_id = user_id
        self.answers = answers
        button = discord.ui.Button(label="I AGREE", style=discord.ButtonStyle.success)
        button.callback = self.agree
        self.add_item(button)

    async def agree(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This agreement is not yours.", ephemeral=True)
            return
        await self.controller.submit_application(interaction, self.answers)


class JoinReviewView(discord.ui.View):
    def __init__(
        self,
        controller: NewcomerAccessCog,
        application_id: uuid.UUID,
        *,
        status: str,
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.application_id = application_id
        actions = (
            ("APPROVE", discord.ButtonStyle.success),
            ("REJECT", discord.ButtonStyle.danger),
            ("FLAG", discord.ButtonStyle.secondary),
        )
        for action, style in actions:
            button = discord.ui.Button(
                label=action,
                style=style,
                custom_id=f"axis:join:{action.lower()}:{application_id}",
                disabled=(
                    status not in {"PENDING", "FLAGGED"}
                    or (status == "FLAGGED" and action == "FLAG")
                ),
            )
            button.callback = self._callback(action)
            self.add_item(button)

    def _callback(self, action: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self.controller.review_application(interaction, self.application_id, action)

        return callback


class NewcomerAccessCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        guild_id: int,
        owner_user_id: int | None,
        manager_role_id: int,
        member_role_id: int,
        newcomer_role_id: int,
        join_review_channel_id: int,
        system_alerts_channel_id: int,
        service: NewcomerAccessService,
        access_service: MembershipAccessService,
        risk_scanner: NewcomerRiskScanner,
        free_trial_calendar_days: int = 7,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self.manager_role_id = manager_role_id
        self.member_role_id = member_role_id
        self.newcomer_role_id = newcomer_role_id
        self.join_review_channel_id = join_review_channel_id
        self.system_alerts_channel_id = system_alerts_channel_id
        self.service = service
        self.access_service = access_service
        self.risk_scanner = risk_scanner
        self.free_trial_calendar_days = free_trial_calendar_days
        self._ready = False
        self.reconcile_loop.start()
        self.security_loop.start()

    def cog_unload(self) -> None:
        self.reconcile_loop.cancel()
        self.security_loop.cancel()

    async def begin_application(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "This application does not belong to the current AXIS server.", ephemeral=True
            )
            return
        state = await self.service.application_state(self.guild_id, interaction.user.id)
        if state in {"PENDING", "FLAGGED"}:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="AXIS APPLICATION",
                    description="Your application is already under review.",
                    color=0x111411,
                ),
                ephemeral=True,
            )
            return
        if state == "APPROVED":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="AXIS APPLICATION",
                    description="Your AXIS access application has already been approved.",
                    color=0x111411,
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="AXIS ACCESS APPLICATION",
                description=(
                    "This short application helps AXIS protect the community.\n\n"
                    "Select your answers below, then continue."
                ),
                color=0x86F7A8,
            ),
            view=ApplicationFormView(self, interaction.user.id),
            ephemeral=True,
        )

    async def deny_restricted_action(self, interaction: discord.Interaction) -> None:
        profile = await self.service.profile(self.guild_id, interaction.user.id)
        if profile is not None and profile.approved and profile.role_sync_status != "SYNCED":
            embed = discord.Embed(
                title="AXIS ACCESS",
                description=(
                    "Your application is approved. AXIS is synchronizing your Discord access.\n\n"
                    "Please try again shortly. No second application is required."
                ),
                color=0x111411,
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if interaction.response.is_done():
            await interaction.followup.send(
                embed=access_required_embed(), view=ApplyAccessView(self), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=access_required_embed(), view=ApplyAccessView(self), ephemeral=True
            )

    async def approval_required(self, user_id: int) -> bool:
        profile = await self.service.profile(self.guild_id, user_id)
        return (
            profile is None
            or not profile.approved
            or profile.role_sync_status != "SYNCED"
        )

    async def submit_application(
        self,
        interaction: discord.Interaction,
        answers: ApplicationAnswers,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        try:
            application = await self.service.submit_application(
                self.guild_id,
                member.id,
                username=str(member),
                display_name=getattr(member, "display_name", str(member)),
                discovery_source=answers.discovery_source or "",
                referred_by=answers.referred_by,
                interests=answers.interests,
                interaction_id=interaction.id,
            )
            created_at = getattr(member, "created_at", discord.utils.snowflake_time(member.id))
            risk = await self.risk_scanner.scan(
                self.guild_id,
                member.id,
                username=str(member),
                display_name=getattr(member, "display_name", str(member)),
                account_created_at=created_at,
                application_id=application.id,
            )
            await self._dispatch_risk_alerts(member.id, risk.flags)
            await self.ensure_review_card(application.id)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="AXIS APPLICATION",
                    description=(
                        "Your application has been submitted.\n\n"
                        "A member of the AXIS team will review it.\n\n"
                        "If approved, your 7-day free member access will begin automatically.\n\n"
                        "No credit card is required."
                    ),
                    color=0x86F7A8,
                ),
                ephemeral=True,
            )
        except NewcomerAccessError as exc:
            message = {
                "APPLICATION_ALREADY_PENDING": "Your application is already under review.",
                "APPLICATION_ALREADY_APPROVED": "Your AXIS application is already approved.",
            }.get(exc.code, "Your application could not be submitted. Please try again.")
            await interaction.followup.send(
                embed=discord.Embed(title="AXIS APPLICATION", description=message, color=0x111411),
                ephemeral=True,
            )

    async def review_application(
        self,
        interaction: discord.Interaction,
        application_id: uuid.UUID,
        action: str,
    ) -> None:
        if not await self._authorize_manager(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        target = {
            "APPROVE": AccessApplicationStatus.APPROVED.value,
            "REJECT": AccessApplicationStatus.REJECTED.value,
            "FLAG": AccessApplicationStatus.FLAGGED.value,
        }[action]
        try:
            application = await self.service.review(
                application_id,
                action=target,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            trial_message = ""
            if target == AccessApplicationStatus.APPROVED.value:
                trial_created = False
                try:
                    await self.access_service.claim_free_trial(
                        self.guild_id,
                        application.user_id,
                        interaction_id=interaction.id,
                        application_id=application.id,
                        approved_by_user_id=interaction.user.id,
                    )
                    trial_created = True
                except MembershipAccessError as exc:
                    if exc.code != "FREE_TRIAL_ALREADY_CLAIMED":
                        raise
                try:
                    await self.sync_user_roles(
                        application.user_id,
                        approved=True,
                        actor_user_id=interaction.user.id,
                    )
                    await self.service.mark_role_sync(
                        self.guild_id,
                        application.user_id,
                        status="SYNCED",
                        actor_user_id=interaction.user.id,
                    )
                except (discord.HTTPException, NewcomerAccessError) as exc:
                    await self.service.mark_role_sync(
                        self.guild_id,
                        application.user_id,
                        status="FAILED",
                        error_code=type(exc).__name__,
                        actor_user_id=interaction.user.id,
                    )
                    await report_system_failure(
                        self.bot,
                        severity="ERROR",
                        service="Newcomer Security",
                        error_type="ROLE_SYNC_FAILED",
                        affected=f"Discord User {application.user_id}",
                        detail="Approval persisted; Discord role reconciliation is pending.",
                    )
                trial_message = (
                    " The 7-day Free Trial started automatically."
                    if trial_created
                    else " No second Free Trial was created because permanent history exists."
                )
            await self.ensure_review_card(application.id)
            await interaction.followup.send(
                f"Application {application.status}.{trial_message}", ephemeral=True
            )
        except (NewcomerAccessError, MembershipAccessError) as exc:
            await interaction.followup.send(f"Review not completed: {exc.code}", ephemeral=True)

    async def sync_user_roles(
        self,
        user_id: int,
        *,
        approved: bool,
        actor_user_id: int,
    ) -> None:
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            raise NewcomerAccessError("GUILD_NOT_AVAILABLE")
        member = guild.get_member(user_id)
        if member is None:
            with suppress(discord.NotFound):
                member = await guild.fetch_member(user_id)
        if member is None:
            return
        newcomer_role = guild.get_role(self.newcomer_role_id)
        member_role = guild.get_role(self.member_role_id)
        if newcomer_role is None or member_role is None:
            raise NewcomerAccessError("ONBOARDING_ROLE_NOT_FOUND")
        if approved:
            if newcomer_role in member.roles:
                await member.remove_roles(newcomer_role, reason="AXIS application approved")
                await self.service.record_role_event(
                    self.guild_id,
                    user_id,
                    action="NEWCOMER_ROLE_REMOVED",
                    actor_user_id=actor_user_id,
                    role_name="Newcomer",
                )
            should_have_member = await self.access_service.should_have_access(
                self.guild_id, user_id
            )
            if should_have_member and member_role not in member.roles:
                await member.add_roles(member_role, reason="AXIS approved access active")
                await self.service.record_role_event(
                    self.guild_id,
                    user_id,
                    action="MEMBER_ROLE_ADDED",
                    actor_user_id=actor_user_id,
                    role_name="Member",
                )
            if not should_have_member and member_role in member.roles:
                await member.remove_roles(member_role, reason="AXIS entitlement inactive")
                await self.service.record_role_event(
                    self.guild_id,
                    user_id,
                    action="MEMBER_ROLE_REMOVED",
                    actor_user_id=actor_user_id,
                    role_name="Member",
                )
        else:
            if newcomer_role not in member.roles:
                await member.add_roles(newcomer_role, reason="AXIS onboarding required")
                await self.service.record_role_event(
                    self.guild_id,
                    user_id,
                    action="NEWCOMER_ROLE_ADDED",
                    actor_user_id=actor_user_id,
                    role_name="Newcomer",
                )
            if member_role in member.roles:
                await member.remove_roles(member_role, reason="AXIS approval required")
                await self.service.record_role_event(
                    self.guild_id,
                    user_id,
                    action="MEMBER_ROLE_REMOVED",
                    actor_user_id=actor_user_id,
                    role_name="Member",
                )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot or member.guild.id != self.guild_id or self.bot.user is None:
            return
        if await self.service.gate_activated_at(self.guild_id) is None:
            logger.warning("event=newcomer_join_before_gate_activation user_id=%s", member.id)
            return
        profile = await self.service.register_join(
            self.guild_id,
            member.id,
            username=str(member),
            display_name=member.display_name,
            joined_at=member.joined_at or datetime.now(UTC),
        )
        risk = await self.risk_scanner.scan(
            self.guild_id,
            member.id,
            username=str(member),
            display_name=member.display_name,
            account_created_at=member.created_at,
        )
        await self._dispatch_risk_alerts(member.id, risk.flags)
        await self.sync_user_roles(
            member.id,
            approved=profile.approved,
            actor_user_id=self.bot.user.id,
        )

    async def ensure_review_card(self, application_id: uuid.UUID) -> None:
        application = await self.service.get_application(application_id)
        if application is None:
            return
        guild = self.bot.get_guild(self.guild_id)
        if guild is None or self.bot.user is None:
            return
        member = guild.get_member(application.user_id)
        created_at = (
            member.created_at
            if member is not None
            else discord.utils.snowflake_time(application.user_id)
        )
        risk = await self.risk_scanner.scan(
            self.guild_id,
            application.user_id,
            username=application.username,
            display_name=application.display_name,
            account_created_at=created_at,
            application_id=application.id,
        )
        previous = await self.service.previous_application_status(
            self.guild_id, application.user_id, exclude_id=application.id
        )
        previous_trial = await self.service.has_trial_history(application.user_id)
        profile = await self.service.profile(self.guild_id, application.user_id)
        embed = self._review_embed(
            application,
            risk.flags,
            previous,
            previous_trial,
            created_at,
            profile.last_joined_at if profile is not None else application.submitted_at,
        )
        view = JoinReviewView(self, application.id, status=application.status)
        self.bot.add_view(view)
        channel = self.bot.get_channel(self.join_review_channel_id) or await self.bot.fetch_channel(
            self.join_review_channel_id
        )
        message = None
        if application.review_message_id:
            with suppress(discord.NotFound):
                message = await channel.fetch_message(application.review_message_id)
        if message is None:
            message = await channel.send(embed=embed, view=view)
            await self.service.attach_review_message(
                application.id,
                channel_id=channel.id,
                message_id=message.id,
            )
        else:
            await message.edit(embed=embed, view=view)

    @tasks.loop(minutes=5)
    async def reconcile_loop(self) -> None:
        if not self._ready:
            self.bot.add_view(ApplyAccessView(self))
            for application in await self.service.open_applications(self.guild_id):
                await self.ensure_review_card(application.id)
            self._ready = True
        guild = self.bot.get_guild(self.guild_id)
        if guild is None or self.bot.user is None:
            return
        for application in await self.service.approved_applications_without_trial(
            self.guild_id
        ):
            try:
                await self.access_service.claim_free_trial(
                    self.guild_id,
                    application.user_id,
                    interaction_id=None,
                    application_id=application.id,
                    approved_by_user_id=application.reviewed_by_user_id,
                )
            except MembershipAccessError as exc:
                if exc.code != "FREE_TRIAL_ALREADY_CLAIMED":
                    await report_system_failure(
                        self.bot,
                        severity="ERROR",
                        service="Newcomer Security",
                        error_type="FREE_TRIAL_RECOVERY_FAILED",
                        affected=f"Discord User {application.user_id}",
                        detail=(
                            "Approval is durable; automatic Free Trial reconciliation "
                            "will retry."
                        ),
                    )
        gate_activated_at = await self.service.gate_activated_at(self.guild_id)
        for member in guild.members:
            if member.bot:
                continue
            profile = await self.service.profile(self.guild_id, member.id)
            if profile is None:
                joined_at = member.joined_at
                if (
                    gate_activated_at is None
                    or joined_at is None
                    or joined_at < gate_activated_at
                ):
                    # Pre-gate users are handled by the explicit production baseline.
                    continue
                profile = await self.service.register_join(
                    self.guild_id,
                    member.id,
                    username=str(member),
                    display_name=member.display_name,
                    joined_at=joined_at,
                )
            try:
                await self.sync_user_roles(
                    member.id,
                    approved=profile.approved,
                    actor_user_id=self.bot.user.id,
                )
                if profile.role_sync_status != "SYNCED":
                    await self.service.mark_role_sync(
                        self.guild_id,
                        member.id,
                        status="SYNCED",
                        actor_user_id=self.bot.user.id,
                    )
            except (discord.HTTPException, NewcomerAccessError) as exc:
                await self.service.mark_role_sync(
                    self.guild_id,
                    member.id,
                    status="FAILED",
                    error_code=type(exc).__name__,
                    actor_user_id=self.bot.user.id,
                )

    @reconcile_loop.before_loop
    async def before_reconcile_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def security_loop(self) -> None:
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return
        for member in guild.members:
            if member.bot:
                continue
            profile = await self.service.profile(self.guild_id, member.id)
            if profile is None or profile.approved:
                continue
            risk = await self.risk_scanner.scan(
                self.guild_id,
                member.id,
                username=str(member),
                display_name=member.display_name,
                account_created_at=member.created_at,
            )
            await self._dispatch_risk_alerts(member.id, risk.flags)
        await self._ensure_security_status()

    @security_loop.before_loop
    async def before_security_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _dispatch_risk_alerts(
        self, user_id: int, flags: tuple[RiskFlagSnapshot, ...]
    ) -> None:
        active_codes = {flag.risk_code for flag in flags}
        for flag in flags:
            if flag.severity != "HIGH":
                continue
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Newcomer Security",
                error_type=flag.risk_code,
                affected=f"Discord User {user_id}",
                detail=flag.details,
            )
        for code in {"VERY_NEW_ACCOUNT", "POSSIBLE_IMPERSONATION"} - active_codes:
            await report_system_recovery(
                self.bot,
                service="Newcomer Security",
                error_type=code,
                affected=f"Discord User {user_id}",
            )

    async def _ensure_security_status(self) -> None:
        metrics = await self.service.metrics(self.guild_id)
        embed = discord.Embed(
            title="AXIS SYSTEM STATUS",
            color=0xD6A86A if metrics.health == "ATTENTION" else 0x86F7A8,
        )
        embed.add_field(name="NEWCOMER SECURITY", value=metrics.health, inline=False)
        embed.add_field(name="Newcomers", value=str(metrics.newcomers), inline=True)
        embed.add_field(
            name="Pending Applications", value=str(metrics.pending_applications), inline=True
        )
        embed.add_field(
            name="Flagged Applications", value=str(metrics.flagged_applications), inline=True
        )
        embed.add_field(
            name="High-Risk Newcomers", value=str(metrics.high_risk_newcomers), inline=True
        )
        embed.add_field(
            name="Applications Approved Today", value=str(metrics.approved_today), inline=True
        )
        embed.add_field(
            name="Applications Rejected Today", value=str(metrics.rejected_today), inline=True
        )
        embed.set_footer(text="AXIS Newcomer Security Status v1")
        channel = self.bot.get_channel(
            self.system_alerts_channel_id
        ) or await self.bot.fetch_channel(self.system_alerts_channel_id)
        async with self.service.database.session() as session:
            config = await session.get(GuildConfig, self.guild_id)
            message_id = config.newcomer_status_message_id if config else None
        message = None
        if message_id:
            with suppress(discord.NotFound):
                message = await channel.fetch_message(message_id)
        if message is None:
            message = await channel.send(embed=embed)
            with suppress(discord.Forbidden):
                await message.pin(reason="AXIS Newcomer Security health")
            async with self.service.database.session() as session:
                config = await session.get(GuildConfig, self.guild_id)
                if config is not None:
                    config.newcomer_status_message_id = message.id
                    await session.commit()
        else:
            await message.edit(embed=embed)

    async def _authorize_manager(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        user = interaction.user
        allowed = (
            guild is not None
            and guild.id == self.guild_id
            and isinstance(user, discord.Member)
            and (
                user.id == guild.owner_id
                or user.id == self.owner_user_id
                or self.manager_role_id in {role.id for role in user.roles}
            )
        )
        if allowed:
            return True
        await interaction.response.send_message(
            "You do not have permission to review AXIS applications.", ephemeral=True
        )
        return False

    @staticmethod
    def _review_embed(
        application: ApplicationSnapshot,
        flags: tuple[RiskFlagSnapshot, ...],
        previous_status: str | None,
        previous_trial: bool,
        account_created_at: datetime,
        joined_at: datetime,
    ) -> discord.Embed:
        now = datetime.now(UTC)
        created = (
            account_created_at
            if account_created_at.tzinfo
            else account_created_at.replace(tzinfo=UTC)
        )
        age_days = max((now - created).days, 0)
        years, remaining_days = divmod(age_days, 365)
        months = remaining_days // 30
        age_text = f"{years} year(s) {months} month(s)" if years else f"{age_days} day(s)"
        icons = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "⚪"}
        risk_text = (
            "\n\n".join(
                f"{icons.get(flag.severity, '⚪')} **{flag.risk_code}**\n"
                f"{flag.details or 'No details.'}"
                for flag in flags
            )
            or "None"
        )
        embed = discord.Embed(title="AXIS JOIN REQUEST", color=0x86F7A8)
        embed.add_field(
            name="User",
            value=f"<@{application.user_id}>\n`{application.user_id}`",
            inline=False,
        )
        embed.add_field(name="Discord Account Age", value=age_text, inline=True)
        embed.add_field(
            name="Joined AXIS",
            value=joined_at.astimezone(ET).strftime("%b %d, %Y"),
            inline=True,
        )
        embed.add_field(
            name="Source",
            value=DISCOVERY_SOURCES.get(application.discovery_source, application.discovery_source),
            inline=True,
        )
        embed.add_field(name="Referred By", value=application.referred_by or "None", inline=True)
        embed.add_field(
            name="Interests",
            value=" · ".join(INTEREST_LABELS.get(item, item) for item in application.interests),
            inline=True,
        )
        embed.add_field(name="Previous Application", value=previous_status or "None", inline=True)
        embed.add_field(name="Previous Trial", value="Yes" if previous_trial else "No", inline=True)
        embed.add_field(
            name="Risk Acknowledgement",
            value="Accepted" if application.risk_acknowledged else "Missing",
            inline=True,
        )
        embed.add_field(
            name="Community Safety",
            value="Accepted" if application.community_rules_acknowledged else "Missing",
            inline=True,
        )
        embed.add_field(name="Risk Flags", value=risk_text[:1024], inline=False)
        embed.add_field(name="Status", value=application.status, inline=False)
        embed.set_footer(text=f"AXIS Join Review · {application.id}")
        return embed
