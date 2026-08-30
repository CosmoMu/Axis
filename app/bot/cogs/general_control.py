from __future__ import annotations

import logging
from contextlib import suppress

import discord
from discord.ext import commands, tasks
from sqlalchemy import select

from app.bot.general_cards import (
    lobby_guide_embed,
    member_wins_guide_embed,
    results_guide_embed,
    subscription_embed,
    welcome_embed,
)
from app.db.models import GuildConfig
from app.services.membership_payments import MembershipPaymentError, MembershipPaymentService

logger = logging.getLogger(__name__)


class CheckoutLinkView(discord.ui.View):
    def __init__(self, checkout_url: str) -> None:
        super().__init__(timeout=600)
        self.add_item(
            discord.ui.Button(
                label="CONTINUE TO CHECKOUT",
                style=discord.ButtonStyle.link,
                url=checkout_url,
            )
        )


class JoinAxisView(discord.ui.View):
    def __init__(
        self,
        controller: GeneralControlCog,
        *,
        customer_portal_url: str | None,
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        join = discord.ui.Button(
            label="JOIN AXIS",
            style=discord.ButtonStyle.success,
            custom_id="axis:membership:join:v1",
        )
        join.callback = self.join
        self.add_item(join)
        if customer_portal_url:
            self.add_item(
                discord.ui.Button(
                    label="MANAGE MEMBERSHIP",
                    style=discord.ButtonStyle.link,
                    url=customer_portal_url,
                )
            )

    async def join(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.controller.guild_id:
            await interaction.response.send_message("该入口不属于当前服务器。", ephemeral=True)
            return
        try:
            checkout = await self.controller.payment_service.create_checkout_session(
                self.controller.guild_id,
                interaction.user.id,
            )
            await interaction.response.send_message(
                "Checkout 已绑定你的 Discord User ID。链接将在 "
                f"{self.controller.payment_service.session_ttl_minutes} 分钟后失效。",
                view=CheckoutLinkView(checkout.checkout_url),
                ephemeral=True,
            )
        except MembershipPaymentError as exc:
            message = (
                "订阅入口尚未配置，请稍后再试。"
                if exc.code == "SUBSCRIPTION_URL_NOT_CONFIGURED"
                else "暂时无法创建 Checkout，请稍后再试。"
            )
            await interaction.response.send_message(message, ephemeral=True)


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
        results_mention: str,
        membership_price_display: str,
        customer_portal_url: str | None,
        payment_service: MembershipPaymentService,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.welcome_channel_id = welcome_channel_id
        self.subscriptions_channel_id = subscriptions_channel_id
        self.results_channel_id = results_channel_id
        self.lobby_channel_id = lobby_channel_id
        self.member_wins_channel_id = member_wins_channel_id
        self.results_mention = results_mention
        self.membership_price_display = membership_price_display
        self.customer_portal_url = customer_portal_url
        self.payment_service = payment_service
        self._ready = False
        self.control_loop.start()

    def cog_unload(self) -> None:
        self.control_loop.cancel()

    @tasks.loop(seconds=30)
    async def control_loop(self) -> None:
        if self._ready:
            return
        try:
            guild = self.bot.get_guild(self.guild_id)
            if guild is None:
                return
            icon_url = str(guild.icon.url) if guild.icon else None
            join_view = JoinAxisView(
                self,
                customer_portal_url=self.customer_portal_url,
            )
            self.bot.add_view(join_view)
            await self._ensure_message(
                self.welcome_channel_id,
                "welcome_message_id",
                "AXIS Welcome v1",
                welcome_embed(icon_url=icon_url),
                join_view,
            )
            await self._ensure_message(
                self.subscriptions_channel_id,
                "subscription_message_id",
                "AXIS Membership v1",
                subscription_embed(self.membership_price_display, icon_url=icon_url),
                join_view,
            )
            await self._ensure_message(
                self.results_channel_id,
                "results_guide_message_id",
                "AXIS Results Guide v1",
                results_guide_embed(),
                None,
            )
            await self._ensure_message(
                self.lobby_channel_id,
                "lobby_guide_message_id",
                "AXIS Lobby Guide v1",
                lobby_guide_embed(),
                None,
            )
            wins = member_wins_guide_embed()
            wins.description = (wins.description or "").replace(
                "<#RESULTS_CHANNEL_ID>", self.results_mention
            )
            await self._ensure_message(
                self.member_wins_channel_id,
                "member_wins_guide_message_id",
                "AXIS Member Wins Guide v1",
                wins,
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

    async def _ensure_message(
        self,
        channel_id: int,
        config_field: str,
        marker: str,
        embed: discord.Embed,
        view: discord.ui.View | None,
        *,
        pin: bool = False,
    ) -> None:
        database = self.payment_service.database
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
                if any(item.footer.text == marker for item in candidate.embeds):
                    message = candidate
                    break
        if message is None:
            message = await channel.send(embed=embed, view=view)
        else:
            await message.edit(embed=embed, view=view)
        if pin and not message.pinned:
            try:
                await message.pin(reason="AXIS channel guide")
            except discord.HTTPException as exc:
                logger.warning(
                    "event=general_guide_pin_failed marker=%s status=%s code=%s",
                    marker.replace(" ", "_"),
                    exc.status,
                    exc.code,
                )
                raise
        async with database.session() as session:
            config = await session.scalar(
                select(GuildConfig).where(GuildConfig.guild_id == self.guild_id).with_for_update()
            )
            if config is not None and getattr(config, config_field) != message.id:
                setattr(config, config_field, message.id)
                await session.commit()
