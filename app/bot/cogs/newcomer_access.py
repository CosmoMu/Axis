from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.bot.member_welcomes import community_welcome_message, member_lounge_welcome_message
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

APPLICATION_STATUS_LABELS = {
    "PENDING": "待审核",
    "FLAGGED": "已标记",
    "APPROVED": "已批准",
    "REJECTED": "已拒绝",
}
RISK_CODE_LABELS = {
    "VERY_NEW_ACCOUNT": "Discord 账户注册时间不足 7 天",
    "NEW_ACCOUNT": "Discord 账户注册时间不足 30 天",
    "PREVIOUS_REJECTION": "曾有申请被拒绝",
    "PREVIOUS_FLAG": "曾有申请被标记",
    "TRIAL_ALREADY_USED": "已使用免费体验",
    "REJOIN_WITHOUT_APPROVAL": "未获批准重复加入",
    "POSSIBLE_IMPERSONATION": "疑似身份冒充",
}


def welcome_application_embed(*, trial_days: int = 3) -> discord.Embed:
    embed = discord.Embed(
        title="👋 欢迎来到 AXIS",
        description=(
            "**这里只是 AXIS 欢迎界面**\n\n"
            "看到这个页面并不代表你已经加入 AXIS。\n\n"
            "**如需加入，请点击下方绿色「申请加入 AXIS」按钮并提交申请。**"
        ),
        color=0x86F7A8,
    )
    embed.add_field(
        name="🚪 如何加入",
        value=(
            "1. 点击下方「申请加入 AXIS」按钮。\n"
            "2. 填写简短的加入申请。\n"
            "3. 提交后等待管理员审核。"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎁 审核通过后",
        value=(
            f"自动获得 **{trial_days} 个美国股票市场交易日**的完整会员权限。\n\n"
            "无需信用卡，不会自动续费。"
        ),
        inline=False,
    )
    embed.add_field(
        name="会员权限",
        value="⚡ 短线\n〽️ 波段\n♾️ 长期\n🛋️ 会员交流区",
        inline=False,
    )
    embed.add_field(
        name="风险提示",
        value=(
            "AXIS 仅提供市场研究与教育内容，不构成投资、财务或交易建议。\n"
            "交易存在风险，请独立判断并自行承担风险。"
        ),
        inline=False,
    )
    embed.add_field(
        name="安全提示",
        value=(
            "AXIS 工作人员绝不会主动私信索取私人付款、密码、券商账户信息、"
            "加密货币转账或远程访问权限。"
        ),
        inline=False,
    )
    embed.set_footer(text="AXIS 欢迎界面")
    return embed


def access_required_embed() -> discord.Embed:
    return discord.Embed(
        title="AXIS 访问权限",
        description=(
            "请先完成 AXIS 加入申请。\n\n"
            "审核通过后，你将自动获得 3 个美国股票市场交易日的完整会员权限。"
        ),
        color=0x111411,
    )


def risk_acknowledgement_embed() -> discord.Embed:
    return discord.Embed(
        title="风险确认",
        description=(
            "AXIS 提供的内容仅用于市场分析、研究与金融教育，"
            "不构成个性化投资、财务或交易建议。\n\n"
            "期权及其他金融市场具有较高风险，可能造成部分或全部本金损失。\n\n"
            "所有入场、离场、仓位和风险管理决定均由用户本人负责。\n\n"
            "历史表现不代表未来结果。\n\n"
            "**我的风险不等于你的风险。**"
        ),
        color=0x111411,
    )


def safety_agreement_embed() -> discord.Embed:
    return discord.Embed(
        title="社区安全协议",
        description=(
            "我同意不会：\n\n"
            "- 冒充 AXIS 工作人员\n"
            "- 诈骗、诱导或骚扰 AXIS 成员\n"
            "- 向成员索取私人付款\n"
            "- 发送垃圾信息或恶意私信成员\n"
            "- 转发或转售 AXIS 私密内容\n"
            "- 索取密码或券商账户信息\n"
            "- 索取远程账户访问权限"
        ),
        color=0x111411,
    )


class ApplyAccessView(discord.ui.View):
    def __init__(self, controller: NewcomerAccessCog) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        button = discord.ui.Button(
            label="申请加入 AXIS",
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
            placeholder="你是通过什么渠道了解到 AXIS 的？",
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
            placeholder="你主要对哪些内容感兴趣？",
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
        continue_button = discord.ui.Button(label="继续", style=discord.ButtonStyle.success)
        continue_button.callback = self.continue_application
        self.add_item(continue_button)

    async def _belongs_to_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "该申请属于其他用户。", ephemeral=True
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
                "请选择了解渠道和至少一项感兴趣的内容。", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ReferralModal(self.controller, self.user_id, self.answers)
        )


class ReferralModal(discord.ui.Modal, title="AXIS 加入申请"):
    referred_by = discord.ui.TextInput(
        label="谁推荐你加入 AXIS？（选填）",
        placeholder="可填写 Discord 用户名、昵称或推荐人名称",
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
                "该申请属于其他用户。", ephemeral=True
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
        button = discord.ui.Button(label="我已阅读并同意", style=discord.ButtonStyle.success)
        button.callback = self.agree
        self.add_item(button)

    async def agree(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("该确认不属于你。", ephemeral=True)
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
        button = discord.ui.Button(label="我已阅读并同意", style=discord.ButtonStyle.success)
        button.callback = self.agree
        self.add_item(button)

    async def agree(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("该确认不属于你。", ephemeral=True)
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
            ("APPROVE", "批准", discord.ButtonStyle.success),
            ("REJECT", "拒绝", discord.ButtonStyle.danger),
            ("FLAG", "标记", discord.ButtonStyle.secondary),
        )
        for action, label, style in actions:
            button = discord.ui.Button(
                label=label,
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
        lobby_channel_id: int,
        member_lounge_channel_id: int,
        short_term_channel_id: int,
        swing_channel_id: int,
        leaps_channel_id: int,
        system_alerts_channel_id: int,
        service: NewcomerAccessService,
        access_service: MembershipAccessService,
        risk_scanner: NewcomerRiskScanner,
        expect_member_role_change: Callable[[int, bool], None] | None = None,
        free_trial_trading_days: int = 3,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self.manager_role_id = manager_role_id
        self.member_role_id = member_role_id
        self.newcomer_role_id = newcomer_role_id
        self.join_review_channel_id = join_review_channel_id
        self.lobby_channel_id = lobby_channel_id
        self.member_lounge_channel_id = member_lounge_channel_id
        self.short_term_channel_id = short_term_channel_id
        self.swing_channel_id = swing_channel_id
        self.leaps_channel_id = leaps_channel_id
        self.system_alerts_channel_id = system_alerts_channel_id
        self.service = service
        self.access_service = access_service
        self.risk_scanner = risk_scanner
        self.expect_member_role_change = expect_member_role_change or (
            lambda _user_id, _state: None
        )
        self.free_trial_trading_days = free_trial_trading_days
        self._welcome_locks: dict[uuid.UUID, asyncio.Lock] = {}
        self._ready = False
        self.reconcile_loop.start()
        self.security_loop.start()

    def cog_unload(self) -> None:
        self.reconcile_loop.cancel()
        self.security_loop.cancel()

    async def begin_application(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "该申请不属于当前 AXIS 服务器。", ephemeral=True
            )
            return
        state = await self.service.application_state(self.guild_id, interaction.user.id)
        if state in {"PENDING", "FLAGGED"}:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="AXIS 加入申请",
                    description="你的申请已提交，正在等待审核。",
                    color=0x111411,
                ),
                ephemeral=True,
            )
            return
        if state == "APPROVED":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="AXIS 加入申请",
                    description="你的 AXIS 加入申请已经通过。",
                    color=0x111411,
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="AXIS 加入申请",
                description=(
                    "这份简短申请用于帮助 AXIS 维护社区安全。\n\n"
                    "请在下方选择答案，然后点击「继续」。"
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
                title="AXIS 访问权限",
                description=(
                    "你的申请已经通过，AXIS 正在同步 Discord 访问权限。\n\n"
                    "请稍后重试，无需重复提交申请。"
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
                    title="AXIS 加入申请",
                    description=(
                        "你的申请已提交。\n\n"
                        "AXIS 管理员将进行审核。\n\n"
                        "审核通过后，3 个美国股票市场交易日的免费会员权限将自动开始。\n\n"
                        "无需信用卡。"
                    ),
                    color=0x86F7A8,
                ),
                ephemeral=True,
            )
        except NewcomerAccessError as exc:
            message = {
                "APPLICATION_ALREADY_PENDING": "你的申请已提交，正在等待审核。",
                "APPLICATION_ALREADY_APPROVED": "你的 AXIS 加入申请已经通过。",
            }.get(exc.code, "申请暂时无法提交，请稍后重试。")
            await interaction.followup.send(
                embed=discord.Embed(title="AXIS 加入申请", description=message, color=0x111411),
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
            role_sync_succeeded = False
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
                    role_sync_succeeded = True
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
                    "已自动开始 3 个美国股票市场交易日的免费体验。"
                    if trial_created
                    else "已有永久免费体验记录，因此没有重复创建免费体验。"
                )
                if role_sync_succeeded:
                    await self.ensure_approval_welcomes(application)
            await self.ensure_review_card(application.id)
            status_label = APPLICATION_STATUS_LABELS.get(
                application.status, application.status
            )
            await interaction.followup.send(
                f"申请状态：{status_label}。{trial_message}",
                ephemeral=True,
            )
        except (NewcomerAccessError, MembershipAccessError) as exc:
            logger.warning(
                "event=application_review_failed application_id=%s error_code=%s",
                application_id,
                exc.code,
            )
            await interaction.followup.send(
                "审核暂时无法完成，请稍后重试。系统错误已记录。",
                ephemeral=True,
            )

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
                self.expect_member_role_change(user_id, True)
                await member.add_roles(member_role, reason="AXIS approved access active")
                await self.service.record_role_event(
                    self.guild_id,
                    user_id,
                    action="MEMBER_ROLE_ADDED",
                    actor_user_id=actor_user_id,
                    role_name="Member",
                )
            if not should_have_member and member_role in member.roles:
                self.expect_member_role_change(user_id, False)
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
                self.expect_member_role_change(user_id, False)
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

        for application in await self.service.approved_applications_pending_welcome(
            self.guild_id
        ):
            profile = await self.service.profile(self.guild_id, application.user_id)
            if profile is None or profile.role_sync_status != "SYNCED":
                continue
            if not await self.access_service.should_have_access(
                self.guild_id, application.user_id
            ):
                continue
            await self.ensure_approval_welcomes(application)

    async def ensure_approval_welcomes(self, application: ApplicationSnapshot) -> None:
        if application.status != AccessApplicationStatus.APPROVED.value or self.bot.user is None:
            return
        lock = self._welcome_locks.setdefault(application.id, asyncio.Lock())
        async with lock:
            current = await self.service.get_application(application.id)
            if current is None:
                return
            destinations = (
                ("LOBBY", self.lobby_channel_id, current.lobby_welcome_message_id),
                (
                    "MEMBER_LOUNGE",
                    self.member_lounge_channel_id,
                    current.member_lounge_welcome_message_id,
                ),
            )
            allowed_mentions = discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=True,
                replied_user=False,
            )
            for destination, channel_id, existing_message_id in destinations:
                if existing_message_id is not None:
                    continue
                try:
                    channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(
                        channel_id
                    )
                    content = (
                        community_welcome_message(current.user_id)
                        if destination == "LOBBY"
                        else member_lounge_welcome_message(
                            current.user_id,
                            short_term_channel_id=self.short_term_channel_id,
                            swing_channel_id=self.swing_channel_id,
                            leaps_channel_id=self.leaps_channel_id,
                        )
                    )
                    message = await channel.send(
                        content,
                        allowed_mentions=allowed_mentions,
                    )
                    await self.service.attach_approval_welcome_message(
                        current.id,
                        destination=destination,
                        message_id=message.id,
                        actor_user_id=self.bot.user.id,
                    )
                except (discord.HTTPException, NewcomerAccessError) as exc:
                    logger.exception(
                        "event=approval_welcome_failed user_id=%s destination=%s",
                        current.user_id,
                        destination,
                    )
                    await report_system_failure(
                        self.bot,
                        severity="ERROR",
                        service="Newcomer Security",
                        error_type="APPROVAL_WELCOME_FAILED",
                        affected=f"Discord User {current.user_id} · {destination}",
                        detail=type(exc).__name__,
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
            "你没有审核 AXIS 加入申请的权限。", ephemeral=True
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
        age_text = f"{years} 年 {months} 个月" if years else f"{age_days} 天"
        icons = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "⚪"}
        risk_text = (
            "\n\n".join(
                f"{icons.get(flag.severity, '⚪')} "
                f"**{RISK_CODE_LABELS.get(flag.risk_code, flag.risk_code)}**\n"
                f"{flag.details or '无详细信息。'}"
                for flag in flags
            )
            or "无"
        )
        embed = discord.Embed(title="AXIS 加入审核", color=0x86F7A8)
        embed.add_field(
            name="用户",
            value=f"<@{application.user_id}>\n`{application.user_id}`",
            inline=False,
        )
        embed.add_field(name="Discord 账号年龄", value=age_text, inline=True)
        embed.add_field(
            name="加入 AXIS 时间",
            value=joined_at.astimezone(ET).strftime("%Y年%m月%d日"),
            inline=True,
        )
        embed.add_field(
            name="了解渠道",
            value=DISCOVERY_SOURCES.get(application.discovery_source, application.discovery_source),
            inline=True,
        )
        embed.add_field(name="推荐人", value=application.referred_by or "无", inline=True)
        embed.add_field(
            name="感兴趣的内容",
            value=" · ".join(INTEREST_LABELS.get(item, item) for item in application.interests),
            inline=True,
        )
        embed.add_field(
            name="历史申请",
            value=APPLICATION_STATUS_LABELS.get(previous_status, previous_status or "无"),
            inline=True,
        )
        embed.add_field(name="历史免费体验", value="有" if previous_trial else "无", inline=True)
        embed.add_field(
            name="风险确认",
            value="已同意" if application.risk_acknowledged else "未完成",
            inline=True,
        )
        embed.add_field(
            name="社区安全协议",
            value="已同意" if application.community_rules_acknowledged else "未完成",
            inline=True,
        )
        embed.add_field(name="风险标记", value=risk_text[:1024], inline=False)
        embed.add_field(
            name="当前状态",
            value=APPLICATION_STATUS_LABELS.get(application.status, application.status),
            inline=False,
        )
        embed.set_footer(text=f"AXIS 加入审核 · {application.id}")
        return embed
