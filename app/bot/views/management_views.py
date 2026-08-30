from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord

from app.domain.enums import MembershipExtensionType
from app.services.membership_management import MembershipSnapshot
from app.services.mentor_management import MentorSnapshot, MentorTrade

if TYPE_CHECKING:
    from app.bot.cogs.manager_control import ManagerControlCog


def _aliases(raw: str) -> list[str]:
    return [value.strip() for value in raw.replace("，", ",").split(",") if value.strip()]


def _user_id(raw: str) -> int:
    match = re.fullmatch(r"\s*(?:<@!?)?(\d{15,22})>?\s*", raw)
    if match is None:
        raise ValueError("USER_ID_INVALID")
    return int(match.group(1))


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


def _expiry(raw: str) -> datetime | None:
    value = raw.strip()
    if not value or value in {"-", "—"}:
        return None
    try:
        if "T" in value or " " in value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            parsed = datetime.combine(
                datetime.fromisoformat(value).date(),
                time(23, 59, 59),
                tzinfo=ZoneInfo("America/New_York"),
            )
    except ValueError as exc:
        raise ValueError("EXPIRY_INVALID") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _extension(raw: str) -> tuple[str, int | None, datetime | None]:
    normalized = raw.strip().upper().replace(" ", "")
    if normalized.startswith("CUSTOM:"):
        return (
            MembershipExtensionType.CUSTOM.value,
            None,
            _expiry(normalized.split(":", 1)[1]),
        )
    suffixes = {
        "T": MembershipExtensionType.TRADING_DAYS.value,
        "C": MembershipExtensionType.CALENDAR_DAYS.value,
        "M": MembershipExtensionType.CALENDAR_MONTH.value,
    }
    suffix = normalized[-1:] if normalized else ""
    if suffix not in suffixes:
        raise ValueError("EXTENSION_FORMAT_INVALID")
    amount = int(normalized[:-1])
    if amount <= 0:
        raise ValueError("EXTENSION_AMOUNT_INVALID")
    return suffixes[suffix], amount, None


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


def membership_embed(snapshot: MembershipSnapshot | None, user_id: int) -> discord.Embed:
    embed = discord.Embed(title=f"Member · {user_id}", color=0x86F7A8)
    if snapshot is None:
        embed.description = "数据库中没有会员记录。"
        return embed
    ends_at = snapshot.ends_at
    embed.add_field(name="Status", value=snapshot.status, inline=True)
    embed.add_field(name="Source", value=snapshot.source, inline=True)
    embed.add_field(name="Entitlements", value=str(snapshot.entitlement_count), inline=True)
    embed.add_field(
        name="Ends At",
        value=ends_at.isoformat() if ends_at is not None else "Lifetime",
        inline=False,
    )
    embed.add_field(
        name="Cancel At Period End",
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
        *,
        edit: bool,
    ) -> None:
        self.controller = controller
        self.edit_mode = edit
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
            custom_id=f"axis:mentor:select:menu:{'edit' if edit else 'view'}:v1",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            mentor = await self.controller.mentor_service.get(uuid.UUID(self.values[0]))
            if self.edit_mode:
                await interaction.response.send_modal(MentorModal(self.controller, mentor))
            else:
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
        *,
        edit: bool,
    ) -> None:
        super().__init__(timeout=180)
        self.add_item(MentorSelect(controller, mentors, edit=edit))


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
        self.add_item(edit)
        self.add_item(toggle)
        self.add_item(reassign)

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
            ("编辑 Mentor", "axis:mentor:edit:v1", self.edit, discord.ButtonStyle.primary),
        ):
            button = discord.ui.Button(label=label, custom_id=custom_id, style=style)
            button.callback = callback
            self.add_item(button)

    async def _select(self, interaction: discord.Interaction, *, edit: bool) -> None:
        if not await self.controller.authorize(interaction):
            return
        mentors = await self.controller.mentor_service.list(self.controller.guild_id)
        if not mentors:
            await interaction.response.send_message("当前没有 Mentor，请先新增。", ephemeral=True)
            return
        await interaction.response.send_message(
            "请选择 Mentor：",
            view=MentorSelectView(self.controller, mentors, edit=edit),
            ephemeral=True,
        )

    async def select(self, interaction: discord.Interaction) -> None:
        await self._select(interaction, edit=False)

    async def add(self, interaction: discord.Interaction) -> None:
        if await self.controller.authorize(interaction):
            await interaction.response.send_modal(MentorModal(self.controller))

    async def edit(self, interaction: discord.Interaction) -> None:
        await self._select(interaction, edit=True)


class MemberLookupModal(discord.ui.Modal):
    def __init__(self, controller: ManagerControlCog) -> None:
        super().__init__(title="查找会员", custom_id="axis:member:lookup:modal:v1")
        self.controller = controller
        self.user = discord.ui.TextInput(label="Discord User ID 或 @mention")
        self.add_item(self.user)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = _user_id(self.user.value)
            snapshot = await self.controller.membership_service.get(
                self.controller.guild_id, user_id
            )
            await interaction.followup.send(
                embed=membership_embed(snapshot, user_id), ephemeral=True
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MemberDurationModal(discord.ui.Modal):
    def __init__(self, controller: ManagerControlCog, *, action: str) -> None:
        super().__init__(
            title="赠送会员" if action == "gift" else "延长会员",
            custom_id=f"axis:member:{action}:modal:v1",
        )
        self.controller = controller
        self.action = action
        self.user = discord.ui.TextInput(label="Discord User ID 或 @mention")
        self.duration = discord.ui.TextInput(
            label=(
                "7 / 30 / 90 / LIFETIME"
                if action == "gift"
                else "1T / 3T / 5T / 10T / 30C / 1M / CUSTOM"
            ),
            placeholder="30" if action == "gift" else "3T",
        )
        self.add_item(self.user)
        self.add_item(self.duration)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = _user_id(self.user.value)
            if self.action == "gift":
                snapshot = await self.controller.membership_service.grant(
                    self.controller.guild_id,
                    user_id,
                    days=_duration(self.duration.value),
                    actor_user_id=interaction.user.id,
                    interaction_id=interaction.id,
                )
            else:
                extension_type, amount, custom_expiry = _extension(self.duration.value)
                snapshot = await self.controller.membership_service.extend_access(
                    self.controller.guild_id,
                    user_id,
                    extension_type=extension_type,
                    amount=amount,
                    custom_expiry=custom_expiry,
                    actor_user_id=interaction.user.id,
                    interaction_id=interaction.id,
                )
            await self.controller.sync_member_role(user_id, snapshot.is_active)
            await interaction.followup.send(
                embed=membership_embed(snapshot, user_id), ephemeral=True
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MemberCancelModal(discord.ui.Modal):
    def __init__(self, controller: ManagerControlCog) -> None:
        super().__init__(title="到期取消", custom_id="axis:member:cancel:modal:v1")
        self.controller = controller
        self.user = discord.ui.TextInput(label="Discord User ID 或 @mention")
        self.ends_at = discord.ui.TextInput(
            label="Lifetime 会员需填写 YYYY-MM-DD",
            required=False,
            placeholder="已有到期日可留空",
        )
        self.add_item(self.user)
        self.add_item(self.ends_at)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = _user_id(self.user.value)
            snapshot = await self.controller.membership_service.cancel_at_expiry(
                self.controller.guild_id,
                user_id,
                ends_at=_expiry(self.ends_at.value),
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await interaction.followup.send(
                embed=membership_embed(snapshot, user_id), ephemeral=True
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MemberRemoveModal(discord.ui.Modal):
    def __init__(self, controller: ManagerControlCog) -> None:
        super().__init__(title="立即移除", custom_id="axis:member:remove:modal:v1")
        self.controller = controller
        self.user = discord.ui.TextInput(label="Discord User ID 或 @mention")
        self.reason = discord.ui.TextInput(
            label="Reason", required=False, default="manager_revoke", max_length=200
        )
        self.add_item(self.user)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = _user_id(self.user.value)
            snapshot = await self.controller.membership_service.remove(
                self.controller.guild_id,
                user_id,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
                reason=self.reason.value or "manager_revoke",
            )
            await self.controller.sync_member_role(user_id, False)
            await interaction.followup.send(
                embed=membership_embed(snapshot, user_id), ephemeral=True
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class MemberControlView(discord.ui.View):
    def __init__(self, controller: ManagerControlCog) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        definitions = (
            ("查找会员", "lookup", discord.ButtonStyle.secondary, self.lookup),
            ("赠送会员", "gift", discord.ButtonStyle.success, self.gift),
            ("延长会员", "extend", discord.ButtonStyle.primary, self.extend),
            ("到期取消", "cancel", discord.ButtonStyle.secondary, self.cancel),
            ("立即移除", "remove", discord.ButtonStyle.danger, self.remove),
        )
        for label, action, style, callback in definitions:
            button = discord.ui.Button(
                label=label,
                custom_id=f"axis:member:{action}:v1",
                style=style,
            )
            button.callback = callback
            self.add_item(button)

    async def lookup(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemberLookupModal(self.controller))

    async def gift(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemberDurationModal(self.controller, action="gift"))

    async def extend(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemberDurationModal(self.controller, action="extend"))

    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemberCancelModal(self.controller))

    async def remove(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemberRemoveModal(self.controller))
