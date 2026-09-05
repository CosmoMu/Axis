"""Owner-only `/stock` test surface; no message trigger and no write-side effects."""

from __future__ import annotations

import logging
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


def stock_authorization_error(
    *,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int,
    expected_guild_id: int,
    owner_user_id: int,
    card_testing_channel_id: int,
    mode: str,
) -> str | None:
    if guild_id != expected_guild_id or user_id != owner_user_id:
        return "PERMISSION_DENIED"
    if mode == "OFF":
        return "STOCK_ANALYST_DISABLED"
    if mode == "TEST" and channel_id != card_testing_channel_id:
        return "TEST_CHANNEL_REQUIRED"
    return None if mode == "TEST" else "STOCK_ANALYST_DISABLED"


class StockAnalystCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: StockAnalystQueryService,
        guild_id: int,
        owner_user_id: int,
        card_testing_channel_id: int,
        mode: str,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self.card_testing_channel_id = card_testing_channel_id
        self.mode = mode

    @app_commands.command(name="stock", description="生成 AXIS Stock Analyst 测试卡片")
    @app_commands.describe(ticker="美股或 ETF 代码，例如 NVDA、$SPY")
    @app_commands.guild_only()
    async def stock(self, interaction: discord.Interaction, ticker: str) -> None:
        authorization = stock_authorization_error(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
            expected_guild_id=self.guild_id,
            owner_user_id=self.owner_user_id,
            card_testing_channel_id=self.card_testing_channel_id,
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
        try:
            symbol = normalize_stock_ticker(ticker)
        except StockAnalystError:
            await interaction.response.send_message(
                "AXIS STOCK ANALYST\n\n"
                f"Unable to find valid market data for:\n\n{ticker.strip().upper()}\n\n"
                "Please check the symbol and try again.",
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
            )
            filename = f"axis-stock-{result.analysis.ticker.lower()}.png"
            await interaction.edit_original_response(
                content=None,
                embed=build_stock_analyst_embed(result),
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
        message = (
            "AXIS STOCK ANALYST\n\n"
            f"Unable to find valid market data for:\n\n{ticker}\n\n"
            "Please check the symbol and try again."
            if invalid
            else (
                "AXIS STOCK ANALYST\n\nMarket analysis is temporarily unavailable.\n\n"
                "Please try again shortly."
            )
        )
        with suppress(discord.HTTPException):
            await interaction.delete_original_response()
        await interaction.followup.send(message, ephemeral=True)
        if not invalid and code not in {
            "STOCK_ANALYST_USER_COOLDOWN",
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
                affected=f"STOCK {ticker} · test",
                detail=error_type,
            )

    async def _report_recovery(self, error_type: str, ticker: str) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_recovery(  # type: ignore[attr-defined]
                service="AXIS Stock Analyst",
                error_type=error_type,
                affected=f"STOCK {ticker} · test",
            )
