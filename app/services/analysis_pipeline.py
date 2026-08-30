from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalysisDraft,
    AnalysisDraftRevision,
    AnalysisIndicator,
    AnalysisKeyLevel,
    AnalysisPoint,
    AnalysisPredictionPoint,
    AnalysisPublication,
    AnalysisScenario,
    AnalysisSymbol,
    AuditLog,
    GuildConfig,
    LlmInvocation,
    Mentor,
    MentorAnalysis,
    SourceAttachment,
    SourceMessage,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import (
    AnalysisDraftStatus,
    AnalysisHorizon,
    AnalysisStance,
    AnalysisType,
    LlmWorkload,
    PublicationStatus,
    SourceKind,
    SourceStatus,
)
from app.domain.public_cards import PublicAnalysisCard
from app.integrations.openai_analysis_parser import (
    AnalysisParseError,
    AnalysisParseResult,
    OpenAIAnalysisParser,
)
from app.integrations.openai_trade_parser import LlmInvocationTrace, ParserAttachment
from app.market_intelligence.stock_analyst import (
    AxisStockAnalystError,
    AxisStockAnalystService,
    PredictionChartError,
    merge_stock_analysis,
    render_prediction_chart,
    sanitize_input_analysis,
)
from app.services.attachment_storage import AttachmentStorageError, LocalAttachmentStore
from app.services.input_codes import next_input_code
from app.services.review_cleanup import ReviewMessageRef


class AnalysisError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AnalysisValidationError(AnalysisError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisDraftSnapshot:
    id: uuid.UUID
    guild_id: int
    draft_code: str
    status: str
    normalized: dict[str, Any]
    mentor_name: str | None
    missing_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    confidence: Decimal | None
    review_channel_id: int | None
    review_message_id: int | None
    revision: int
    version: int
    chart_source: str | None
    normalized_mentor: dict[str, Any]
    market_context: dict[str, Any]
    conflicts: tuple[dict[str, Any], ...]
    chart_render_error: str | None


@dataclass(frozen=True, slots=True)
class AnalysisGenerationResult:
    draft_code: str
    channel_id: int
    discord_message_id: int
    failed: bool


@dataclass(frozen=True, slots=True)
class AnalysisArchiveResult:
    draft: AnalysisDraftSnapshot
    analysis_id: uuid.UUID
    publication_id: uuid.UUID | None
    channel_id: int | None
    public_ref: str | None
    card: PublicAnalysisCard | None
    message_id: int | None


@dataclass(frozen=True, slots=True)
class AnalysisMedia:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class AnalysisEnrichment:
    payload: dict[str, Any]
    mentor_payload: dict[str, Any]
    market_context: dict[str, Any]
    chart_source: str | None
    source_attachment_id: uuid.UUID | None
    generated_chart_png: bytes | None
    chart_render_error: str | None


EDITABLE = {
    AnalysisDraftStatus.PENDING_REVIEW.value,
    AnalysisDraftStatus.PARSE_FAILED.value,
}
ANALYSIS_CLEANUP_REVIEW_STATUSES = {
    AnalysisDraftStatus.ARCHIVED.value,
    AnalysisDraftStatus.PUBLISHED.value,
    AnalysisDraftStatus.DELETED.value,
}


class AnalysisPipelineService:
    def __init__(
        self,
        database: Database,
        attachment_store: LocalAttachmentStore,
        parse_parser: OpenAIAnalysisParser,
        rewrite_parser: OpenAIAnalysisParser,
        schema: dict[str, Any],
        stock_analyst: AxisStockAnalystService | None = None,
    ) -> None:
        self.database = database
        self.attachment_store = attachment_store
        self.parse_parser = parse_parser
        self.rewrite_parser = rewrite_parser
        self.validator = Draft202012Validator(schema)
        self.stock_analyst = stock_analyst

    async def process_next(self) -> AnalysisGenerationResult | None:
        async with self.database.session() as session:
            source_id = await session.scalar(
                select(SourceMessage.id)
                .where(
                    SourceMessage.source_kind == SourceKind.ANALYSIS.value,
                    SourceMessage.status.in_(
                        [SourceStatus.RECEIVED.value, SourceStatus.PROCESSING.value]
                    ),
                    ~exists().where(AnalysisDraft.source_message_id == SourceMessage.id),
                )
                .order_by(SourceMessage.received_at, SourceMessage.id)
                .limit(1)
            )
        return await self.generate(source_id) if source_id is not None else None

    async def generate(self, source_id: uuid.UUID) -> AnalysisGenerationResult:
        async with self.database.session() as session:
            existing = await session.scalar(
                select(AnalysisDraft).where(AnalysisDraft.source_message_id == source_id)
            )
            source = await session.get(SourceMessage, source_id)
            if source is None or source.source_kind != SourceKind.ANALYSIS.value:
                raise AnalysisValidationError("ANALYSIS_SOURCE_NOT_FOUND")
            if source.status not in {
                SourceStatus.RECEIVED.value,
                SourceStatus.PROCESSING.value,
            }:
                raise AnalysisValidationError("ANALYSIS_SOURCE_NOT_PROCESSABLE")
            if existing is not None:
                return AnalysisGenerationResult(
                    existing.draft_code,
                    source.channel_id,
                    source.discord_message_id,
                    existing.status == AnalysisDraftStatus.PARSE_FAILED.value,
                )
            source.status = SourceStatus.PROCESSING.value
            await session.commit()
            snapshot = (
                source.guild_id,
                source.raw_text,
                source.submitted_by,
                source.channel_id,
                source.discord_message_id,
            )
        try:
            attachment_rows = await self._attachment_rows(source_id)
            result = await self.parse_parser.parse(
                raw_text=snapshot[1],
                attachments=await self._parser_attachments(attachment_rows),
            )
            enrichment = await self._enrich(result.payload, attachment_rows)
            return await self._persist_generation(
                source_id,
                snapshot,
                result,
                failed=False,
                enrichment=enrichment,
            )
        except (AnalysisParseError, AttachmentStorageError) as exc:
            trace = exc.trace if isinstance(exc, AnalysisParseError) else None
            error_code = (
                exc.code if isinstance(exc, AnalysisParseError) else "ATTACHMENT_READ_FAILED"
            )
            fallback_trace = trace or LlmInvocationTrace(
                provider="openai",
                model=self.parse_parser.route.model,
                workload=LlmWorkload.ANALYSIS_PARSE,
                prompt_version=self.parse_parser.route.prompt_version,
                schema_version=self.parse_parser.route.schema_version,
                latency_ms=0,
                success=False,
                error_type=error_code,
                response_id=None,
            )
            return await self._persist_generation(
                source_id,
                snapshot,
                AnalysisParseResult(
                    payload=self._failure_payload(error_code), trace=fallback_trace
                ),
                failed=True,
                enrichment=None,
            )

    async def next_unposted(self, guild_id: int) -> AnalysisDraftSnapshot | None:
        async with self.database.session() as session:
            draft = await session.scalar(
                select(AnalysisDraft)
                .where(
                    AnalysisDraft.guild_id == guild_id,
                    AnalysisDraft.status.in_(EDITABLE),
                    AnalysisDraft.review_message_id.is_(None),
                )
                .order_by(AnalysisDraft.created_at, AnalysisDraft.id)
                .limit(1)
            )
            return await self._snapshot(session, draft) if draft is not None else None

    async def registered(self, guild_id: int) -> list[AnalysisDraftSnapshot]:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(AnalysisDraft)
                    .where(
                        AnalysisDraft.guild_id == guild_id,
                        AnalysisDraft.status.in_(
                            [*EDITABLE, AnalysisDraftStatus.PUBLISH_FAILED.value]
                        ),
                        AnalysisDraft.review_message_id.is_not(None),
                    )
                    .order_by(AnalysisDraft.created_at)
                )
            ).all()
            return [await self._snapshot(session, row) for row in rows]

    async def review_cleanup_candidates(
        self,
        guild_id: int,
        *,
        updated_before: datetime,
        limit: int = 25,
    ) -> list[ReviewMessageRef]:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(
                        AnalysisDraft.id,
                        AnalysisDraft.review_channel_id,
                        AnalysisDraft.review_message_id,
                    )
                    .where(
                        AnalysisDraft.guild_id == guild_id,
                        AnalysisDraft.status.in_(ANALYSIS_CLEANUP_REVIEW_STATUSES),
                        AnalysisDraft.review_channel_id.is_not(None),
                        AnalysisDraft.review_message_id.is_not(None),
                        AnalysisDraft.updated_at <= updated_before,
                    )
                    .order_by(AnalysisDraft.updated_at, AnalysisDraft.id)
                    .limit(limit)
                )
            ).all()
        return [
            ReviewMessageRef(draft_id, channel_id, message_id)
            for draft_id, channel_id, message_id in rows
            if channel_id is not None and message_id is not None
        ]

    async def release_review_message(self, ref: ReviewMessageRef) -> bool:
        async with self.database.session() as session:
            draft = await session.scalar(
                select(AnalysisDraft)
                .where(
                    AnalysisDraft.id == ref.draft_id,
                    AnalysisDraft.status.in_(ANALYSIS_CLEANUP_REVIEW_STATUSES),
                    AnalysisDraft.review_channel_id == ref.channel_id,
                    AnalysisDraft.review_message_id == ref.message_id,
                )
                .with_for_update()
            )
            if draft is None:
                return False
            draft.review_message_id = None
            await session.commit()
            return True

    async def get(self, draft_id: uuid.UUID) -> AnalysisDraftSnapshot:
        async with self.database.session() as session:
            draft = await session.get(AnalysisDraft, draft_id)
            if draft is None:
                raise AnalysisValidationError("ANALYSIS_DRAFT_NOT_FOUND")
            return await self._snapshot(session, draft)

    async def attach_review_message(
        self, draft_id: uuid.UUID, *, channel_id: int, message_id: int
    ) -> AnalysisDraftSnapshot:
        async with self.database.session() as session:
            draft = await session.get(AnalysisDraft, draft_id)
            if draft is None:
                raise AnalysisValidationError("ANALYSIS_DRAFT_NOT_FOUND")
            if draft.review_message_id is None:
                draft.review_channel_id = channel_id
                draft.review_message_id = message_id
                await session.commit()
            return await self._snapshot(session, draft)

    async def mentor_choices(self, guild_id: int) -> list[tuple[uuid.UUID, str]]:
        async with self.database.session() as session:
            return list(
                (
                    await session.execute(
                        select(Mentor.id, Mentor.name)
                        .where(Mentor.guild_id == guild_id, Mentor.is_active.is_(True))
                        .order_by(Mentor.name)
                        .limit(25)
                    )
                ).all()
            )

    async def select_mentor(
        self,
        draft_id: uuid.UUID,
        mentor_id: uuid.UUID,
        *,
        actor_user_id: int,
        interaction_id: int,
    ) -> AnalysisDraftSnapshot:
        async with self.database.session() as session:
            draft = await self._locked_editable(session, draft_id)
            mentor = await session.get(Mentor, mentor_id)
            if mentor is None or mentor.guild_id != draft.guild_id or not mentor.is_active:
                raise AnalysisValidationError("MENTOR_UNAVAILABLE")
            draft.mentor_id = mentor.id
            draft.reviewed_by = actor_user_id
            draft.version += 1
            self._audit(session, draft, actor_user_id, interaction_id, "ANALYSIS_MENTOR_SELECTED")
            await session.commit()
            return await self._snapshot(session, draft)

    async def edit(
        self,
        draft_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        actor_user_id: int,
        interaction_id: int,
    ) -> AnalysisDraftSnapshot:
        self._validate_archive(payload)
        chart_png = None
        chart_error = None
        if payload.get("prediction_path"):
            try:
                chart_png = render_prediction_chart(payload)
            except (PredictionChartError, OSError, RuntimeError) as exc:
                chart_error = (str(exc) or type(exc).__name__)[:64]
        async with self.database.session() as session:
            draft = await self._locked_editable(session, draft_id)
            draft.normalized_json = payload
            draft.conflicts_json = list(payload.get("conflicts", []))
            draft.missing_fields = list(payload.get("missing_fields", []))
            draft.warnings = list(payload.get("warnings", []))
            draft.reviewed_by = actor_user_id
            draft.revision += 1
            draft.version += 1
            if chart_png is not None:
                stored = await self.attachment_store.write_generated_png(
                    guild_id=draft.guild_id,
                    artifact_id=uuid.uuid5(draft.id, f"manual-edit-{draft.revision}"),
                    data=chart_png,
                )
                draft.chart_source = "AXIS_STOCK_ANALYST"
                draft.chart_storage_key = stored.storage_key
                draft.chart_checksum_sha256 = stored.checksum_sha256
                draft.chart_content_type = stored.content_type
                draft.chart_render_error = None
            elif not payload.get("prediction_path"):
                draft.chart_source = None
                draft.chart_storage_key = None
                draft.chart_checksum_sha256 = None
                draft.chart_content_type = None
                draft.chart_render_error = None
            else:
                draft.chart_render_error = chart_error
            session.add(
                AnalysisDraftRevision(
                    draft_id=draft.id,
                    revision=draft.revision,
                    normalized_json=payload,
                    instruction="MANUAL_EDIT",
                    created_by=actor_user_id,
                )
            )
            self._audit(session, draft, actor_user_id, interaction_id, "ANALYSIS_EDITED")
            await session.commit()
            return await self._snapshot(session, draft)

    async def rewrite(
        self,
        draft_id: uuid.UUID,
        instruction: str,
        *,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> AnalysisDraftSnapshot:
        async with self.database.session() as session:
            draft = await self._locked_editable(session, draft_id)
            source = await session.get(SourceMessage, draft.source_message_id)
            if source is None:
                raise AnalysisValidationError("SOURCE_NOT_FOUND")
            current = dict(draft.normalized_mentor_json or draft.normalized_json)
            source_id = source.id
            raw_text = source.raw_text
        attachment_rows = await self._attachment_rows(source_id)
        result = await self.rewrite_parser.parse(
            raw_text=raw_text,
            attachments=await self._parser_attachments(attachment_rows),
            rewrite_instruction=instruction,
            current_payload=current,
        )
        enrichment = await self._enrich(result.payload, attachment_rows)
        async with self.database.session() as session:
            draft = await self._locked_editable(session, draft_id)
            source = await session.get(SourceMessage, draft.source_message_id)
            if source is None:
                raise AnalysisValidationError("SOURCE_NOT_FOUND")
            invocation = self._invocation(draft.guild_id, draft.source_message_id, result.trace)
            session.add(invocation)
            # These models intentionally have no ORM relationship. PostgreSQL therefore
            # needs the referenced invocation row flushed before dependent FK updates.
            await session.flush()
            draft.llm_invocation_id = invocation.id
            await self._apply_enrichment(draft, enrichment)
            draft.missing_fields = list(enrichment.payload.get("missing_fields", []))
            draft.warnings = list(enrichment.payload.get("warnings", []))
            draft.reviewed_by = actor_user_id
            draft.status = AnalysisDraftStatus.PENDING_REVIEW.value
            source.status = SourceStatus.PARSED.value
            draft.revision += 1
            draft.version += 1
            session.add(
                AnalysisDraftRevision(
                    draft_id=draft.id,
                    revision=draft.revision,
                    normalized_json=enrichment.payload,
                    llm_invocation_id=invocation.id,
                    instruction=instruction[:64],
                    created_by=actor_user_id,
                )
            )
            self._audit(session, draft, actor_user_id, interaction_id, "ANALYSIS_REWRITTEN")
            await session.commit()
            return await self._snapshot(session, draft)

    async def archive(
        self,
        draft_id: uuid.UUID,
        *,
        publish: bool,
        actor_user_id: int,
        interaction_id: int,
    ) -> AnalysisArchiveResult:
        async with self.database.session() as session:
            draft = await session.scalar(
                select(AnalysisDraft).where(AnalysisDraft.id == draft_id).with_for_update()
            )
            if draft is None:
                raise AnalysisValidationError("ANALYSIS_DRAFT_NOT_FOUND")
            existing = await session.scalar(
                select(MentorAnalysis).where(MentorAnalysis.draft_id == draft.id)
            )
            if existing is not None:
                return await self._archive_result(session, draft, existing)
            if draft.status not in EDITABLE or draft.mentor_id is None:
                raise AnalysisValidationError("ANALYSIS_NOT_ARCHIVABLE")
            payload = dict(draft.normalized_json)
            self._validate_archive(payload)
            source = await session.get(SourceMessage, draft.source_message_id)
            invocation = await session.get(LlmInvocation, draft.llm_invocation_id)
            config = await session.scalar(
                select(GuildConfig).where(GuildConfig.guild_id == draft.guild_id).with_for_update()
            )
            if source is None or invocation is None or config is None:
                raise AnalysisValidationError("ANALYSIS_TRACE_MISSING")
            attachments = list(
                (
                    await session.scalars(
                        select(SourceAttachment)
                        .where(SourceAttachment.source_message_id == source.id)
                        .order_by(SourceAttachment.created_at, SourceAttachment.id)
                    )
                ).all()
            )
            analysis = MentorAnalysis(
                guild_id=draft.guild_id,
                analysis_code=await self._next_code(session, draft.guild_id),
                draft_id=draft.id,
                source_message_id=draft.source_message_id,
                mentor_id=draft.mentor_id,
                analysis_type=payload["analysis_type"],
                stance=payload["stance"],
                time_horizon=payload["time_horizon"],
                title=payload.get("title"),
                summary=payload.get("summary"),
                core_thesis=payload.get("core_thesis"),
                why_now_json=list(payload.get("why_now", [])),
                invalidation=payload.get("invalidation"),
                sector=payload.get("sector"),
                normalized_json=payload,
                raw_source_json={
                    "text": source.raw_text,
                    "source_message_id": str(source.id),
                    "attachments": [
                        {
                            "id": str(item.id),
                            "content_type": item.content_type,
                            "checksum_sha256": item.checksum_sha256,
                        }
                        for item in attachments
                    ],
                },
                normalized_mentor_json=dict(draft.normalized_mentor_json),
                stock_analyst_snapshot=dict(draft.market_context_json),
                final_fused_json=payload,
                conflict_detected=bool(payload.get("conflict_detected")),
                public_snapshot=None,
                observed_at=source.received_at,
                approved_at=utc_now(),
                publication_status=(PublicationStatus.PENDING.value if publish else None),
                llm_model=invocation.model,
                llm_workload=invocation.workload,
                prompt_version=invocation.prompt_version,
                schema_version=invocation.schema_version,
            )
            session.add(analysis)
            await session.flush()
            self._add_children(session, analysis.id, payload)
            if publish:
                if config.member_lounge_channel_id is None:
                    raise AnalysisValidationError("MEMBER_LOUNGE_NOT_CONFIGURED")
                card = self._public_card(analysis, payload)
                analysis.public_snapshot = self._json_snapshot(card)
                session.add(
                    AnalysisPublication(
                        guild_id=draft.guild_id,
                        analysis_id=analysis.id,
                        channel_id=config.member_lounge_channel_id,
                        public_ref=f"AN-P-{uuid.uuid4().hex[:10].upper()}",
                        status=PublicationStatus.PENDING.value,
                    )
                )
            draft.status = AnalysisDraftStatus.ARCHIVED.value
            draft.reviewed_by = actor_user_id
            draft.version += 1
            self._audit(
                session,
                draft,
                actor_user_id,
                interaction_id,
                "ANALYSIS_ARCHIVED_FOR_PUBLICATION" if publish else "ANALYSIS_ARCHIVED",
            )
            await session.commit()
            return await self._archive_result(session, draft, analysis)

    async def finalize_publication(
        self, publication_id: uuid.UUID, *, message_id: int
    ) -> AnalysisDraftSnapshot:
        async with self.database.session() as session:
            publication = await session.scalar(
                select(AnalysisPublication)
                .where(AnalysisPublication.id == publication_id)
                .with_for_update()
            )
            if publication is None:
                raise AnalysisValidationError("ANALYSIS_PUBLICATION_NOT_FOUND")
            analysis = await session.get(MentorAnalysis, publication.analysis_id)
            draft = await session.get(AnalysisDraft, analysis.draft_id if analysis else None)
            if analysis is None or draft is None:
                raise AnalysisValidationError("ANALYSIS_PUBLICATION_DATA_MISSING")
            if publication.status != PublicationStatus.PUBLISHED.value:
                publication.message_id = message_id
                publication.status = PublicationStatus.PUBLISHED.value
                publication.published_at = utc_now()
                analysis.publication_status = PublicationStatus.PUBLISHED.value
                draft.status = AnalysisDraftStatus.PUBLISHED.value
                draft.version += 1
                await session.commit()
            return await self._snapshot(session, draft)

    async def fail_publication(
        self, publication_id: uuid.UUID, error_code: str
    ) -> AnalysisDraftSnapshot:
        async with self.database.session() as session:
            publication = await session.get(AnalysisPublication, publication_id)
            analysis = await session.get(
                MentorAnalysis, publication.analysis_id if publication else None
            )
            draft = await session.get(AnalysisDraft, analysis.draft_id if analysis else None)
            if publication is None or analysis is None or draft is None:
                raise AnalysisValidationError("ANALYSIS_PUBLICATION_DATA_MISSING")
            publication.status = PublicationStatus.FAILED.value
            publication.last_error_code = error_code[:64]
            analysis.publication_status = PublicationStatus.FAILED.value
            draft.status = AnalysisDraftStatus.PUBLISH_FAILED.value
            draft.version += 1
            await session.commit()
            return await self._snapshot(session, draft)

    async def retry_publication(self, draft_id: uuid.UUID) -> AnalysisArchiveResult:
        async with self.database.session() as session:
            draft = await session.get(AnalysisDraft, draft_id)
            analysis = await session.scalar(
                select(MentorAnalysis).where(MentorAnalysis.draft_id == draft_id)
            )
            if draft is None or analysis is None:
                raise AnalysisValidationError("ANALYSIS_NOT_ARCHIVED")
            publication = await session.scalar(
                select(AnalysisPublication).where(AnalysisPublication.analysis_id == analysis.id)
            )
            if publication is None:
                raise AnalysisValidationError("ANALYSIS_PUBLICATION_NOT_FOUND")
            if publication.status == PublicationStatus.FAILED.value:
                publication.status = PublicationStatus.PENDING.value
                publication.last_error_code = None
                analysis.publication_status = PublicationStatus.PENDING.value
                await session.commit()
            return await self._archive_result(session, draft, analysis)

    async def delete(
        self, draft_id: uuid.UUID, *, actor_user_id: int, interaction_id: int
    ) -> AnalysisDraftSnapshot:
        async with self.database.session() as session:
            draft = await self._locked_editable(session, draft_id)
            draft.status = AnalysisDraftStatus.DELETED.value
            draft.reviewed_by = actor_user_id
            draft.version += 1
            self._audit(session, draft, actor_user_id, interaction_id, "ANALYSIS_DELETED")
            await session.commit()
            return await self._snapshot(session, draft)

    async def _persist_generation(
        self,
        source_id: uuid.UUID,
        source_snapshot: tuple[int, str | None, int, int, int],
        result: AnalysisParseResult,
        *,
        failed: bool,
        enrichment: AnalysisEnrichment | None,
    ) -> AnalysisGenerationResult:
        guild_id, _, actor, channel_id, message_id = source_snapshot
        invocation = self._invocation(guild_id, source_id, result.trace)
        draft_id = uuid.uuid4()
        effective = enrichment or AnalysisEnrichment(
            payload=result.payload,
            mentor_payload=result.payload,
            market_context={},
            chart_source=None,
            source_attachment_id=None,
            generated_chart_png=None,
            chart_render_error=None,
        )
        draft = AnalysisDraft(
            id=draft_id,
            guild_id=guild_id,
            draft_code="A-PENDING",
            source_message_id=source_id,
            llm_invocation_id=invocation.id,
            status=(
                AnalysisDraftStatus.PARSE_FAILED.value
                if failed
                else AnalysisDraftStatus.PENDING_REVIEW.value
            ),
            normalized_json=effective.payload,
            normalized_mentor_json=effective.mentor_payload,
            market_context_json=effective.market_context,
            conflicts_json=list(effective.payload.get("conflicts", [])),
            missing_fields=list(effective.payload.get("missing_fields", [])),
            warnings=list(effective.payload.get("warnings", [])),
            parser_confidence=Decimal(str(effective.payload.get("confidence", 0))),
            chart_source=effective.chart_source,
            chart_source_attachment_id=effective.source_attachment_id,
            chart_render_error=effective.chart_render_error,
        )
        if effective.generated_chart_png is not None:
            stored = await self.attachment_store.write_generated_png(
                guild_id=guild_id,
                artifact_id=draft_id,
                data=effective.generated_chart_png,
            )
            draft.chart_storage_key = stored.storage_key
            draft.chart_checksum_sha256 = stored.checksum_sha256
            draft.chart_content_type = stored.content_type
        async with self.database.session() as session:
            source = await session.get(SourceMessage, source_id)
            if source is None:
                raise AnalysisValidationError("SOURCE_NOT_FOUND")
            draft.draft_code = await next_input_code(session, guild_id, "ANALYSIS")
            source.status = SourceStatus.FAILED.value if failed else SourceStatus.PARSED.value
            session.add(invocation)
            # Flush the referenced row before inserting the draft that points to it.
            await session.flush()
            session.add(draft)
            self._audit(session, draft, actor, None, "ANALYSIS_DRAFT_CREATED")
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(AnalysisDraft).where(AnalysisDraft.source_message_id == source_id)
                )
                if existing is None:
                    raise
                draft = existing
        return AnalysisGenerationResult(draft.draft_code, channel_id, message_id, failed)

    async def _attachment_rows(self, source_id: uuid.UUID) -> list[SourceAttachment]:
        async with self.database.session() as session:
            rows = await session.scalars(
                select(SourceAttachment)
                .where(SourceAttachment.source_message_id == source_id)
                .order_by(SourceAttachment.created_at, SourceAttachment.id)
            )
            return list(rows.all())

    async def _parser_attachments(self, rows: list[SourceAttachment]) -> list[ParserAttachment]:
        output = []
        for row in rows:
            if row.storage_key is None or row.checksum_sha256 is None:
                raise AttachmentStorageError("attachment metadata missing")
            output.append(
                ParserAttachment(
                    content_type=row.content_type,
                    data=await self.attachment_store.read_verified(
                        row.storage_key, row.checksum_sha256
                    ),
                )
            )
        return output

    async def _attachments(self, source_id: uuid.UUID) -> list[ParserAttachment]:
        return await self._parser_attachments(await self._attachment_rows(source_id))

    async def _enrich(
        self,
        payload: dict[str, Any],
        attachment_rows: list[SourceAttachment],
    ) -> AnalysisEnrichment:
        mentor_payload = sanitize_input_analysis(payload)
        enriched = dict(mentor_payload)
        warnings = list(mentor_payload.get("warnings", []))
        source_attachment_id = None
        projection = enriched.get("source_projection")
        if isinstance(projection, dict) and projection.get("present") is True:
            index = projection.get("attachment_index")
            if isinstance(index, int) and 0 <= index < len(attachment_rows):
                source_attachment_id = attachment_rows[index].id
            else:
                warnings.append("SOURCE_PROJECTION_ATTACHMENT_INVALID")

        context: dict[str, Any] = {}
        symbols = enriched.get("symbols")
        eligible = (
            self.stock_analyst is not None
            and enriched.get("analysis_type") == AnalysisType.TICKER.value
            and isinstance(symbols, list)
            and len(symbols) == 1
            and isinstance(symbols[0], str)
        )
        if eligible:
            try:
                result = await self.stock_analyst.query(  # type: ignore[union-attr]
                    symbols[0],
                    include_chart=False,
                )
                context = result.context
                enriched = merge_stock_analysis(enriched, context)
            except AxisStockAnalystError:
                warnings.append("AXIS_STOCK_ANALYST_UNAVAILABLE")
                enriched = merge_stock_analysis(enriched, {})
        else:
            enriched = merge_stock_analysis(enriched, {})
        warnings.extend(enriched.get("warnings", []))
        enriched["warnings"] = list(dict.fromkeys(warnings))
        generated_chart_png = None
        chart_source = None
        chart_render_error = None
        if enriched.get("prediction_path"):
            try:
                generated_chart_png = render_prediction_chart(enriched)
                chart_source = "AXIS_STOCK_ANALYST"
            except (PredictionChartError, OSError, RuntimeError) as exc:
                chart_render_error = str(exc)[:64] or type(exc).__name__
                enriched["warnings"] = list(
                    dict.fromkeys([*enriched["warnings"], "AXIS_PREDICTION_CHART_FAILED"])
                )
        return AnalysisEnrichment(
            payload=enriched,
            mentor_payload=mentor_payload,
            market_context=context,
            chart_source=chart_source,
            source_attachment_id=source_attachment_id,
            generated_chart_png=generated_chart_png,
            chart_render_error=chart_render_error,
        )

    async def _apply_enrichment(self, draft: AnalysisDraft, enrichment: AnalysisEnrichment) -> None:
        draft.normalized_json = enrichment.payload
        draft.normalized_mentor_json = enrichment.mentor_payload
        draft.market_context_json = enrichment.market_context
        draft.conflicts_json = list(enrichment.payload.get("conflicts", []))
        draft.chart_source = enrichment.chart_source
        draft.chart_source_attachment_id = enrichment.source_attachment_id
        draft.chart_storage_key = None
        draft.chart_checksum_sha256 = None
        draft.chart_content_type = None
        draft.chart_render_error = enrichment.chart_render_error
        if enrichment.generated_chart_png is not None:
            stored = await self.attachment_store.write_generated_png(
                guild_id=draft.guild_id,
                artifact_id=uuid.uuid5(draft.id, f"revision-{draft.revision + 1}"),
                data=enrichment.generated_chart_png,
            )
            draft.chart_storage_key = stored.storage_key
            draft.chart_checksum_sha256 = stored.checksum_sha256
            draft.chart_content_type = stored.content_type

    async def retry_prediction_chart(self, draft_id: uuid.UUID) -> AnalysisDraftSnapshot:
        async with self.database.session() as session:
            draft = await self._locked_editable(session, draft_id)
            payload = dict(draft.normalized_json)
            guild_id = draft.guild_id
            revision = draft.revision
        try:
            png = render_prediction_chart(payload)
        except (PredictionChartError, OSError, RuntimeError) as exc:
            async with self.database.session() as session:
                draft = await self._locked_editable(session, draft_id)
                draft.chart_render_error = (str(exc) or type(exc).__name__)[:64]
                await session.commit()
            raise AnalysisValidationError("ANALYSIS_CHART_RENDER_FAILED") from exc
        stored = await self.attachment_store.write_generated_png(
            guild_id=guild_id,
            artifact_id=uuid.uuid5(draft_id, f"chart-retry-{revision}"),
            data=png,
        )
        async with self.database.session() as session:
            draft = await self._locked_editable(session, draft_id)
            draft.chart_source = "AXIS_STOCK_ANALYST"
            draft.chart_storage_key = stored.storage_key
            draft.chart_checksum_sha256 = stored.checksum_sha256
            draft.chart_content_type = stored.content_type
            draft.chart_render_error = None
            draft.version += 1
            await session.commit()
            return await self._snapshot(session, draft)

    async def media_for_draft(self, draft_id: uuid.UUID) -> AnalysisMedia | None:
        async with self.database.session() as session:
            draft = await session.get(AnalysisDraft, draft_id)
            if draft is None or draft.chart_source is None:
                return None
            if draft.chart_source == "SOURCE":
                row = await session.get(SourceAttachment, draft.chart_source_attachment_id)
                if row is None or not row.storage_key or not row.checksum_sha256:
                    raise AttachmentStorageError("analysis source media metadata missing")
                storage_key = row.storage_key
                checksum = row.checksum_sha256
                content_type = row.content_type
            else:
                if not draft.chart_storage_key or not draft.chart_checksum_sha256:
                    raise AttachmentStorageError("analysis generated media metadata missing")
                storage_key = draft.chart_storage_key
                checksum = draft.chart_checksum_sha256
                content_type = draft.chart_content_type or "image/png"
        data = await self.attachment_store.read_verified(storage_key, checksum)
        extension = {
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(content_type, ".png")
        return AnalysisMedia(
            filename=f"axis-analysis{extension}",
            content_type=content_type,
            data=data,
        )

    @staticmethod
    def _invocation(
        guild_id: int, source_id: uuid.UUID, trace: LlmInvocationTrace
    ) -> LlmInvocation:
        return LlmInvocation(
            id=uuid.uuid4(),
            guild_id=guild_id,
            source_message_id=source_id,
            provider=trace.provider,
            model=trace.model,
            workload=trace.workload.value,
            prompt_version=trace.prompt_version,
            schema_version=trace.schema_version,
            latency_ms=trace.latency_ms,
            success=trace.success,
            error_type=trace.error_type,
            provider_response_id=trace.response_id,
        )

    @staticmethod
    async def _locked_editable(session: AsyncSession, draft_id: uuid.UUID) -> AnalysisDraft:
        draft = await session.scalar(
            select(AnalysisDraft).where(AnalysisDraft.id == draft_id).with_for_update()
        )
        if draft is None or draft.status not in EDITABLE:
            raise AnalysisValidationError("ANALYSIS_NOT_EDITABLE")
        return draft

    @staticmethod
    async def _snapshot(session: AsyncSession, draft: AnalysisDraft) -> AnalysisDraftSnapshot:
        mentor_name = None
        if draft.mentor_id is not None:
            mentor_name = await session.scalar(
                select(Mentor.name).where(Mentor.id == draft.mentor_id)
            )
        return AnalysisDraftSnapshot(
            id=draft.id,
            guild_id=draft.guild_id,
            draft_code=draft.draft_code,
            status=draft.status,
            normalized=dict(draft.normalized_json),
            mentor_name=mentor_name,
            missing_fields=tuple(draft.missing_fields),
            warnings=tuple(draft.warnings),
            confidence=draft.parser_confidence,
            review_channel_id=draft.review_channel_id,
            review_message_id=draft.review_message_id,
            revision=draft.revision,
            version=draft.version,
            chart_source=draft.chart_source,
            normalized_mentor=dict(draft.normalized_mentor_json),
            market_context=dict(draft.market_context_json),
            conflicts=tuple(draft.conflicts_json),
            chart_render_error=draft.chart_render_error,
        )

    @staticmethod
    def _validate_archive(payload: dict[str, Any]) -> None:
        if payload.get("analysis_type") not in {item.value for item in AnalysisType}:
            raise AnalysisValidationError("ANALYSIS_TYPE_REQUIRED")
        if payload.get("stance") not in {item.value for item in AnalysisStance}:
            raise AnalysisValidationError("ANALYSIS_STANCE_REQUIRED")
        if payload.get("time_horizon") not in {item.value for item in AnalysisHorizon}:
            raise AnalysisValidationError("ANALYSIS_HORIZON_REQUIRED")
        if not payload.get("summary") and not payload.get("core_thesis"):
            raise AnalysisValidationError("ANALYSIS_CONTENT_REQUIRED")

    @staticmethod
    async def _next_code(session: AsyncSession, guild_id: int) -> str:
        codes = (
            await session.scalars(
                select(MentorAnalysis.analysis_code).where(MentorAnalysis.guild_id == guild_id)
            )
        ).all()
        numbers = []
        for code in codes:
            try:
                numbers.append(int(code.removeprefix("AN-")))
            except ValueError:
                continue
        return f"AN-{max(numbers, default=0) + 1:04d}"

    @staticmethod
    def _public_card(analysis: MentorAnalysis, payload: dict[str, Any]) -> PublicAnalysisCard:
        levels = tuple(
            {
                key: item.get(key)
                for key in (
                    "symbol",
                    "role",
                    "price",
                    "price_high",
                    "strength",
                    "description",
                )
            }
            for item in payload.get("key_levels", [])
            if isinstance(item, dict)
        )
        indicators = tuple(
            {
                key: item.get(key)
                for key in ("indicator_name", "value", "interpretation")
            }
            for item in payload.get("indicators", [])
            if isinstance(item, dict)
        )
        raw_top = payload.get("top_scenario")
        top_scenario = (
            {
                key: raw_top.get(key)
                for key in (
                    "scenario_id",
                    "label",
                    "model_weight_percent",
                    "trigger",
                    "targets",
                    "invalidation",
                    "direction_clear",
                )
            }
            if isinstance(raw_top, dict)
            else None
        )
        prediction_path = tuple(
            {key: item.get(key) for key in ("type", "price", "label", "sequence")}
            for item in payload.get("prediction_path", [])
            if isinstance(item, dict)
        )
        return PublicAnalysisCard(
            analysis_code=analysis.analysis_code,
            analysis_type=payload["analysis_type"],
            symbols=tuple(payload.get("symbols", [])),
            sector=payload.get("sector"),
            stance=payload["stance"],
            title=payload.get("title"),
            summary=payload.get("summary"),
            core_thesis=payload.get("core_thesis"),
            key_levels=levels,
            indicators=indicators,
            market_profile=dict(payload.get("market_profile") or {}),
            top_scenario=top_scenario,
            prediction_path=prediction_path,
            invalidation=payload.get("invalidation"),
            risks=tuple(payload.get("risks", [])),
            market_conditions=tuple(payload.get("market_conditions", [])),
            methodology_notice=payload.get("methodology_notice"),
            market_as_of=payload.get("market_as_of"),
            observed_at=analysis.observed_at,
        )

    @classmethod
    async def _archive_result(
        cls,
        session: AsyncSession,
        draft: AnalysisDraft,
        analysis: MentorAnalysis,
    ) -> AnalysisArchiveResult:
        publication = await session.scalar(
            select(AnalysisPublication).where(AnalysisPublication.analysis_id == analysis.id)
        )
        return AnalysisArchiveResult(
            draft=await cls._snapshot(session, draft),
            analysis_id=analysis.id,
            publication_id=publication.id if publication else None,
            channel_id=publication.channel_id if publication else None,
            public_ref=publication.public_ref if publication else None,
            card=(
                cls._public_card(analysis, dict(analysis.normalized_json))
                if publication is not None
                else None
            ),
            message_id=publication.message_id if publication else None,
        )

    @staticmethod
    def _add_children(
        session: AsyncSession, analysis_id: uuid.UUID, payload: dict[str, Any]
    ) -> None:
        for symbol in payload.get("symbols", []):
            session.add(
                AnalysisSymbol(analysis_id=analysis_id, symbol=symbol, symbol_kind="PRIMARY")
            )
        for symbol in payload.get("related_symbols", []):
            session.add(
                AnalysisSymbol(analysis_id=analysis_id, symbol=symbol, symbol_kind="RELATED")
            )
        for level in payload.get("key_levels", []):
            session.add(
                AnalysisKeyLevel(
                    analysis_id=analysis_id,
                    symbol=level.get("symbol"),
                    level_type=level.get("role") or level.get("level_type") or "WATCH",
                    price=level.get("price"),
                    price_high=level.get("price_high"),
                    strength=level.get("strength"),
                    note=level.get("description") or level.get("note"),
                    description=level.get("description") or level.get("note"),
                    source=(
                        "STOCK_ANALYST"
                        if level.get("source") in {"STOCK_ANALYST", "AXIS_STOCK_ANALYST"}
                        else "MENTOR_INPUT"
                    ),
                )
            )
        for position, indicator in enumerate(payload.get("indicators", [])):
            if not isinstance(indicator, dict):
                continue
            value = indicator.get("value")
            session.add(
                AnalysisIndicator(
                    analysis_id=analysis_id,
                    position=position,
                    indicator_name=str(indicator.get("indicator_name") or "Indicator")[:80],
                    indicator_value=None if value is None else str(value)[:120],
                    indicator_interpretation=indicator.get("interpretation"),
                    source=(
                        "STOCK_ANALYST"
                        if indicator.get("source") == "STOCK_ANALYST"
                        else "MENTOR_INPUT"
                    ),
                )
            )
        for position, scenario in enumerate(payload.get("scenarios", [])[:3]):
            if not isinstance(scenario, dict):
                continue
            session.add(
                AnalysisScenario(
                    analysis_id=analysis_id,
                    position=position,
                    scenario_id=str(scenario.get("scenario_id") or f"SCENARIO_{position + 1}"),
                    label=str(scenario.get("label") or "结构路径")[:160],
                    model_weight_percent=scenario.get("model_weight_percent", 0),
                    trigger=scenario.get("trigger"),
                    targets_json=list(scenario.get("targets") or []),
                    invalidation=scenario.get("invalidation"),
                    rationale=scenario.get("rationale"),
                    source=scenario.get("source", "STOCK_ANALYST"),
                )
            )
        for position, point in enumerate(payload.get("prediction_path", [])):
            if not isinstance(point, dict) or point.get("price") is None:
                continue
            session.add(
                AnalysisPredictionPoint(
                    analysis_id=analysis_id,
                    sequence=position,
                    point_type=str(point.get("type") or "STRUCTURE")[:32],
                    price=point["price"],
                    label=point.get("label"),
                )
            )
        for point_type, key in (
            ("WHY_NOW", "why_now"),
            ("SUPPORTING", "supporting_points"),
            ("ENGINE_OBSERVATION", "engine_observations"),
            ("CATALYST", "catalysts"),
            ("RISK", "risks"),
            ("MARKET_CONDITION", "market_conditions"),
        ):
            for position, content in enumerate(payload.get(key, [])):
                session.add(
                    AnalysisPoint(
                        analysis_id=analysis_id,
                        point_type=point_type,
                        position=position,
                        content=content,
                        source=(
                            "STOCK_ANALYST"
                            if key == "engine_observations"
                            else "MENTOR_INPUT"
                        ),
                    )
                )

    @staticmethod
    def _audit(
        session: AsyncSession,
        draft: AnalysisDraft,
        actor: int,
        interaction_id: int | None,
        action: str,
    ) -> None:
        session.add(
            AuditLog(
                guild_id=draft.guild_id,
                actor_user_id=actor,
                action_type=action,
                entity_type="analysis_draft",
                entity_id=str(draft.id),
                before_json=None,
                after_json={
                    "status": draft.status,
                    "revision": draft.revision,
                    "version": draft.version,
                },
                discord_interaction_id=interaction_id,
            )
        )

    @staticmethod
    def _json_snapshot(card: PublicAnalysisCard) -> dict[str, Any]:
        payload = asdict(card)
        payload["observed_at"] = card.observed_at.isoformat()
        return payload

    @staticmethod
    def _failure_payload(error: str) -> dict[str, Any]:
        return {
            "analysis_type": "UNKNOWN",
            "symbols": [],
            "sector": None,
            "stance": "WATCH",
            "time_horizon": "UNSPECIFIED",
            "title": None,
            "summary": None,
            "core_thesis": None,
            "supporting_points": [],
            "engine_observations": [],
            "key_levels": [],
            "indicators": [],
            "invalidation": None,
            "catalysts": [],
            "risks": [],
            "market_conditions": [],
            "related_symbols": [],
            "source_projection": {
                "present": False,
                "attachment_index": None,
                "evidence": None,
            },
            "confidence": 0,
            "missing_fields": ["manual_review"],
            "warnings": [error],
        }
