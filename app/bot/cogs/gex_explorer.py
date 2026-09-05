"""Discord command surfaces for the read-only AXIS GEX Explorer."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from contextlib import suppress
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.gex_cards import build_gex_embed
from app.services.gex_explorer import GexExplorerError, GexExplorerService, normalize_gex_ticker

logger = logging.getLogger(__name__)
GEX_MESSAGE_PREFIX = re.compile(r"^\s*gex(?:\s|$|[:：])", re.IGNORECASE)
GEX_MESSAGE_PATTERN = re.compile(
    r"^\s*gex(?:\s+|\s*[:：]\s*)\$?([A-Z][A-Z0-9.\-]{0,9})\s*$",
    re.IGNORECASE,
)
RECOVERABLE_GEX_ERRORS = (
    "GEX_COMMAND_FAILED",
    "GEX_PROVIDER_UNAVAILABLE",
    "GEX_PROVIDER_RESPONSE_INVALID",
    "GEX_SPOT_UNAVAILABLE",
    "GEX_OPTION_CHAIN_EMPTY",
    "GEX_DATA_QUALITY_FAILED",
    "GEX_RENDER_FAILED",
    "GEX_EXPIRY_COVERAGE_INSUFFICIENT",
    "GEX_INTRADAY_COVERAGE_INSUFFICIENT",
    "GEX_INTRADAY_UNAVAILABLE",
    "GEX_INTRADAY_EMPTY",
    "GEX_INTRADAY_RESPONSE_INVALID",
    "MASSIVE_AUTH_FAILED",
    "MASSIVE_RATE_LIMITED",
)


def parse_gex_message(content: str) -> str | None:
    """Return a ticker only for the intentionally narrow `gex TICKER` syntax."""
    match = GEX_MESSAGE_PATTERN.fullmatch(content)
    return match.group(1) if match is not None else None


def has_gex_lounge_access(
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


def has_gex_cooldown_bypass(
    *,
    user_id: int,
    role_ids: Iterable[int],
    guild_owner_id: int,
    configured_owner_id: int,
    manager_role_id: int,
) -> bool:
    """Managers and both Owner identities bypass user/ticker cooldowns."""
    return user_id in {guild_owner_id, configured_owner_id} or manager_role_id in set(role_ids)


def gex_authorization_error(
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
        return "GEX_DISABLED"
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
    return "GEX_DISABLED"


class GexExplorerCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: GexExplorerService,
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

    @app_commands.command(name="gex", description="生成 AXIS GEX 盘中结构图")
    @app_commands.describe(ticker="股票或指数代码，例如 NVDA、$SPY、SPX")
    @app_commands.guild_only()
    async def gex(self, interaction: discord.Interaction, ticker: str) -> None:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        guild_owner_id = interaction.guild.owner_id if interaction.guild is not None else 0
        role_ids = tuple(role.id for role in member.roles) if member is not None else ()
        authorization = gex_authorization_error(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
            expected_guild_id=self.guild_id,
            owner_user_id=self.owner_user_id,
            card_testing_channel_id=self.card_testing_channel_id,
            member_lounge_channel_id=self.member_lounge_channel_id,
            has_lounge_access=(
                member is not None
                and has_gex_lounge_access(
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
                "测试模式：请只在 🧪・card-testing 使用 `/gex TICKER`。",
                ephemeral=True,
            )
            return
        if authorization == "MEMBER_LOUNGE_REQUIRED":
            await interaction.response.send_message(
                "请在 🛋️・member-lounge 使用 `gex TICKER` 或 `/gex TICKER`。",
                ephemeral=True,
            )
            return
        try:
            symbol = normalize_gex_ticker(ticker)
        except GexExplorerError:
            await interaction.response.send_message(
                "未识别该 Ticker。请检查拼写，例如 `gex SPY`。",
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
                bypass_cooldowns=has_gex_cooldown_bypass(
                    user_id=interaction.user.id,
                    role_ids=role_ids,
                    guild_owner_id=guild_owner_id,
                    configured_owner_id=self.owner_user_id,
                    manager_role_id=self.manager_role_id,
                ),
            )
            filename = f"axis-gex-{result.snapshot.ticker.lower()}.png"
            await interaction.edit_original_response(
                content=None,
                embed=build_gex_embed(
                    result,
                    test_mode=interaction.channel_id == self.card_testing_channel_id,
                ),
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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if (
            self.mode != "MEMBER_LOUNGE"
            or message.author.bot
            or message.guild is None
            or message.guild.id != self.guild_id
            or message.channel.id != self.member_lounge_channel_id
        ):
            return
        if not GEX_MESSAGE_PREFIX.match(message.content):
            return
        if not isinstance(message.author, discord.Member) or not has_gex_lounge_access(
            user_id=message.author.id,
            role_ids=(role.id for role in message.author.roles),
            guild_owner_id=message.guild.owner_id,
            configured_owner_id=self.owner_user_id,
            member_role_id=self.member_role_id,
            manager_role_id=self.manager_role_id,
        ):
            await self._safe_message_reply(message, "当前没有使用 AXIS GEX Explorer 的权限。")
            return
        ticker = parse_gex_message(message.content)
        if ticker is None:
            await self._safe_message_reply(message, "格式：`gex SPY`（请替换为需要查询的代码）。")
            return
        try:
            symbol = normalize_gex_ticker(ticker)
        except GexExplorerError:
            await self._safe_message_reply(message, "未识别该 Ticker。请检查拼写，例如 `gex SPY`。")
            return

        try:
            async with message.channel.typing():
                role_ids = tuple(role.id for role in message.author.roles)
                result = await self.service.query(
                    guild_id=self.guild_id,
                    actor_user_id=message.author.id,
                    ticker=symbol,
                    interaction_id=message.id,
                    bypass_cooldowns=has_gex_cooldown_bypass(
                        user_id=message.author.id,
                        role_ids=role_ids,
                        guild_owner_id=message.guild.owner_id,
                        configured_owner_id=self.owner_user_id,
                        manager_role_id=self.manager_role_id,
                    ),
                )
            filename = f"axis-gex-{result.snapshot.ticker.lower()}.png"
            await message.reply(
                embed=build_gex_embed(result, test_mode=False),
                file=discord.File(BytesIO(result.heatmap_png), filename=filename),
                mention_author=False,
            )
            if result.latency_ms > self.service.policy.max_latency_seconds * 1000:
                await self._report_failure("WARNING", "GEX_EXCESSIVE_LATENCY", symbol)
            else:
                await self._report_recovery("GEX_EXCESSIVE_LATENCY", symbol)
            for error_type in RECOVERABLE_GEX_ERRORS:
                await self._report_recovery(error_type, symbol)
        except GexExplorerError as exc:
            await self._handle_message_error(message, symbol, exc.code)
        except Exception as exc:
            logger.exception("event=gex_message_failed error_type=%s", type(exc).__name__)
            await self._handle_message_error(message, symbol, "GEX_COMMAND_FAILED")

    async def _handle_error(self, interaction: discord.Interaction, ticker: str, code: str) -> None:
        message = self._error_message(code)
        with suppress(discord.HTTPException):
            await interaction.delete_original_response()
        await interaction.followup.send(message, ephemeral=True)
        await self._report_error_if_needed(code, ticker)

    async def _handle_message_error(self, message: discord.Message, ticker: str, code: str) -> None:
        await self._safe_message_reply(message, self._error_message(code))
        await self._report_error_if_needed(code, ticker)

    @staticmethod
    def _error_message(code: str) -> str:
        messages = {
            "GEX_USER_COOLDOWN": "每位会员每 30 秒可查询一次，请稍候再试。",
            "GEX_TICKER_COOLDOWN": "该标的刚刚查询过；同一标的每 60 秒可更新一次。",
            "GEX_GUILD_RATE_LIMIT": "当前请求较多，请稍后重试。",
            "GEX_TICKER_NOT_FOUND": "未找到该 Ticker 或可用期权链，请检查后重试。",
            "GEX_NO_EXPIRATIONS": "该标的没有找到可用的近期到期日。",
            "GEX_OPTION_CHAIN_EMPTY": "期权链暂时没有返回可用数据。",
            "GEX_EXPIRY_COVERAGE_INSUFFICIENT": "有效到期日覆盖不足，已停止生成以避免误导。",
            "GEX_INTRADAY_COVERAGE_INSUFFICIENT": "盘中 K 线数量不足，已停止生成。",
            "GEX_INTRADAY_UNAVAILABLE": "Massive 盘中 K 线暂时不可用。",
            "GEX_INTRADAY_EMPTY": "Massive 当前没有返回可用于绘图的盘中 K 线。",
            "GEX_INTRADAY_RESPONSE_INVALID": "Massive 盘中 K 线响应格式异常。",
            "MASSIVE_AUTH_FAILED": "行情权限或凭据不可用，请管理员检查 Massive 配置。",
            "MASSIVE_RATE_LIMITED": "行情服务达到速率限制，请稍后重试。",
            "GEX_SPX_UNSUPPORTED": "当前 Massive 权限不支持 SPX GEX 数据，请勿用 SPY 替代。",
        }
        return messages.get(code, "GEX 数据或图片生成暂时失败，请稍后重试。")

    async def _report_error_if_needed(self, code: str, ticker: str) -> None:
        severity = (
            "WARNING"
            if code in {"GEX_USER_COOLDOWN", "GEX_TICKER_COOLDOWN", "GEX_GUILD_RATE_LIMIT"}
            else "ERROR"
        )
        if code not in {
            "GEX_USER_COOLDOWN",
            "GEX_TICKER_COOLDOWN",
            "GEX_GUILD_RATE_LIMIT",
            "GEX_TICKER_NOT_FOUND",
            "GEX_NO_EXPIRATIONS",
            "GEX_SPX_UNSUPPORTED",
        }:
            await self._report_failure(severity, code, ticker)

    @staticmethod
    async def _safe_message_reply(message: discord.Message, content: str) -> None:
        with suppress(discord.HTTPException):
            await message.reply(content, mention_author=False)

    async def _report_failure(self, severity: str, error_type: str, ticker: str) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_failure(  # type: ignore[attr-defined]
                severity=severity,
                service="AXIS GEX Explorer",
                error_type=error_type,
                affected=f"GEX {ticker} · {self.mode.lower().replace('_', '-')}",
                detail=error_type,
            )

    async def _report_recovery(self, error_type: str, ticker: str) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_recovery(  # type: ignore[attr-defined]
                service="AXIS GEX Explorer",
                error_type=error_type,
                affected=f"GEX {ticker} · {self.mode.lower().replace('_', '-')}",
            )
