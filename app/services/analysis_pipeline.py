from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalysisDraft,
    AnalysisDraftRevision,
    AnalysisKeyLevel,
    AnalysisPoint,
    AnalysisPublication,
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
from app.services.attachment_storage import AttachmentStorageError, LocalAttachmentStore


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


EDITABLE = {
    AnalysisDraftStatus.PENDING_REVIEW.value,
    AnalysisDraftStatus.PARSE_FAILED.value,
}


class AnalysisPipelineService:
    def __init__(
        self,
        database: Database,
        attachment_store: LocalAttachmentStore,
        parse_parser: OpenAIAnalysisParser,
        rewrite_parser: OpenAIAnalysisParser,
        schema: dict[str, Any],
    ) -> None:
        self.database = database
        self.attachment_store = attachment_store
        self.parse_parser = parse_parser
        self.rewrite_parser = rewrite_parser
        self.validator = Draft202012Validator(schema)

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
            result = await self.parse_parser.parse(
                raw_text=snapshot[1], attachments=await self._attachments(source_id)
            )
            return await self._persist_generation(source_id, snapshot, result, failed=False)
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
        if list(self.validator.iter_errors(payload)):
            raise AnalysisValidationError("ANALYSIS_PAYLOAD_INVALID")
        async with self.database.session() as session:
            draft = await self._locked_editable(session, draft_id)
            draft.normalized_json = payload
            draft.missing_fields = list(payload.get("missing_fields", []))
            draft.warnings = list(payload.get("warnings", []))
            draft.reviewed_by = actor_user_id
            draft.revision += 1
            draft.version += 1
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
            current = dict(draft.normalized_json)
            source_id = source.id
            raw_text = source.raw_text
        result = await self.rewrite_parser.parse(
            raw_text=raw_text,
            attachments=await self._attachments(source_id),
            rewrite_instruction=instruction,
            current_payload=current,
        )
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
            draft.normalized_json = result.payload
            draft.missing_fields = list(result.payload.get("missing_fields", []))
            draft.warnings = list(result.payload.get("warnings", []))
            draft.reviewed_by = actor_user_id
            draft.status = AnalysisDraftStatus.PENDING_REVIEW.value
            source.status = SourceStatus.PARSED.value
            draft.revision += 1
            draft.version += 1
            session.add(
                AnalysisDraftRevision(
                    draft_id=draft.id,
                    revision=draft.revision,
                    normalized_json=result.payload,
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
                invalidation=payload.get("invalidation"),
                sector=payload.get("sector"),
                normalized_json=payload,
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
    ) -> AnalysisGenerationResult:
        guild_id, _, actor, channel_id, message_id = source_snapshot
        invocation = self._invocation(guild_id, source_id, result.trace)
        draft = AnalysisDraft(
            id=uuid.uuid4(),
            guild_id=guild_id,
            draft_code=f"AN-D-{uuid.uuid4().hex[:8].upper()}",
            source_message_id=source_id,
            llm_invocation_id=invocation.id,
            status=(
                AnalysisDraftStatus.PARSE_FAILED.value
                if failed
                else AnalysisDraftStatus.PENDING_REVIEW.value
            ),
            normalized_json=result.payload,
            missing_fields=list(result.payload.get("missing_fields", [])),
            warnings=list(result.payload.get("warnings", [])),
            parser_confidence=Decimal(str(result.payload.get("confidence", 0))),
        )
        async with self.database.session() as session:
            source = await session.get(SourceMessage, source_id)
            if source is None:
                raise AnalysisValidationError("SOURCE_NOT_FOUND")
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

    async def _attachments(self, source_id: uuid.UUID) -> list[ParserAttachment]:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(SourceAttachment)
                    .where(SourceAttachment.source_message_id == source_id)
                    .order_by(SourceAttachment.created_at, SourceAttachment.id)
                )
            ).all()
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
        return PublicAnalysisCard(
            analysis_code=analysis.analysis_code,
            analysis_type=payload["analysis_type"],
            symbols=tuple(payload.get("symbols", [])),
            sector=payload.get("sector"),
            stance=payload["stance"],
            time_horizon=payload["time_horizon"],
            title=payload.get("title"),
            summary=payload.get("summary"),
            core_thesis=payload.get("core_thesis"),
            supporting_points=tuple(payload.get("supporting_points", [])),
            key_levels=tuple(payload.get("key_levels", [])),
            invalidation=payload.get("invalidation"),
            catalysts=tuple(payload.get("catalysts", [])),
            risks=tuple(payload.get("risks", [])),
            market_conditions=tuple(payload.get("market_conditions", [])),
            related_symbols=tuple(payload.get("related_symbols", [])),
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
                    level_type=level["level_type"],
                    price=level.get("price"),
                    note=level.get("note"),
                )
            )
        for point_type, key in (
            ("SUPPORTING", "supporting_points"),
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
            "key_levels": [],
            "invalidation": None,
            "catalysts": [],
            "risks": [],
            "market_conditions": [],
            "related_symbols": [],
            "confidence": 0,
            "missing_fields": ["manual_review"],
            "warnings": [error],
        }
