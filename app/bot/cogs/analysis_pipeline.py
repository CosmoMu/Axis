from __future__ import annotations

import logging
from io import BytesIO

import discord
from discord.ext import commands, tasks

from app.bot.cards import build_analysis_review_embed, build_public_analysis_embed
from app.bot.cogs.signal_input import is_signal_manager
from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.bot.ephemeral import (
    ERROR_DELETE_AFTER,
    SUCCESS_DELETE_AFTER,
    send_temporary_ephemeral,
)
from app.bot.message_input import extract_message_input
from app.bot.views.analysis_views import AnalysisRetryView, AnalysisReviewView
from app.domain.enums import AnalysisDraftStatus, SourceKind
from app.services.analysis_pipeline import (
    AnalysisArchiveResult,
    AnalysisDraftSnapshot,
    AnalysisError,
    AnalysisPipelineService,
)
from app.services.signal_input import (
    IncomingSignal,
    IngestDisposition,
    SignalInputService,
)

logger = logging.getLogger(__name__)


class AnalysisPipelineCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        guild_id: int,
        input_channel_id: int,
        review_channel_id: int,
        manager_role_id: int,
        owner_user_id: int | None,
        input_service: SignalInputService,
        service: AnalysisPipelineService,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.input_channel_id = input_channel_id
        self.review_channel_id = review_channel_id
        self.manager_role_id = manager_role_id
        self.owner_user_id = owner_user_id
        self.input_service = input_service
        self.service = service
        self._registered = False
        self.worker.start()
        self.review_queue.start()

    def cog_unload(self) -> None:
        self.worker.cancel()
        self.review_queue.cancel()

    async def authorize(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        guild = interaction.guild
        allowed = (
            guild is not None
            and guild.id == self.guild_id
            and isinstance(user, discord.Member)
            and is_signal_manager(
                user_id=user.id,
                role_ids=(r.id for r in user.roles),
                guild_owner_id=guild.owner_id,
                configured_owner_id=self.owner_user_id,
                manager_role_id=self.manager_role_id,
            )
        )
        if allowed:
            return True
        await send_temporary_ephemeral(
            interaction,
            "你没有 Analysis 管理权限。",
            delete_after=ERROR_DELETE_AFTER,
        )
        return False

    async def handle_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        message = (
            f"Analysis 操作未完成：{exc.code}"
            if isinstance(exc, AnalysisError)
            else "Analysis 操作暂时失败。"
        )
        await send_temporary_ephemeral(
            interaction,
            message,
            delete_after=ERROR_DELETE_AFTER,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if (
            message.author.bot
            or message.guild is None
            or message.guild.id != self.guild_id
            or message.channel.id != self.input_channel_id
        ):
            return
        if not isinstance(message.author, discord.Member) or not is_signal_manager(
            user_id=message.author.id,
            role_ids=(r.id for r in message.author.roles),
            guild_owner_id=message.guild.owner_id,
            configured_owner_id=self.owner_user_id,
            manager_role_id=self.manager_role_id,
        ):
            await message.reply("你没有提交 Analysis 的权限。", mention_author=False)
            return
        message_input = extract_message_input(message)
        result = await self.input_service.ingest(
            IncomingSignal(
                guild_id=message.guild.id,
                message_id=message.id,
                channel_id=message.channel.id,
                submitted_by=message.author.id,
                content=message_input.content,
                received_at=message.created_at,
                attachments=message_input.attachments,
                source_kind=SourceKind.ANALYSIS,
            )
        )
        text = {
            IngestDisposition.RECEIVED: "已接收观点，正在结构化。",
            IngestDisposition.DUPLICATE: "该观点已经接收，无需重复提交。",
            IngestDisposition.REJECTED: (
                "无法接收：请提供文字或真实的 PNG/JPEG/WEBP 图片，单张不超过 10MB。"
            ),
            IngestDisposition.FAILED: "观点暂时无法保存，请稍后重试。",
        }[result.disposition]
        await message.reply(text, mention_author=False)

    @tasks.loop(seconds=5)
    async def worker(self) -> None:
        try:
            result = await self.service.process_next()
            if result is None:
                return
            channel = self.bot.get_channel(result.channel_id) or await self.bot.fetch_channel(
                result.channel_id
            )
            message = await channel.fetch_message(result.discord_message_id)
            await message.reply(
                "观点解析失败，已保存人工审核草稿。"
                if result.failed
                else f"观点草稿 {result.draft_code} 已生成。",
                mention_author=False,
            )
            await report_system_recovery(
                self.bot,
                service="Analysis Processing",
                error_type="ANALYSIS_PROCESSING_FAILED",
                affected="analysis-input → analysis-review",
            )
        except Exception as exc:
            driver_error = getattr(exc, "orig", None)
            database_error = getattr(driver_error, "orig", driver_error)
            logger.warning(
                "event=analysis_worker_failed error_type=%s db_error=%s "
                "sqlstate=%s db_table=%s db_column=%s db_constraint=%s",
                type(exc).__name__,
                type(database_error).__name__,
                getattr(database_error, "sqlstate", None),
                getattr(database_error, "table_name", None),
                getattr(database_error, "column_name", None),
                getattr(database_error, "constraint_name", None),
            )
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Analysis Processing",
                error_type="ANALYSIS_PROCESSING_FAILED",
                affected="analysis-input → analysis-review",
                detail=type(exc).__name__,
            )
            return

    @worker.before_loop
    async def before_worker(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=5)
    async def review_queue(self) -> None:
        try:
            if not self._registered:
                for draft in await self.service.registered(self.guild_id):
                    view = await self._view(draft)
                    if view and draft.review_message_id:
                        self.bot.add_view(view, message_id=draft.review_message_id)
                        try:
                            await self.refresh(draft)
                        except discord.HTTPException:
                            logger.warning(
                                "event=analysis_review_refresh_failed error_type=HTTPException"
                            )
                for draft in await self.service.published_without_review_message(self.guild_id):
                    await self._post_review(draft)
                self._registered = True
            draft = await self.service.next_unposted(self.guild_id)
            if draft:
                await self._post_review(draft)
        except Exception as exc:
            logger.warning("event=analysis_review_queue_failed error_type=%s", type(exc).__name__)
            return

    @review_queue.before_loop
    async def before_review(self) -> None:
        await self.bot.wait_until_ready()

    async def _view(self, draft: AnalysisDraftSnapshot) -> discord.ui.View | None:
        if draft.status in {
            AnalysisDraftStatus.PENDING_REVIEW.value,
            AnalysisDraftStatus.PARSE_FAILED.value,
        }:
            return AnalysisReviewView(
                self,
                draft,
                mentor_choices=await self.service.mentor_choices(draft.guild_id),
            )
        if draft.status == AnalysisDraftStatus.PUBLISH_FAILED.value:
            return AnalysisRetryView(self, draft)
        return None

    async def _post_review(self, draft: AnalysisDraftSnapshot) -> None:
        channel = self.bot.get_channel(self.review_channel_id) or await self.bot.fetch_channel(
            self.review_channel_id
        )
        marker = f"AXIS Analysis · {draft.draft_code}"
        message = None
        async for candidate in channel.history(limit=100):
            if (
                self.bot.user
                and candidate.author.id == self.bot.user.id
                and any(e.footer.text and marker in e.footer.text for e in candidate.embeds)
            ):
                message = candidate
                break
        view = await self._view(draft)
        media = await self.service.media_for_draft(draft.id)
        file = discord.File(BytesIO(media.data), filename=media.filename) if media else None
        embed = build_analysis_review_embed(
            draft, image_filename=media.filename if media else None
        )
        if message is None:
            message = (
                await channel.send(embed=embed, view=view, file=file)
                if file
                else await channel.send(embed=embed, view=view)
            )
        else:
            await message.edit(embed=embed, view=view, attachments=[file] if file else [])
        saved = await self.service.attach_review_message(
            draft.id, channel_id=self.review_channel_id, message_id=message.id
        )
        saved_view = await self._view(saved)
        if saved_view is not None:
            self.bot.add_view(saved_view, message_id=message.id)

    async def refresh(self, draft: AnalysisDraftSnapshot) -> None:
        if not draft.review_message_id:
            return
        channel = self.bot.get_channel(
            draft.review_channel_id or self.review_channel_id
        ) or await self.bot.fetch_channel(draft.review_channel_id or self.review_channel_id)
        message = await channel.fetch_message(draft.review_message_id)
        media = await self.service.media_for_draft(draft.id)
        file = discord.File(BytesIO(media.data), filename=media.filename) if media else None
        await message.edit(
            embed=build_analysis_review_embed(
                draft, image_filename=media.filename if media else None
            ),
            view=await self._view(draft),
            attachments=[file] if file else [],
        )

    async def retry_chart_interaction(
        self, interaction: discord.Interaction, draft: AnalysisDraftSnapshot
    ) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.service.retry_prediction_chart(draft.id)
            await self.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "图片已重新生成。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def archive_interaction(
        self, interaction: discord.Interaction, draft: AnalysisDraftSnapshot, *, publish: bool
    ) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.service.archive(
                draft.id,
                publish=publish,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            updated = await self.publish_result(result) if publish else result.draft
            await self.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "观点已归档并发布。" if publish else "观点已仅归档。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def publish_result(self, result: AnalysisArchiveResult) -> AnalysisDraftSnapshot:
        if (
            result.publication_id is None
            or result.channel_id is None
            or result.public_ref is None
            or result.card is None
            ):
            return result.draft
        if result.message_id is not None:
            return await self.service.finalize_publication(
                result.publication_id, message_id=result.message_id
            )
        channel = self.bot.get_channel(result.channel_id) or await self.bot.fetch_channel(
            result.channel_id
        )
        marker = f"AXIS Analysis · {result.public_ref}"
        message = None
        media = await self.service.media_for_draft(result.draft.id)
        file = discord.File(BytesIO(media.data), filename=media.filename) if media else None
        embed = build_public_analysis_embed(
            result.card,
            public_ref=result.public_ref,
            image_filename=media.filename if media else None,
        )
        try:
            async for candidate in channel.history(limit=200):
                if (
                    self.bot.user
                    and candidate.author.id == self.bot.user.id
                    and any(e.footer.text == marker for e in candidate.embeds)
                ):
                    message = candidate
                    break
            if message is None:
                message = (
                    await channel.send(embed=embed, file=file)
                    if file
                    else await channel.send(embed=embed)
                )
            else:
                await message.edit(embed=embed, attachments=[file] if file else [])
        except discord.HTTPException:
            return await self.service.fail_publication(result.publication_id, "DISCORD_SEND_FAILED")
        return await self.service.finalize_publication(result.publication_id, message_id=message.id)
