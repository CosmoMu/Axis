from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from app.services.membership_management import MembershipSnapshot
from app.services.mentor_management import MentorSnapshot, MentorTrade

if TYPE_CHECKING:
    from app.bot.cogs.manager_control import ManagerControlCog


def _aliases(raw: str) -> list[str]:
    return [value.strip() for value in raw.replace("，", ",").split(",") if value.strip()]


def _duration(raw: str) -> int | None:
    normalized = raw.strip().upper().replace(" DAYS", "").replace(" DAY", "")
    if normalized in {"LIFETIME", "永久", "NONE"}:
        return None
    if normalized.startswith("CUSTOM:"):
        normalized = normalized.split(":", 1)[1].strip()
    days = int(normalized)
    if not 1 <= days <= 3650:
        raise ValueError("DURATION_INVALID")
    return days


def mentor_embed(mentor: MentorSnapshot) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mentor.name} · {mentor.short_code}",
        description="Active" if mentor.is_active else "Inactive",
        color=0x86F7A8 if mentor.is_active else 0x9A9F9B,
    )
    embed.add_field(name="Aliases", value=", ".join(mentor.aliases) or "—", inline=False)
    embed.add_field(
        name="当前订单",
        value=(
            "\n".join(
                f"{trade.public_trade_id} · {trade.ticker} · {trade.state}"
                for trade in mentor.active_trades[:15]
            )
            or "—"
        ),
        inline=False,
    )
    embed.add_field(
        name="历史订单",
        value=(
            "\n".join(
                f"{trade.public_trade_id} · {trade.ticker} · {trade.state}"
                for trade in mentor.historical_trades[:15]
            )
            or "—"
        ),
        inline=False,
    )
    embed.set_footer(text=f"AXIS Mentor ID: {mentor.id}")
    return embed


def _discord_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    return f"<t:{int(value.timestamp())}:F>"


def membership_embed(
    snapshot: MembershipSnapshot | None,
    user_id: int,
    *,
    member: discord.Member | discord.User | None = None,
    has_member_role: bool | None = None,
) -> discord.Embed:
    display_name = member.display_name if member is not None else str(user_id)
    embed = discord.Embed(title=f"Member · {display_name}", color=0x86F7A8)
    embed.add_field(name="Discord User", value=f"<@{user_id}>\n`{user_id}`", inline=False)
    joined_at = member.joined_at if isinstance(member, discord.Member) else None
    embed.add_field(name="加入服务器时间", value=_discord_time(joined_at), inline=False)
    if has_member_role is not None:
        embed.add_field(
            name="Member Role",
            value="Active" if has_member_role else "Not Assigned",
            inline=True,
        )
    if snapshot is None:
        embed.add_field(name="会员状态", value="NO MEMBERSHIP RECORD", inline=True)
        embed.add_field(name="加入会员时间", value="—", inline=False)
        embed.add_field(name="到期日期", value="—", inline=False)
        return embed
    embed.add_field(name="会员状态", value=snapshot.status, inline=True)
    embed.add_field(name="会员来源", value=snapshot.source, inline=True)
    embed.add_field(name="Entitlements", value=str(snapshot.entitlement_count), inline=True)
    embed.add_field(name="加入会员时间", value=_discord_time(snapshot.starts_at), inline=False)
    embed.add_field(
        name="到期日期",
        value="Lifetime" if snapshot.ends_at is None else _discord_time(snapshot.ends_at),
        inline=False,
    )
    embed.add_field(
        name="到期时取消",
        value="Yes" if snapshot.cancel_at_period_end else "No",
        inline=True,
    )
    embed.set_footer(text=f"AXIS Membership ID: {snapshot.id} · v{snapshot.version}")
    return embed


class MentorModal(discord.ui.Modal):
    def __init__(self, controller: ManagerControlCog, mentor: MentorSnapshot | None = None) -> None:
        super().__init__(
            title=("编辑 Mentor" if mentor else "新增 Mentor"),
            timeout=300,
            custom_id=(
                f"axis:mentor:modal:{mentor.id.hex}" if mentor else "axis:mentor:add:modal:v1"
            ),
        )
        self.controller = controller
        self.mentor = mentor
        self.name = discord.ui.TextInput(
            label="Mentor Name", default=mentor.name if mentor else "", max_length=100
        )
        self.short_code = discord.ui.TextInput(
            label="Short Code",
            default=mentor.short_code if mentor else "",
            max_length=24,
        )
        self.aliases = discord.ui.TextInput(
            label="Aliases（逗号分隔，可留空）",
            default=", ".join(mentor.aliases) if mentor else "",
            required=False,
            max_length=500,
        )
        self.add_item(self.name)
        self.add_item(self.short_code)
        self.add_item(self.aliases)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            if self.mentor is None:
                snapshot = await self.controller.mentor_service.create(
                    self.controller.guild_id,
                    name=self.name.value,
                    short_code=self.short_code.value,
                    aliases=_aliases(self.aliases.value),
                    actor_user_id=interaction.user.id,
                    interaction_id=interaction.id,
                )
            else:
                snapshot = await self.controller.mentor_service.edit(
                    self.mentor.id,
                    name=self.name.value,
                    short_code=self.short_code.value,
                    aliases=_aliases(self.aliases.value),
                    actor_user_id=interaction.user.id,
                    interaction_id=interaction.id,
                )
            await interaction.followup.send(embed=mentor_embed(snapshot), ephemeral=True)
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MentorSelect(discord.ui.Select):
    def __init__(
        self,
        controller: ManagerControlCog,
        mentors: list[MentorSnapshot],
    ) -> None:
        self.controller = controller
        super().__init__(
            placeholder="选择 Mentor",
            options=[
                discord.SelectOption(
                    label=mentor.name[:100],
                    value=str(mentor.id),
                    description=(
                        f"{mentor.short_code} · {'Active' if mentor.is_active else 'Inactive'}"
                    )[:100],
                )
                for mentor in mentors[:25]
            ],
            custom_id="axis:mentor:select:menu:view:v1",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            mentor = await self.controller.mentor_service.get(uuid.UUID(self.values[0]))
            await interaction.response.send_message(
                embed=mentor_embed(mentor),
                view=MentorDetailView(self.controller, mentor),
                ephemeral=True,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MentorSelectView(discord.ui.View):
    def __init__(
        self,
        controller: ManagerControlCog,
        mentors: list[MentorSnapshot],
    ) -> None:
        super().__init__(timeout=180)
        self.add_item(MentorSelect(controller, mentors))


class MentorDetailView(discord.ui.View):
    def __init__(self, controller: ManagerControlCog, mentor: MentorSnapshot) -> None:
        super().__init__(timeout=180)
        self.controller = controller
        self.mentor = mentor
        edit = discord.ui.Button(label="编辑", style=discord.ButtonStyle.primary)
        edit.callback = self.edit
        toggle = discord.ui.Button(
            label="停用" if mentor.is_active else "恢复",
            style=(discord.ButtonStyle.danger if mentor.is_active else discord.ButtonStyle.success),
        )
        toggle.callback = self.toggle
        reassign = discord.ui.Button(label="修改订单 Mentor", style=discord.ButtonStyle.secondary)
        reassign.callback = self.reassign
        delete = discord.ui.Button(label="删除 Mentor", style=discord.ButtonStyle.danger)
        delete.callback = self.delete
        self.add_item(edit)
        self.add_item(toggle)
        self.add_item(reassign)
        self.add_item(delete)

    async def edit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MentorModal(self.controller, self.mentor))

    async def toggle(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            mentor = await self.controller.mentor_service.set_active(
                self.mentor.id,
                is_active=not self.mentor.is_active,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await interaction.followup.send(embed=mentor_embed(mentor), ephemeral=True)
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)

    async def reassign(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        trades = [*self.mentor.active_trades, *self.mentor.historical_trades]
        if not trades:
            await interaction.response.send_message(
                "该 Mentor 当前没有可修改的订单。", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "请选择要修改 Mentor 的订单：",
            view=TradeReassignView(self.controller, trades),
            ephemeral=True,
        )

    async def delete(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.send_message(
            f"确认永久删除 Mentor **{self.mentor.name}**？"
            "已有 Draft、Trade 或 Analysis 时会被阻止。",
            view=DeleteMentorConfirmView(self.controller, self.mentor),
            ephemeral=True,
        )


class DeleteMentorConfirmView(discord.ui.View):
    def __init__(self, controller: ManagerControlCog, mentor: MentorSnapshot) -> None:
        super().__init__(timeout=120)
        self.controller = controller
        self.mentor = mentor
        confirm = discord.ui.Button(
            label="确认删除 Mentor",
            style=discord.ButtonStyle.danger,
        )
        confirm.callback = self.confirm
        cancel = discord.ui.Button(label="取消", style=discord.ButtonStyle.secondary)
        cancel.callback = self.cancel
        self.add_item(confirm)
        self.add_item(cancel)

    async def confirm(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.controller.mentor_service.delete(
                self.mentor.id,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await interaction.followup.send(
                f"Mentor **{self.mentor.name}** 已永久删除。",
                ephemeral=True,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)

    async def cancel(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.edit_message(content="已取消删除 Mentor。", view=None)


class TradeReassignSelect(discord.ui.Select):
    def __init__(self, controller: ManagerControlCog, trades: list[MentorTrade]) -> None:
        self.controller = controller
        super().__init__(
            placeholder="选择订单",
            options=[
                discord.SelectOption(
                    label=trade.public_trade_id[:100],
                    value=str(trade.trade_id),
                    description=f"{trade.ticker} · {trade.state}"[:100],
                )
                for trade in trades[:25]
            ],
            custom_id="axis:mentor:reassign:trade:v1",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        mentors = [
            mentor
            for mentor in await self.controller.mentor_service.list(self.controller.guild_id)
            if mentor.is_active
        ]
        if not mentors:
            await interaction.response.send_message("当前没有 Active Mentor。", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="请选择新的 Mentor：",
            view=MentorTargetView(self.controller, uuid.UUID(self.values[0]), mentors),
        )


class TradeReassignView(discord.ui.View):
    def __init__(self, controller: ManagerControlCog, trades: list[MentorTrade]) -> None:
        super().__init__(timeout=180)
        self.add_item(TradeReassignSelect(controller, trades))


class MentorTargetSelect(discord.ui.Select):
    def __init__(
        self,
        controller: ManagerControlCog,
        trade_id: uuid.UUID,
        mentors: list[MentorSnapshot],
    ) -> None:
        self.controller = controller
        self.trade_id = trade_id
        super().__init__(
            placeholder="选择新的 Mentor",
            options=[
                discord.SelectOption(
                    label=mentor.name[:100],
                    value=str(mentor.id),
                    description=mentor.short_code[:100],
                )
                for mentor in mentors[:25]
            ],
            custom_id="axis:mentor:reassign:target:v1",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            mentor = await self.controller.mentor_service.reassign_trade(
                self.trade_id,
                mentor_id=uuid.UUID(self.values[0]),
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await interaction.followup.send(
                "订单 Mentor 已更新。", embed=mentor_embed(mentor), ephemeral=True
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MentorTargetView(discord.ui.View):
    def __init__(
        self,
        controller: ManagerControlCog,
        trade_id: uuid.UUID,
        mentors: list[MentorSnapshot],
    ) -> None:
        super().__init__(timeout=180)
        self.add_item(MentorTargetSelect(controller, trade_id, mentors))


class MentorControlView(discord.ui.View):
    def __init__(self, controller: ManagerControlCog) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        for label, custom_id, callback, style in (
            ("选择 Mentor", "axis:mentor:select:v1", self.select, discord.ButtonStyle.secondary),
            ("新增 Mentor", "axis:mentor:add:v1", self.add, discord.ButtonStyle.success),
        ):
            button = discord.ui.Button(label=label, custom_id=custom_id, style=style)
            button.callback = callback
            self.add_item(button)

    async def _select(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        mentors = await self.controller.mentor_service.list(self.controller.guild_id)
        if not mentors:
            await interaction.response.send_message("当前没有 Mentor，请先新增。", ephemeral=True)
            return
        await interaction.response.send_message(
            "请选择 Mentor：",
            view=MentorSelectView(self.controller, mentors),
            ephemeral=True,
        )

    async def select(self, interaction: discord.Interaction) -> None:
        await self._select(interaction)

    async def add(self, interaction: discord.Interaction) -> None:
        if await self.controller.authorize(interaction):
            await interaction.response.send_modal(MentorModal(self.controller))


class MemberGiftModal(discord.ui.Modal):
    def __init__(self, controller: ManagerControlCog, user_id: int) -> None:
        super().__init__(title="赠送会员")
        self.controller = controller
        self.user_id = user_id
        self.duration = discord.ui.TextInput(
            label="7 / 30 / 90 / LIFETIME",
            placeholder="30",
        )
        self.add_item(self.duration)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            snapshot = await self.controller.membership_service.grant(
                self.controller.guild_id,
                self.user_id,
                days=_duration(self.duration.value),
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.sync_member_role(self.user_id, snapshot.is_active)
            member = await _selected_member(interaction, self.user_id)
            await interaction.followup.send(
                embed=_member_info_embed(self.controller, member, snapshot),
                ephemeral=True,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MemberRemoveModal(discord.ui.Modal):
    def __init__(self, controller: ManagerControlCog, user_id: int) -> None:
        super().__init__(title="确认移除会员")
        self.controller = controller
        self.user_id = user_id
        self.reason = discord.ui.TextInput(
            label="Reason", required=False, default="manager_revoke", max_length=200
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            snapshot = await self.controller.membership_service.remove(
                self.controller.guild_id,
                self.user_id,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
                reason=self.reason.value or "manager_revoke",
            )
            await self.controller.sync_member_role(self.user_id, False)
            member = await _selected_member(interaction, self.user_id)
            await interaction.followup.send(
                embed=_member_info_embed(self.controller, member, snapshot, role_override=False),
                ephemeral=True,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


async def _selected_member(
    interaction: discord.Interaction,
    user_id: int,
) -> discord.Member | discord.User:
    guild = interaction.guild
    if guild is None:
        return interaction.user
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return await interaction.client.fetch_user(user_id)


def _member_info_embed(
    controller: ManagerControlCog,
    member: discord.Member | discord.User,
    snapshot: MembershipSnapshot | None,
    *,
    role_override: bool | None = None,
) -> discord.Embed:
    has_role = role_override
    if has_role is None and isinstance(member, discord.Member):
        has_role = controller.member_role_id in {role.id for role in member.roles}
    return membership_embed(
        snapshot,
        member.id,
        member=member,
        has_member_role=has_role,
    )


class MemberSearchSelect(discord.ui.UserSelect):
    def __init__(self, controller: ManagerControlCog) -> None:
        super().__init__(
            placeholder="搜索并选择服务器成员",
            min_values=1,
            max_values=1,
            custom_id="axis:member:user-select:v2",
        )
        self.controller = controller

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            member = self.values[0]
            snapshot = await self.controller.membership_service.get(
                self.controller.guild_id,
                member.id,
            )
            await interaction.response.send_message(
                embed=_member_info_embed(self.controller, member, snapshot),
                view=MemberDetailView(
                    self.controller,
                    member.id,
                    has_active_membership=snapshot is not None and snapshot.is_active,
                ),
                ephemeral=True,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MemberDetailView(discord.ui.View):
    def __init__(
        self,
        controller: ManagerControlCog,
        user_id: int,
        *,
        has_active_membership: bool,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.user_id = user_id
        definitions = (
            ("查看信息", discord.ButtonStyle.secondary, self.info, False),
            ("赠送会员", discord.ButtonStyle.success, self.gift, False),
            ("移除会员", discord.ButtonStyle.danger, self.remove, not has_active_membership),
        )
        for label, style, callback, disabled in definitions:
            button = discord.ui.Button(label=label, style=style, disabled=disabled)
            button.callback = callback
            self.add_item(button)

    async def info(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            snapshot = await self.controller.membership_service.get(
                self.controller.guild_id,
                self.user_id,
            )
            member = await _selected_member(interaction, self.user_id)
            await interaction.response.send_message(
                embed=_member_info_embed(self.controller, member, snapshot),
                ephemeral=True,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)

    async def gift(self, interaction: discord.Interaction) -> None:
        if await self.controller.authorize(interaction):
            await interaction.response.send_modal(MemberGiftModal(self.controller, self.user_id))

    async def remove(self, interaction: discord.Interaction) -> None:
        if await self.controller.authorize(interaction):
            await interaction.response.send_modal(MemberRemoveModal(self.controller, self.user_id))


class MemberControlView(discord.ui.View):
    def __init__(self, controller: ManagerControlCog) -> None:
        super().__init__(timeout=None)
        self.add_item(MemberSearchSelect(controller))
