"""Owner-only Discord surface for AXIS Multi-Agent Research test mode."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.bot.research_cards import (
    build_research_embed,
    detail_embed,
    progress_text,
)
from app.market_intelligence.research_engine.models import ResearchRunResult
from app.market_intelligence.research_engine.service import ResearchError, ResearchService

logger = logging.getLogger(__name__)


def research_authorization_error(
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
        return "RESEARCH_DISABLED"
    if channel_id != card_testing_channel_id:
        return "TEST_CHANNEL_REQUIRED"
    return None


class ResearchDetailView(discord.ui.View):
    def __init__(self, result: ResearchRunResult, *, owner_user_id: int) -> None:
        super().__init__(timeout=900)
        self.result = result
        self.owner_user_id = owner_user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_user_id:
            return True
        await interaction.response.send_message("当前没有查看研究详情的权限。", ephemeral=True)
        return False

    async def _show(self, interaction: discord.Interaction, section: str) -> None:
        file: discord.File | None = None
        ticker = self.result.view.ticker.lower()
        if section == "technical" and self.result.stock_chart_png is not None:
            file = discord.File(
                BytesIO(self.result.stock_chart_png),
                filename=f"axis-research-technical-{ticker}.png",
            )
        elif section == "gex" and self.result.gex_chart_png is not None:
            file = discord.File(
                BytesIO(self.result.gex_chart_png),
                filename=f"axis-research-gex-{ticker}.png",
            )
        embed = detail_embed(self.result, section)
        if file is not None:
            await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="技术面", style=discord.ButtonStyle.secondary, row=0)
    async def technical(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "technical")

    @discord.ui.button(label="期权结构", style=discord.ButtonStyle.secondary, row=0)
    async def gex(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "gex")

    @discord.ui.button(label="基本面", style=discord.ButtonStyle.secondary, row=0)
    async def fundamentals(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "fundamentals")

    @discord.ui.button(label="新闻动态", style=discord.ButtonStyle.secondary, row=0)
    async def news(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "news")

    @discord.ui.button(label="多空观点", style=discord.ButtonStyle.secondary, row=1)
    async def bull_bear(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "bull_bear")

    @discord.ui.button(label="风险评估", style=discord.ButtonStyle.secondary, row=1)
    async def risk(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "risk")


class _ProgressReporter:
    def __init__(self, interaction: discord.Interaction, ticker: str) -> None:
        self.interaction = interaction
        self.ticker = ticker
        self.statuses: dict[str, str] = {}
        self.lock = asyncio.Lock()

    async def update(self, stage: str, status: str) -> None:
        async with self.lock:
            self.statuses[stage] = status
            await self.interaction.edit_original_response(
                content=progress_text(self.ticker, self.statuses), embed=None
            )


class ResearchCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: ResearchService,
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
        if service.outcomes is not None:
            self.outcome_loop.start()

    def cog_unload(self) -> None:
        self.outcome_loop.cancel()

    @app_commands.command(name="research", description="运行 AXIS 多智能体市场研究（测试模式）")
    @app_commands.describe(ticker="股票或 ETF 代码，例如 SPY、NVDA、TSLA")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def research(self, interaction: discord.Interaction, ticker: str) -> None:
        authorization = research_authorization_error(
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
                "当前没有使用 AXIS Research 的权限。", ephemeral=True
            )
            return
        if authorization == "TEST_CHANNEL_REQUIRED":
            await interaction.response.send_message(
                "AXIS RESEARCH · TEST MODE\n\n"
                "Multi-Agent Research is currently available only in:\n\n"
                "🧪・卡片测试",
                ephemeral=True,
            )
            return
        if authorization:
            await interaction.response.send_message("AXIS Research 当前已关闭。", ephemeral=True)
            return
        symbol = ticker.strip().upper().removeprefix("$")
        await interaction.response.defer(thinking=True)
        reporter = _ProgressReporter(interaction, symbol)
        await reporter.update("technical", "PENDING")
        try:
            result = await self.service.query(
                guild_id=self.guild_id,
                actor_user_id=interaction.user.id,
                ticker=symbol,
                interaction_id=interaction.id,
                progress=reporter.update,
            )
            attachments = []
            if result.stock_chart_png is not None:
                attachments.append(
                    discord.File(
                        BytesIO(result.stock_chart_png),
                        filename=f"axis-research-{result.view.ticker.lower()}.png",
                    )
                )
            await interaction.edit_original_response(
                content=None,
                embed=build_research_embed(result),
                attachments=attachments,
                view=ResearchDetailView(result, owner_user_id=self.owner_user_id),
            )
            await self._sync_result_alerts(result)
        except ResearchError as exc:
            await interaction.edit_original_response(
                content=self._error_message(exc.code), embed=None, attachments=[], view=None
            )
            await self._report_failure(exc.code, symbol)
        except Exception as exc:
            logger.exception("event=research_command_failed error_type=%s", type(exc).__name__)
            await interaction.edit_original_response(
                content="AXIS Research 暂时不可用，请稍后重试。",
                embed=None,
                attachments=[],
                view=None,
            )
            await self._report_failure("RESEARCH_FAILED", symbol)

    @tasks.loop(hours=1)
    async def outcome_loop(self) -> None:
        if self.service.outcomes is None:
            return
        try:
            await self.service.outcomes.resolve_due()
            await self._report_recovery("RESEARCH_OUTCOME_RESOLUTION_FAILURE", "outcomes")
        except Exception as exc:
            logger.warning("event=research_outcome_failed error_type=%s", type(exc).__name__)
            await self._report_failure("RESEARCH_OUTCOME_RESOLUTION_FAILURE", "outcomes")

    @outcome_loop.before_loop
    async def before_outcome_loop(self) -> None:
        await self.bot.wait_until_ready()

    @staticmethod
    def _error_message(code: str) -> str:
        return {
            "RESEARCH_TICKER_INVALID": "未识别该 Ticker，请检查后重试。",
            "RESEARCH_USER_COOLDOWN": "每位使用者每 30 秒可发起一次研究。",
            "RESEARCH_GUILD_RATE_LIMIT": "当前研究请求较多，请稍后重试。",
            "RESEARCH_TIMEOUT": "研究运行超时，已安全停止。",
            "RESEARCH_MIN_COVERAGE_FAILURE": "数据覆盖不足，未生成研究倾向。",
        }.get(code, "AXIS Research 暂时不可用，请稍后重试。")

    async def _report_failure(
        self, error_type: str, ticker: str, *, detail: str | None = None
    ) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_failure(  # type: ignore[attr-defined]
                severity="ERROR",
                service="AXIS Multi-Agent Research",
                error_type=error_type,
                affected=f"RESEARCH {ticker} · test",
                detail=detail or error_type,
            )

    async def _report_recovery(self, error_type: str, ticker: str) -> None:
        alerts = self.bot.get_cog("SystemAlertsCog")
        if alerts is not None:
            await alerts.report_recovery(  # type: ignore[attr-defined]
                service="AXIS Multi-Agent Research",
                error_type=error_type,
                affected=f"RESEARCH {ticker} · test",
            )

    async def _sync_result_alerts(self, result: ResearchRunResult) -> None:
        component_codes = {
            "technical": "RESEARCH_TECHNICAL_FAILURE",
            "gex": "RESEARCH_GEX_FAILURE",
            "fundamentals": "RESEARCH_FUNDAMENTALS_FAILURE",
            "news_macro": "RESEARCH_NEWS_FAILURE",
            "sentiment": "RESEARCH_SENTIMENT_FAILURE",
        }
        for component in result.pack.components:
            code = component_codes[component.component]
            if component.status == "UNAVAILABLE":
                await self._report_failure(
                    code,
                    result.view.ticker,
                    detail=component.error_type or code,
                )
            else:
                await self._report_recovery(code, result.view.ticker)
        if result.view.insufficient_data:
            await self._report_failure("RESEARCH_MIN_COVERAGE_FAILURE", result.view.ticker)
        else:
            await self._report_recovery("RESEARCH_MIN_COVERAGE_FAILURE", result.view.ticker)
