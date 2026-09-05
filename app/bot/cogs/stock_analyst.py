"""Read-only `/stock` surface for Member Lounge and Owner card testing."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from contextlib import suppress
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.stock_analyst_cards import build_stock_analyst_embed
from app.services.stock_analyst import (
    StockAnalystError,
    StockAnalystQueryService,
    normalize_stock_ticker,
)

logger = logging.getLogger(__name__)


def has_stock_lounge_access(
    *,
    user_id: int,
    role_ids: Iterable[int],
    guild_owner_id: int,
    configured_owner_id: int,
    member_role_id: int,
    manager_role_id: int,
) -> bool:
    if user_id in {guild_owner_id, configured_owner_id}:
        return True
    allowed_roles = {member_role_id, manager_role_id}
    return any(role_id in allowed_roles for role_id in role_ids)


def has_stock_cooldown_bypass(
    *,
    user_id: int,
    role_ids: Iterable[int],
    guild_owner_id: int,
    configured_owner_id: int,
    manager_role_id: int,
) -> bool:
    """Managers and both Owner identities bypass user/ticker cooldowns."""
    return user_id in {guild_owner_id, configured_owner_id} or manager_role_id in set(role_ids)


def stock_authorization_error(
    *,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int,
    expected_guild_id: int,
    owner_user_id: int,
    card_testing_channel_id: int,
    member_lounge_channel_id: int,
    has_lounge_access: bool,
    mode: str,
) -> str | None:
    if guild_id != expected_guild_id:
        return "PERMISSION_DENIED"
    if mode == "OFF":
        return "STOCK_ANALYST_DISABLED"
    if mode == "TEST":
        if user_id != owner_user_id:
            return "PERMISSION_DENIED"
        return None if channel_id == card_testing_channel_id else "TEST_CHANNEL_REQUIRED"
    if mode == "MEMBER_LOUNGE":
        if user_id == owner_user_id and channel_id == card_testing_channel_id:
            return None
        if channel_id != member_lounge_channel_id:
            return "MEMBER_LOUNGE_REQUIRED"
        return None if has_lounge_access else "PERMISSION_DENIED"
    return "STOCK_ANALYST_DISABLED"


class StockAnalystCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: StockAnalystQueryService,
        guild_id: int,
        owner_user_id: int,
        card_testing_channel_id: int,
        member_lounge_channel_id: int,
        member_role_id: int,
        manager_role_id: int,
        mode: str,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self.card_testing_channel_id = card_testing_channel_id
        self.member_lounge_channel_id = member_lounge_channel_id
        self.member_role_id = member_role_id
        self.manager_role_id = manager_role_id
        self.mode = mode

    @app_commands.command(name="stock", description="生成 AXIS Stock Analyst 日线分析")
    @app_commands.describe(ticker="美股或 ETF 代码，例如 NVDA、$SPY")
    @app_commands.guild_only()
    async def stock(self, interaction: discord.Interaction, ticker: str) -> None:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        guild_owner_id = interaction.guild.owner_id if interaction.guild is not None else 0
        role_ids = tuple(role.id for role in member.roles) if member is not None else ()
        authorization = stock_authorization_error(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
            expected_guild_id=self.guild_id,
            owner_user_id=self.owner_user_id,
            card_testing_channel_id=self.card_testing_channel_id,
            member_lounge_channel_id=self.member_lounge_channel_id,
            has_lounge_access=(
                member is not None
                and has_stock_lounge_access(
                    user_id=member.id,
                    role_ids=role_ids,
                    guild_owner_id=guild_owner_id,
                    configured_owner_id=self.owner_user_id,
                    member_role_id=self.member_role_id,
                    manager_role_id=self.manager_role_id,
                )
            ),
            mode=self.mode,
        )
        if authorization == "PERMISSION_DENIED":
            await interaction.response.send_message(
                "当前没有使用 AXIS Stock Analyst 的权限。",
                ephemeral=True,
            )
            return
        if authorization == "TEST_CHANNEL_REQUIRED":
            await interaction.response.send_message(
                "AXIS STOCK ANALYST · TEST MODE\n\n"
                "Stock Analyst 当前仅可在 🧪・card-testing 使用。",
                ephemeral=True,
            )
            return
        if authorization == "STOCK_ANALYST_DISABLED":
            await interaction.response.send_message(
                "AXIS Stock Analyst 当前已关闭。",
                ephemeral=True,
            )
            return
        if authorization == "MEMBER_LOUNGE_REQUIRED":
            await interaction.response.send_message(
                "请在 🛋️・member-lounge 使用 `/stock ticker:SPY`。",
                ephemeral=True,
            )
            return
        try:
            symbol = normalize_stock_ticker(ticker)
        except StockAnalystError:
            await interaction.response.send_message(
                "AXIS STOCK ANALYST\n\n"
                f"没有找到 `{ticker.strip().upper()}` 的有效市场数据，请检查代码后重试。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        try:
            result = await self.service.query(
                guild_id=self.guild_id,
                actor_user_id=interaction.user.id,
                ticker=symbol,
                interaction_id=interaction.id,
                bypass_cooldowns=has_stock_cooldown_bypass(
                    user_id=interaction.user.id,
                    role_ids=role_ids,
                    guild_owner_id=guild_owner_id,
                    configured_owner_id=self.owner_user_id,
                    manager_role_id=self.manager_role_id,
                ),
            )
            filename = f"axis-stock-{result.analysis.ticker.lower()}.png"
            await interaction.edit_original_response(
                content=None,
                embed=build_stock_analyst_embed(result, mode=self.mode),
                attachments=[discord.File(BytesIO(result.chart_png), filename=filename)],
            )
            if result.latency_ms > self.service.policy.maximum_latency_seconds * 1000:
                await self._report_failure("WARNING", "STOCK_ANALYST_EXCESSIVE_LATENCY", symbol)
            else:
                await self._report_recovery("STOCK_ANALYST_EXCESSIVE_LATENCY", symbol)
            for code in (
                "STOCK_ANALYST_PROVIDER_FAILURE",
                "STOCK_ANALYST_DATA_QUALITY_FAILURE",
                "STOCK_ANALYST_CALCULATION_FAILURE",
                "STOCK_ANALYST_RENDER_FAILURE",
                "STOCK_ANALYST_LLM_FAILURE",
                "STOCK_ANALYST_COMMAND_FAILURE",
            ):
                await self._report_recovery(code, symbol)
        except StockAnalystError as exc:
            await self._handle_error(interaction, symbol, exc.code)
        except Exception as exc:
            logger.exception("event=stock_analyst_command_failed error_type=%s", type(exc).__name__)
            await self._handle_error(interaction, symbol, "STOCK_ANALYST_COMMAND_FAILURE")

    async def _handle_error(
        self,
        interaction: discord.Interaction,
        ticker: str,
        code: str,
    ) -> None:
        invalid = code in {"AXIS_STOCK_SYMBOL_INVALID", "AXIS_STOCK_SYMBOL_NOT_FOUND"}
        messages = {
            "AXIS_STOCK_SYMBOL_INVALID": f"没有找到 `{ticker}` 的有效市场数据，请检查代码后重试。",
            "AXIS_STOCK_SYMBOL_NOT_FOUND": (
                f"没有找到 `{ticker}` 的有效市场数据，请检查代码后重试。"
            ),
            "STOCK_ANALYST_USER_COOLDOWN": "每位会员每 30 秒可查询一次，请稍候再试。",
            "STOCK_ANALYST_TICKER_COOLDOWN": "该股票刚刚查询过；同一股票每 60 秒可更新一次。",
            "STOCK_ANALYST_GUILD_RATE_LIMIT": "当前分析请求较多，请稍后重试。",
        }
        message = messages.get(code, "AXIS Stock Analyst 暂时不可用，请稍后重试。")
        with suppress(discord.HTTPException):
            await interaction.delete_original_response()
        await interaction.followup.send(message, ephemeral=True)
        if not invalid and code not in {
            "STOCK_ANALYST_USER_COOLDOWN",
            "STOCK_ANALYST_TICKER_COOLDOWN",
            "STOCK_ANALYST_GUILD_RATE_LIMIT",
        }:
            alert_code = (
                code if code.startswith("STOCK_ANALYST_") else "STOCK_ANALYST_PROVIDER_FAILURE"
            )
            await self._report_failure("ERROR", alert_code, ticker)

    async def _report_failure(self, severity: str, error_type: str, ticker: str) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_failure(  # type: ignore[attr-defined]
                severity=severity,
                service="AXIS Stock Analyst",
                error_type=error_type,
                affected=f"STOCK {ticker} · {self.mode.lower().replace('_', '-')}",
                detail=error_type,
            )

    async def _report_recovery(self, error_type: str, ticker: str) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_recovery(  # type: ignore[attr-defined]
                service="AXIS Stock Analyst",
                error_type=error_type,
                affected=f"STOCK {ticker} · {self.mode.lower().replace('_', '-')}",
            )
