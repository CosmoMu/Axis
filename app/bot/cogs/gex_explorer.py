"""Owner-only Phase 1 slash-command surface for AXIS GEX Explorer."""

from __future__ import annotations

import logging
from contextlib import suppress
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.gex_cards import build_gex_embed
from app.services.gex_explorer import GexExplorerError, GexExplorerService, normalize_gex_ticker

logger = logging.getLogger(__name__)
RECOVERABLE_GEX_ERRORS = (
    "GEX_COMMAND_FAILED",
    "GEX_PROVIDER_UNAVAILABLE",
    "GEX_PROVIDER_RESPONSE_INVALID",
    "GEX_SPOT_UNAVAILABLE",
    "GEX_OPTION_CHAIN_EMPTY",
    "GEX_DATA_QUALITY_FAILED",
    "GEX_RENDER_FAILED",
    "GEX_EXPIRY_COVERAGE_INSUFFICIENT",
    "MASSIVE_AUTH_FAILED",
    "MASSIVE_RATE_LIMITED",
)


def gex_authorization_error(
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
    if mode != "TEST":
        return "GEX_DISABLED"
    if channel_id != card_testing_channel_id:
        return "TEST_CHANNEL_REQUIRED"
    return None


class GexExplorerCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: GexExplorerService,
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

    @app_commands.command(name="gex", description="生成 AXIS GEX 结构卡片（Phase 1 Test）")
    @app_commands.describe(ticker="股票或指数代码，例如 NVDA、$SPY、SPX")
    @app_commands.guild_only()
    async def gex(self, interaction: discord.Interaction, ticker: str) -> None:
        authorization = gex_authorization_error(
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
                "当前没有使用 AXIS GEX Explorer 的权限。", ephemeral=True
            )
            return
        if authorization == "GEX_DISABLED":
            await interaction.response.send_message(
                "AXIS GEX Explorer 当前已关闭。", ephemeral=True
            )
            return
        if authorization == "TEST_CHANNEL_REQUIRED":
            await interaction.response.send_message(
                "Test Mode：请只在 🧪・card-testing 使用 `/gex TICKER`。",
                ephemeral=True,
            )
            return
        try:
            symbol = normalize_gex_ticker(ticker)
        except GexExplorerError:
            await interaction.response.send_message(
                "未识别该 Ticker。请检查拼写，并使用例如 `/gex NVDA`。",
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
            filename = f"axis-gex-{result.snapshot.ticker.lower()}.png"
            await interaction.edit_original_response(
                content=None,
                embed=build_gex_embed(result),
                attachments=[discord.File(BytesIO(result.heatmap_png), filename=filename)],
            )
            if result.latency_ms > self.service.policy.max_latency_seconds * 1000:
                await self._report_failure("WARNING", "GEX_EXCESSIVE_LATENCY", symbol)
            else:
                await self._report_recovery("GEX_EXCESSIVE_LATENCY", symbol)
            for error_type in RECOVERABLE_GEX_ERRORS:
                await self._report_recovery(error_type, symbol)
        except GexExplorerError as exc:
            await self._handle_error(interaction, symbol, exc.code)
        except Exception as exc:
            logger.exception("event=gex_command_failed error_type=%s", type(exc).__name__)
            await self._handle_error(interaction, symbol, "GEX_COMMAND_FAILED")

    async def _handle_error(
        self, interaction: discord.Interaction, ticker: str, code: str
    ) -> None:
        messages = {
            "GEX_USER_COOLDOWN": "请求过快，请稍候再试。",
            "GEX_GUILD_RATE_LIMIT": "当前请求较多，请稍后重试。",
            "GEX_TICKER_NOT_FOUND": "未找到该 Ticker 或可用期权链，请检查后重试。",
            "GEX_NO_EXPIRATIONS": "该标的没有找到可用的近期到期日。",
            "GEX_OPTION_CHAIN_EMPTY": "期权链暂时没有返回可用数据。",
            "GEX_EXPIRY_COVERAGE_INSUFFICIENT": "有效到期日覆盖不足，已停止生成以避免误导。",
            "MASSIVE_AUTH_FAILED": "行情权限或凭据不可用，请管理员检查 Massive 配置。",
            "MASSIVE_RATE_LIMITED": "行情服务达到速率限制，请稍后重试。",
            "GEX_SPX_UNSUPPORTED": "当前 Massive 权限不支持 SPX GEX 数据，请勿用 SPY 替代。",
        }
        message = messages.get(code, "GEX 数据或图片生成暂时失败，请稍后重试。")
        with suppress(discord.HTTPException):
            await interaction.delete_original_response()
        await interaction.followup.send(message, ephemeral=True)
        severity = "WARNING" if code in {"GEX_USER_COOLDOWN", "GEX_GUILD_RATE_LIMIT"} else "ERROR"
        if code not in {
            "GEX_USER_COOLDOWN",
            "GEX_GUILD_RATE_LIMIT",
            "GEX_TICKER_NOT_FOUND",
            "GEX_NO_EXPIRATIONS",
            "GEX_SPX_UNSUPPORTED",
        }:
            await self._report_failure(severity, code, ticker)

    async def _report_failure(self, severity: str, error_type: str, ticker: str) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_failure(  # type: ignore[attr-defined]
                severity=severity,
                service="AXIS GEX Explorer",
                error_type=error_type,
                affected=f"/gex {ticker} · card-testing",
                detail=error_type,
            )

    async def _report_recovery(self, error_type: str, ticker: str) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_recovery(  # type: ignore[attr-defined]
                service="AXIS GEX Explorer",
                error_type=error_type,
                affected=f"/gex {ticker} · card-testing",
            )
