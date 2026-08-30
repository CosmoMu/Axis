from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

import discord
from discord.ext import commands, tasks
from sqlalchemy import select

from app.bot.general_cards import (
    member_wins_guide_embed,
    results_guide_embed,
    risk_disclosure_embed,
    subscription_embed,
    welcome_embed,
)
from app.db.models import GuildConfig
from app.domain.enums import MembershipPlanType
from app.domain.public_identity import PublicIdentityPolicy
from app.services.membership_access import (
    MembershipAccessError,
    MembershipAccessService,
    MembershipAcknowledgementService,
    MembershipPriceCatalog,
    PriceSnapshot,
)
from app.services.membership_stripe import MembershipStripeError, MembershipStripeService

logger = logging.getLogger(__name__)


class LinkView(discord.ui.View):
    def __init__(self, label: str, url: str) -> None:
        super().__init__(timeout=600)
        self.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=url))


class WelcomeMembershipView(discord.ui.View):
    def __init__(self, guild_id: int, subscriptions_channel_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="VIEW MEMBERSHIP",
                style=discord.ButtonStyle.link,
                url=(f"https://discord.com/channels/{guild_id}/{subscriptions_channel_id}"),
            )
        )


class RiskDisclosureView(discord.ui.View):
    def __init__(self, controller: GeneralControlCog, plan_type: str) -> None:
        super().__init__(timeout=600)
        self.controller = controller
        self.plan_type = plan_type
        button = discord.ui.Button(
            label="I UNDERSTAND",
            style=discord.ButtonStyle.success,
            custom_id=f"axis:risk:accept:{plan_type.lower()}:v1",
        )
        button.callback = self.accept
        self.add_item(button)

    async def accept(self, interaction: discord.Interaction) -> None:
        if not self.controller.is_current_guild(interaction):
            await interaction.response.send_message("该入口不属于当前服务器。", ephemeral=True)
            return
        await self.controller.acknowledgements.accept_risk(
            self.controller.guild_id,
            interaction.user.id,
            interaction_id=interaction.id,
        )
        await self.controller.activate_plan(interaction, self.plan_type)


class MembershipView(discord.ui.View):
    def __init__(
        self,
        controller: GeneralControlCog,
        offers: dict[str, PriceSnapshot],
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        day = offers.get(MembershipPlanType.DAY_PASS.value)
        monthly = offers.get(MembershipPlanType.MONTHLY.value)
        definitions = (
            (
                "FREE 3-DAY TRIAL",
                "free_trial",
                discord.ButtonStyle.success,
                self.free_trial,
            ),
            (
                f"DAY PASS · {day.display_amount if day else 'UNAVAILABLE'}",
                "day_pass",
                discord.ButtonStyle.primary,
                self.day_pass,
            ),
            (
                f"MONTHLY · {monthly.display_amount if monthly else 'UNAVAILABLE'}",
                "monthly",
                discord.ButtonStyle.primary,
                self.monthly,
            ),
            (
                "CANCEL MONTHLY",
                "manage",
                discord.ButtonStyle.secondary,
                self.manage,
            ),
        )
        for label, action, style, callback in definitions:
            button = discord.ui.Button(
                label=label[:80],
                style=style,
                custom_id=f"axis:membership:{action}:v2",
            )
            button.callback = callback
            self.add_item(button)

    async def free_trial(self, interaction: discord.Interaction) -> None:
        await self.controller.request_plan(interaction, "FREE_TRIAL")

    async def day_pass(self, interaction: discord.Interaction) -> None:
        await self.controller.request_plan(interaction, MembershipPlanType.DAY_PASS.value)

    async def monthly(self, interaction: discord.Interaction) -> None:
        await self.controller.request_plan(interaction, MembershipPlanType.MONTHLY.value)

    async def manage(self, interaction: discord.Interaction) -> None:
        await self.controller.manage_membership(interaction)


class GeneralControlCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        guild_id: int,
        welcome_channel_id: int,
        subscriptions_channel_id: int,
        results_channel_id: int,
        lobby_channel_id: int,
        member_wins_channel_id: int,
        short_term_channel_id: int,
        swing_channel_id: int,
        leaps_channel_id: int,
        member_chat_channel_id: int,
        access_service: MembershipAccessService,
        acknowledgements: MembershipAcknowledgementService,
        price_catalog: MembershipPriceCatalog,
        stripe_service: MembershipStripeService,
        public_identity: PublicIdentityPolicy,
        sync_role: Callable[[int, bool], Awaitable[None]],
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.welcome_channel_id = welcome_channel_id
        self.subscriptions_channel_id = subscriptions_channel_id
        self.results_channel_id = results_channel_id
        self.lobby_channel_id = lobby_channel_id
        self.member_wins_channel_id = member_wins_channel_id
        self.short_term_channel_id = short_term_channel_id
        self.swing_channel_id = swing_channel_id
        self.leaps_channel_id = leaps_channel_id
        self.member_chat_channel_id = member_chat_channel_id
        self.access_service = access_service
        self.acknowledgements = acknowledgements
        self.price_catalog = price_catalog
        self.stripe_service = stripe_service
        self.public_identity = public_identity
        self.sync_role = sync_role
        self._ready = False
        self.control_loop.start()

    def cog_unload(self) -> None:
        self.control_loop.cancel()

    def is_current_guild(self, interaction: discord.Interaction) -> bool:
        return interaction.guild_id == self.guild_id

    async def request_plan(self, interaction: discord.Interaction, plan_type: str) -> None:
        if not self.is_current_guild(interaction):
            await interaction.response.send_message("该入口不属于当前服务器。", ephemeral=True)
            return
        if not await self.acknowledgements.has_current_risk(interaction.user.id):
            notice = risk_disclosure_embed()
            self.public_identity.assert_public(notice.to_dict(), field="risk_disclosure")
            await interaction.response.send_message(
                embed=notice,
                view=RiskDisclosureView(self, plan_type),
                ephemeral=True,
            )
            return
        await self.activate_plan(interaction, plan_type)

    async def activate_plan(self, interaction: discord.Interaction, plan_type: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            if plan_type == "FREE_TRIAL":
                entitlement = await self.access_service.claim_free_trial(
                    self.guild_id,
                    interaction.user.id,
                    interaction_id=interaction.id,
                )
                await self.sync_role(interaction.user.id, True)
                await interaction.followup.send(
                    "Free Trial 已启用。有效交易日："
                    f"{entitlement.first_trading_day} → {entitlement.last_trading_day}；"
                    "最后一天 23:59:59 ET 到期。",
                    ephemeral=True,
                )
                return
            checkout = await self.stripe_service.create_checkout(
                self.guild_id,
                interaction.user.id,
                plan_type,
            )
            await interaction.followup.send(
                "Checkout 已绑定你的 Discord 账户；付款状态只以 Stripe Webhook 为准。",
                view=LinkView("CONTINUE TO CHECKOUT", checkout.url),
                ephemeral=True,
            )
        except (MembershipAccessError, MembershipStripeError) as exc:
            messages = {
                "FREE_TRIAL_ALREADY_CLAIMED": "该 Discord 账户已经领取过终身一次的 Free Trial。",
                "MONTHLY_ALREADY_ACTIVE": (
                    "该 Discord 账户已有有效 Monthly，请使用 Manage Membership。"
                ),
                "STRIPE_CHECKOUT_DISABLED": "Stripe Checkout 仍处于安全禁用状态。",
                "STRIPE_PRICE_NOT_CONFIGURED": "Stripe Price 尚未完成配置。",
            }
            await interaction.followup.send(
                messages.get(exc.code, f"操作未完成：{exc.code}"),
                ephemeral=True,
            )

    async def manage_membership(self, interaction: discord.Interaction) -> None:
        if not self.is_current_guild(interaction):
            await interaction.response.send_message("该入口不属于当前服务器。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            url = await self.stripe_service.create_customer_portal(
                self.guild_id, interaction.user.id
            )
            await interaction.followup.send(
                (
                    "Monthly 会自动续费，直到你在 Stripe Customer Portal 确认取消。"
                    "你也可以在 Portal 查看账单或更新付款方式。"
                ),
                view=LinkView("CANCEL / MANAGE MONTHLY", url),
                ephemeral=True,
            )
        except MembershipStripeError as exc:
            await interaction.followup.send(f"暂时无法打开 Portal：{exc.code}", ephemeral=True)

    @tasks.loop(seconds=30)
    async def control_loop(self) -> None:
        if self._ready:
            return
        try:
            guild = self.bot.get_guild(self.guild_id)
            if guild is None:
                return
            offers = await self.price_catalog.current_offers()
            membership_view = MembershipView(self, offers)
            self.bot.add_view(membership_view)
            welcome_view = WelcomeMembershipView(
                self.guild_id,
                self.subscriptions_channel_id,
            )
            cards = (
                welcome_embed(
                    self.guild_id,
                    {
                        "subscriptions": self.subscriptions_channel_id,
                        "official_results": self.results_channel_id,
                        "lobby": self.lobby_channel_id,
                        "member_wins": self.member_wins_channel_id,
                        "short_term_alerts": self.short_term_channel_id,
                        "swing_alerts": self.swing_channel_id,
                        "leaps_alerts": self.leaps_channel_id,
                        "member_chat": self.member_chat_channel_id,
                    },
                ),
                subscription_embed(offers),
                results_guide_embed(),
                member_wins_guide_embed(),
            )
            for index, embed in enumerate(cards):
                self.public_identity.assert_public(embed.to_dict(), field=f"general_card_{index}")
            await self._ensure_message(
                self.welcome_channel_id,
                "welcome_message_id",
                "AXIS Welcome v1",
                cards[0],
                welcome_view,
            )
            await self._ensure_message(
                self.subscriptions_channel_id,
                "subscription_message_id",
                "AXIS Membership v1",
                cards[1],
                membership_view,
            )
            await self._ensure_message(
                self.results_channel_id,
                "results_guide_message_id",
                "AXIS Results Guide v1",
                cards[2],
                None,
            )
            await self._remove_lobby_guide()
            await self._ensure_message(
                self.member_wins_channel_id,
                "member_wins_guide_message_id",
                "AXIS Member Wins Guide v1",
                cards[3],
                None,
                pin=True,
            )
            self._ready = True
        except discord.HTTPException as exc:
            logger.warning(
                "event=general_control_failed error_type=%s status=%s code=%s",
                type(exc).__name__,
                exc.status,
                exc.code,
            )
        except Exception as exc:
            logger.warning("event=general_control_failed error_type=%s", type(exc).__name__)

    @control_loop.before_loop
    async def before_control_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _remove_lobby_guide(self) -> None:
        database = self.access_service.database
        async with database.session() as session:
            config = await session.get(GuildConfig, self.guild_id)
            saved_message_id = config.lobby_guide_message_id if config else None
        if saved_message_id is None:
            return
        channel = self.bot.get_channel(self.lobby_channel_id) or await self.bot.fetch_channel(
            self.lobby_channel_id
        )
        with suppress(discord.NotFound, discord.Forbidden):
            message = await channel.fetch_message(saved_message_id)
            if self.bot.user is not None and message.author.id == self.bot.user.id:
                await message.delete()
        async with database.session() as session:
            config = await session.get(GuildConfig, self.guild_id)
            if config is not None and config.lobby_guide_message_id is not None:
                config.lobby_guide_message_id = None
                await session.commit()

    async def _ensure_message(
        self,
        channel_id: int,
        config_field: str,
        legacy_marker: str,
        embed: discord.Embed,
        view: discord.ui.View | None,
        *,
        pin: bool = False,
    ) -> None:
        database = self.access_service.database
        async with database.session() as session:
            config = await session.get(GuildConfig, self.guild_id)
            saved_message_id = getattr(config, config_field) if config else None
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        message = None
        if saved_message_id is not None:
            with suppress(discord.NotFound, discord.Forbidden):
                message = await channel.fetch_message(saved_message_id)
        if message is None:
            async for candidate in channel.history(limit=100):
                if self.bot.user is None or candidate.author.id != self.bot.user.id:
                    continue
                if any(
                    item.title == embed.title or item.footer.text == legacy_marker
                    for item in candidate.embeds
                ):
                    message = candidate
                    break
        if message is None:
            message = await channel.send(embed=embed, view=view)
        else:
            await message.edit(embed=embed, view=view)
        if pin and not message.pinned:
            await message.pin(reason="AXIS channel guide")
        async with database.session() as session:
            config = await session.scalar(
                select(GuildConfig).where(GuildConfig.guild_id == self.guild_id).with_for_update()
            )
            if config is not None and getattr(config, config_field) != message.id:
                setattr(config, config_field, message.id)
                await session.commit()
