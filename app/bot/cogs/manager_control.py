from __future__ import annotations

import logging
from contextlib import suppress

import discord
from discord.ext import commands, tasks
from sqlalchemy import select

from app.bot.cards import build_official_result_embed
from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.bot.views.management_views import MemberControlView, MentorControlView
from app.db.models import GuildConfig
from app.services.membership_management import MembershipError, MembershipManagementService
from app.services.mentor_management import MentorError, MentorManagementService
from app.services.official_results import OfficialResultsService, ResultsError

logger = logging.getLogger(__name__)


class ManagerControlCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        guild_id: int,
        owner_user_id: int | None,
        manager_role_id: int,
        member_role_id: int,
        mentor_channel_id: int,
        member_channel_id: int,
        mentor_service: MentorManagementService,
        membership_service: MembershipManagementService,
        results_service: OfficialResultsService,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self.manager_role_id = manager_role_id
        self.member_role_id = member_role_id
        self.mentor_channel_id = mentor_channel_id
        self.member_channel_id = member_channel_id
        self.mentor_service = mentor_service
        self.membership_service = membership_service
        self.results_service = results_service
        self._views_registered = False
        self._panels_ready = False
        self._member_import_complete = False
        self._role_expectations: dict[int, bool] = {}
        self.control_loop.start()
        self.membership_loop.start()
        self.results_loop.start()

    def cog_unload(self) -> None:
        self.control_loop.cancel()
        self.membership_loop.cancel()
        self.results_loop.cancel()

    async def authorize(self, interaction: discord.Interaction) -> bool:
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
        if interaction.response.is_done():
            await interaction.followup.send("你没有管理权限。", ephemeral=True)
        else:
            await interaction.response.send_message("你没有管理权限。", ephemeral=True)
        return False

    async def handle_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        if isinstance(exc, (MentorError, MembershipError, ResultsError)):
            message = f"操作未完成：{exc.code}"
        elif isinstance(exc, ValueError):
            message = f"输入格式不正确：{exc}"
        elif isinstance(exc, discord.HTTPException):
            message = "Discord 操作失败，请稍后重试。"
        else:
            message = "操作暂时失败，请稍后重试。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @tasks.loop(seconds=15)
    async def control_loop(self) -> None:
        try:
            if not self._views_registered:
                self.bot.add_view(MentorControlView(self))
                self.bot.add_view(MemberControlView(self))
                self._views_registered = True
            if not self._panels_ready:
                await self._ensure_panels()
                self._panels_ready = True
        except Exception as exc:
            logger.warning("event=control_loop_failed error_type=%s", type(exc).__name__)
            return

    @control_loop.before_loop
    async def before_control_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def membership_loop(self) -> None:
        try:
            guild = self.bot.get_guild(self.guild_id)
            if guild is None or self.bot.user is None:
                return
            role = guild.get_role(self.member_role_id)
            if role is None:
                return
            if not self._member_import_complete:
                for member in guild.members:
                    if role in member.roles:
                        await self.membership_service.import_role_holder(
                            self.guild_id,
                            member.id,
                            actor_user_id=self.bot.user.id,
                        )
                self._member_import_complete = True
            await self.membership_service.process_due(self.guild_id, actor_user_id=self.bot.user.id)
            active = await self.membership_service.active_user_ids(self.guild_id)
            for member in guild.members:
                should_have = member.id in active
                has_role = role in member.roles
                if should_have != has_role:
                    await self.sync_member_role(member.id, should_have)
            for user_id, expected in list(self._role_expectations.items()):
                member = guild.get_member(user_id)
                if member is None:
                    self._role_expectations.pop(user_id, None)
                    continue
                if (role in member.roles) == expected:
                    self._role_expectations.pop(user_id, None)
            await report_system_recovery(
                self.bot,
                service="Membership Expiry Job",
                error_type="MEMBERSHIP_EXPIRY_FAILED",
                affected="Membership Role Sync",
            )
        except Exception as exc:
            logger.warning("event=membership_loop_failed error_type=%s", type(exc).__name__)
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Membership Expiry Job",
                error_type="MEMBERSHIP_EXPIRY_FAILED",
                affected="Membership Role Sync",
                detail=type(exc).__name__,
            )
            return

    @membership_loop.before_loop
    async def before_membership_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=10)
    async def results_loop(self) -> None:
        try:
            if self.bot.user is None:
                return
            trade_id = await self.results_service.next_unpublished(self.guild_id)
            if trade_id is None:
                return
            result = await self.results_service.calculate(trade_id)
            channel = self.bot.get_channel(result.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(result.channel_id)
            send = getattr(channel, "send", None)
            history = getattr(channel, "history", None)
            if send is None or history is None:
                return
            marker = f"AXIS Result · {result.public_trade_id}"
            message = None
            async for candidate in history(limit=200):
                if candidate.author.id != self.bot.user.id:
                    continue
                if any(embed.footer.text == marker for embed in candidate.embeds):
                    message = candidate
                    break
            if message is None:
                message = await send(embed=build_official_result_embed(result))
            await self.results_service.attach_message(
                trade_id,
                message_id=message.id,
                final_return_pct=result.final_return_pct,
                actor_user_id=self.bot.user.id,
            )
        except Exception as exc:
            logger.warning("event=results_loop_failed error_type=%s", type(exc).__name__)
            return

    @results_loop.before_loop
    async def before_results_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def sync_member_role(self, user_id: int, should_have: bool) -> None:
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return
        role = guild.get_role(self.member_role_id)
        if role is None:
            return
        member = guild.get_member(user_id)
        if member is None:
            with suppress(discord.NotFound):
                member = await guild.fetch_member(user_id)
        if member is None:
            return
        has_role = role in member.roles
        if has_role == should_have:
            return
        self._role_expectations[user_id] = should_have
        if should_have:
            await member.add_roles(role, reason="AXIS membership active")
        else:
            await member.remove_roles(role, reason="AXIS membership inactive")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.guild.id != self.guild_id or self.bot.user is None:
            return
        before_has = self.member_role_id in {role.id for role in before.roles}
        after_has = self.member_role_id in {role.id for role in after.roles}
        if before_has == after_has:
            return
        expected = self._role_expectations.pop(after.id, None)
        if expected is not None and expected == after_has:
            return
        await self.membership_service.sync_manual_role(
            self.guild_id,
            after.id,
            has_role=after_has,
            actor_user_id=self.owner_user_id or self.bot.user.id,
        )

    async def _ensure_panels(self) -> None:
        mentor_embed = discord.Embed(
            title="AXIS Mentor Control",
            description="选择、创建、编辑、停用或恢复 Mentor。",
            color=0x86F7A8,
        )
        mentor_embed.set_footer(text="AXIS Mentor Control v1")
        member_embed = discord.Embed(
            title="AXIS Member Control",
            description="查找、赠送、延期、到期取消或立即移除会员。",
            color=0x86F7A8,
        )
        member_embed.set_footer(text="AXIS Member Control v1")
        await self._ensure_panel(
            channel_id=self.mentor_channel_id,
            config_field="mentor_panel_message_id",
            marker="AXIS Mentor Control v1",
            embed=mentor_embed,
            view=MentorControlView(self),
        )
        await self._ensure_panel(
            channel_id=self.member_channel_id,
            config_field="member_panel_message_id",
            marker="AXIS Member Control v1",
            embed=member_embed,
            view=MemberControlView(self),
        )

    async def _ensure_panel(
        self,
        *,
        channel_id: int,
        config_field: str,
        marker: str,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> None:
        database = self.membership_service.database
        async with database.session() as session:
            config = await session.get(GuildConfig, self.guild_id)
            if config is None:
                return
            saved_message_id = getattr(config, config_field)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        fetch_message = getattr(channel, "fetch_message", None)
        history = getattr(channel, "history", None)
        send = getattr(channel, "send", None)
        if fetch_message is None or history is None or send is None:
            return
        message = None
        if saved_message_id is not None:
            with suppress(discord.NotFound, discord.Forbidden):
                message = await fetch_message(saved_message_id)
        if message is None:
            async for candidate in history(limit=100):
                if self.bot.user is None or candidate.author.id != self.bot.user.id:
                    continue
                if any(embed.footer.text == marker for embed in candidate.embeds):
                    message = candidate
                    break
        if message is None:
            message = await send(embed=embed, view=view)
        else:
            await message.edit(embed=embed, view=view)
        async with database.session() as session:
            config = await session.scalar(
                select(GuildConfig).where(GuildConfig.guild_id == self.guild_id).with_for_update()
            )
            if config is not None and getattr(config, config_field) != message.id:
                setattr(config, config_field, message.id)
                await session.commit()
