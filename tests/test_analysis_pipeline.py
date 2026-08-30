from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.bot.views.analysis_views import AnalysisRetryView, AnalysisReviewView
from app.db.base import Base
from app.db.models import (
    AnalysisDraft,
    AnalysisDraftRevision,
    AnalysisKeyLevel,
    AnalysisPublication,
    GuildConfig,
    LlmInvocation,
    Mentor,
    MentorAnalysis,
    SourceAttachment,
    SourceMessage,
    TradeDraft,
)
from app.db.session import Database
from app.domain.enums import (
    AnalysisDraftStatus,
    LlmWorkload,
    PublicationStatus,
    SourceKind,
    SourceStatus,
)
from app.integrations.cosmos_stock_analyst import CosmosStockAnalystResult
from app.integrations.openai_analysis_parser import AnalysisParseResult
from app.integrations.openai_trade_parser import LlmInvocationTrace, TradeParseResult
from app.services.analysis_pipeline import (
    AnalysisDraftSnapshot,
    AnalysisPipelineService,
    AnalysisValidationError,
)
from app.services.attachment_storage import LocalAttachmentStore
from app.services.draft_generation import DraftGenerationService
from tests.test_openai_analysis_parser import valid_analysis_payload
from tests.test_openai_trade_parser import valid_payload as valid_trade_payload

GUILD_ID = 1543309921066684567
PNG = b"\x89PNG\r\n\x1a\naxis-test-image"


def trace(workload: LlmWorkload, *, model: str = "gpt-5.6-terra") -> LlmInvocationTrace:
    return LlmInvocationTrace(
        provider="openai",
        model=model,
        workload=workload,
        prompt_version=(
            "axis-analysis-rewrite-v2"
            if workload is LlmWorkload.ANALYSIS_REWRITE
            else "axis-analysis-parse-v2"
        ),
        schema_version="axis-analysis-v2",
        latency_ms=7,
        success=True,
        error_type=None,
        response_id=f"resp-{workload.value.lower()}",
    )


class FakeAnalysisParser:
    def __init__(self, payloads: list[dict[str, object]], workload: LlmWorkload) -> None:
        self.payloads = payloads
        self.workload = workload
        self.calls: list[dict[str, object]] = []
        self.route = SimpleNamespace(
            model="gpt-5.6-terra",
            prompt_version="axis-analysis-parse-v2",
            schema_version="axis-analysis-v2",
        )

    async def parse(self, **kwargs: object) -> AnalysisParseResult:
        self.calls.append(kwargs)
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        return AnalysisParseResult(dict(payload), trace(self.workload))


class FakeTradeParser:
    def __init__(self) -> None:
        self.calls = 0

    async def parse(
        self, *, raw_text: str | None, attachments: list[object]
    ) -> TradeParseResult:
        self.calls += 1
        return TradeParseResult(
            valid_trade_payload(),
            LlmInvocationTrace(
                provider="openai",
                model="gpt-5.6-terra",
                workload=LlmWorkload.SIGNAL_PARSE,
                prompt_version="axis-trade-parse-v1",
                schema_version="axis-trade-v1",
                latency_ms=5,
                success=True,
                error_type=None,
                response_id="resp-signal",
            ),
        )


class FakeCosmosClient:
    def __init__(self, context: dict[str, object], chart_png: bytes = PNG) -> None:
        self.context = context
        self.chart_png = chart_png
        self.calls: list[tuple[str, bool]] = []

    async def query(
        self, symbol: str, *, include_chart: bool = True
    ) -> CosmosStockAnalystResult:
        self.calls.append((symbol, include_chart))
        return CosmosStockAnalystResult(
            dict(self.context), self.chart_png if include_chart else None
        )


async def setup_database(
    tmp_path: Path,
) -> tuple[Database, LocalAttachmentStore, Mentor]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID, member_lounge_channel_id=777))
        mentor = Mentor(
            guild_id=GUILD_ID,
            name="Mentor Zero",
            short_code="M0",
            is_active=True,
        )
        session.add(mentor)
        await session.commit()
    return database, store, mentor


async def add_source(
    database: Database,
    *,
    message_id: int,
    kind: SourceKind,
    raw_text: str,
    received_at: datetime | None = None,
) -> uuid.UUID:
    async with database.session() as session:
        source = SourceMessage(
            guild_id=GUILD_ID,
            discord_message_id=message_id,
            channel_id=201,
            submitted_by=301,
            raw_text=raw_text,
            source_kind=kind.value,
            status=SourceStatus.RECEIVED.value,
            received_at=received_at or datetime.now(UTC),
        )
        session.add(source)
        await session.commit()
        return source.id


async def add_source_image(
    database: Database,
    store: LocalAttachmentStore,
    *,
    source_id: uuid.UUID,
    message_id: int,
    attachment_id: int,
    data: bytes = PNG,
) -> uuid.UUID:
    prepared = store.prepare(
        discord_attachment_id=attachment_id,
        filename="forecast.png",
        declared_content_type="image/png",
        declared_size=len(data),
        data=data,
    )
    stored = await store.write(
        guild_id=GUILD_ID,
        message_id=message_id,
        attachment=prepared,
    )
    async with database.session() as session:
        row = SourceAttachment(
            source_message_id=source_id,
            discord_attachment_id=attachment_id,
            filename=stored.display_filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            storage_key=stored.storage_key,
            checksum_sha256=stored.checksum_sha256,
        )
        session.add(row)
        await session.commit()
        return row.id


def analysis_service(
    database: Database,
    store: LocalAttachmentStore,
    parse_payloads: list[dict[str, object]],
    rewrite_payloads: list[dict[str, object]] | None = None,
    cosmos_client: FakeCosmosClient | None = None,
) -> tuple[AnalysisPipelineService, FakeAnalysisParser, FakeAnalysisParser]:
    parse_parser = FakeAnalysisParser(parse_payloads, LlmWorkload.ANALYSIS_PARSE)
    rewrite_parser = FakeAnalysisParser(
        rewrite_payloads or parse_payloads,
        LlmWorkload.ANALYSIS_REWRITE,
    )
    from app.integrations.openai_analysis_parser import load_analysis_schema

    schema = load_analysis_schema(
        Path(__file__).resolve().parents[1] / "config" / "llm_analysis_schema.json"
    )
    return (
        AnalysisPipelineService(
            database,
            store,
            parse_parser,  # type: ignore[arg-type]
            rewrite_parser,  # type: ignore[arg-type]
            schema,
            cosmos_client,  # type: ignore[arg-type]
        ),
        parse_parser,
        rewrite_parser,
    )


def cosmos_context() -> dict[str, object]:
    return {
        "ticker": "NVDA",
        "as_of": "2026-08-28",
        "trend_label": "震荡偏多",
        "trend_score": 61.0,
        "sector_etf": "SMH",
        "sector_rotation": {"rotation_phase": "LEADING"},
        "money_flow": {"label": "偏流入", "score": 64.0},
        "support_levels": [{"price": 174.25}],
        "resistance_levels": [{"price": 182.5}],
        "scenarios": [
            {
                "scenario_id": "TREND_CONTINUATION",
                "label_zh": "多头延续",
                "model_weight_percent": 48.0,
                "targets": [182.5, 188.0],
            }
        ],
    }


async def generate_and_select_mentor(
    service: AnalysisPipelineService,
    source_id: uuid.UUID,
    mentor_id: uuid.UUID,
) -> AnalysisDraftSnapshot:
    await service.generate(source_id)
    async with service.database.session() as session:
        draft_id = await session.scalar(
            select(AnalysisDraft.id).where(AnalysisDraft.source_message_id == source_id)
        )
    assert draft_id is not None
    return await service.select_mentor(
        draft_id,
        mentor_id,
        actor_user_id=901,
        interaction_id=902,
    )


@pytest.mark.asyncio
async def test_signal_and_analysis_workers_only_consume_their_own_sources(
    tmp_path: Path,
) -> None:
    database, store, _ = await setup_database(tmp_path)
    now = datetime.now(UTC)
    signal_id = await add_source(
        database,
        message_id=1001,
        kind=SourceKind.SIGNAL,
        raw_text="SPY 700C entry",
        received_at=now - timedelta(seconds=1),
    )
    analysis_id = await add_source(
        database,
        message_id=1002,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA chart view",
        received_at=now,
    )
    service, analysis_parser, _ = analysis_service(
        database, store, [valid_analysis_payload()]
    )
    trade_parser = FakeTradeParser()
    try:
        analysis_result = await service.process_next()
        signal_result = await DraftGenerationService(
            database, store, trade_parser  # type: ignore[arg-type]
        ).process_next()

        assert analysis_result is not None
        assert signal_result is not None
        assert len(analysis_parser.calls) == 1
        assert trade_parser.calls == 1
        async with database.session() as session:
            analysis_draft_source = await session.scalar(
                select(AnalysisDraft.source_message_id)
            )
            trade_draft_source = await session.scalar(select(TradeDraft.source_message_id))
        assert analysis_draft_source == analysis_id
        assert trade_draft_source == signal_id
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_analysis_without_source_projection_uses_fresh_cosmos_chart(
    tmp_path: Path,
) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1051,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 日 K 观点",
    )
    cosmos = FakeCosmosClient(cosmos_context())
    service, _, _ = analysis_service(
        database,
        store,
        [valid_analysis_payload()],
        cosmos_client=cosmos,
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        assert draft.chart_source == "COSMOS"
        assert draft.cosmos_context_json["ticker"] == "NVDA"
        assert cosmos.calls == [("NVDA", True)]
        assert any(
            "Cosmos Market Stock Analyst" in point
            for point in draft.normalized_json["supporting_points"]
        )
        media = await service.media_for_draft(draft.id)
        assert media is not None
        assert media.filename == "axis-analysis.png"
        assert media.data == PNG
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_explicit_source_projection_wins_over_generated_cosmos_chart(
    tmp_path: Path,
) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1052,
        kind=SourceKind.ANALYSIS,
        raw_text="沿用图上的预测路线",
    )
    source_png = PNG + b"-source"
    source_attachment_id = await add_source_image(
        database,
        store,
        source_id=source_id,
        message_id=1052,
        attachment_id=2052,
        data=source_png,
    )
    payload = valid_analysis_payload(
        source_projection={
            "present": True,
            "attachment_index": 0,
            "evidence": "图中白线延伸到未来 K 线区域",
        }
    )
    cosmos = FakeCosmosClient(cosmos_context(), chart_png=PNG + b"-generated")
    service, _, _ = analysis_service(
        database,
        store,
        [payload],
        cosmos_client=cosmos,
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        assert draft.chart_source == "SOURCE"
        assert draft.chart_source_attachment_id == source_attachment_id
        assert draft.chart_storage_key is None
        assert cosmos.calls == [("NVDA", False)]
        media = await service.media_for_draft(draft.id)
        assert media is not None
        assert media.data == source_png
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_rewrite_replaces_generated_cosmos_media_without_path_collision(
    tmp_path: Path,
) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1053,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 更新观点",
    )
    cosmos = FakeCosmosClient(cosmos_context(), chart_png=PNG + b"-first")
    service, _, _ = analysis_service(
        database,
        store,
        [valid_analysis_payload()],
        rewrite_payloads=[valid_analysis_payload(summary="重写后的观点")],
        cosmos_client=cosmos,
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        first_key = draft.chart_storage_key
        cosmos.chart_png = PNG + b"-second"

        updated = await service.rewrite(
            draft.id,
            "重新整理",
            actor_user_id=301,
            interaction_id=None,
        )

        async with database.session() as session:
            refreshed = await session.get(AnalysisDraft, draft.id)
        assert refreshed is not None
        assert refreshed.chart_storage_key != first_key
        assert updated.revision == 2
        media = await service.media_for_draft(draft.id)
        assert media is not None and media.data == PNG + b"-second"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_archive_only_is_immutable_idempotent_and_never_creates_publication(
    tmp_path: Path,
) -> None:
    database, store, mentor = await setup_database(tmp_path)
    raw = "NVDA raw source must remain unchanged"
    source_id = await add_source(
        database,
        message_id=1101,
        kind=SourceKind.ANALYSIS,
        raw_text=raw,
    )
    payload = valid_analysis_payload()
    service, _, _ = analysis_service(database, store, [payload])
    try:
        draft = await generate_and_select_mentor(service, source_id, mentor.id)
        first = await service.archive(
            draft.id,
            publish=False,
            actor_user_id=901,
            interaction_id=903,
        )
        second = await service.archive(
            draft.id,
            publish=False,
            actor_user_id=901,
            interaction_id=904,
        )

        assert first.analysis_id == second.analysis_id
        assert first.publication_id is None
        assert first.card is None
        async with database.session() as session:
            source = await session.get(SourceMessage, source_id)
            analysis = await session.get(MentorAnalysis, first.analysis_id)
            publication_count = await session.scalar(
                select(func.count()).select_from(AnalysisPublication)
            )
        assert source is not None and source.raw_text == raw
        assert analysis is not None
        assert analysis.normalized_json == payload
        assert analysis.public_snapshot is None
        assert analysis.llm_model == "gpt-5.6-terra"
        assert publication_count == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_archive_requires_mentor_and_rejects_unknown_type(tmp_path: Path) -> None:
    database, store, mentor = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1201,
        kind=SourceKind.ANALYSIS,
        raw_text="Unclassified market note",
    )
    service, _, _ = analysis_service(
        database, store, [valid_analysis_payload(analysis_type="UNKNOWN")]
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft_id = await session.scalar(select(AnalysisDraft.id))
        assert draft_id is not None
        with pytest.raises(AnalysisValidationError, match="ANALYSIS_NOT_ARCHIVABLE"):
            await service.archive(
                draft_id,
                publish=False,
                actor_user_id=901,
                interaction_id=905,
            )
        await service.select_mentor(
            draft_id,
            mentor.id,
            actor_user_id=901,
            interaction_id=906,
        )
        with pytest.raises(AnalysisValidationError, match="ANALYSIS_TYPE_REQUIRED"):
            await service.archive(
                draft_id,
                publish=False,
                actor_user_id=901,
                interaction_id=907,
            )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_publish_uses_public_whitelist_and_failure_retry_preserves_archive(
    tmp_path: Path,
) -> None:
    database, store, mentor = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1301,
        kind=SourceKind.ANALYSIS,
        raw_text="Private Mentor Zero note for NVDA",
    )
    payload = valid_analysis_payload(
        key_levels=[
            {
                "symbol": "NVDA",
                "level_type": "WATCH",
                "price": None,
                "note": "No explicit source price",
            }
        ]
    )
    service, _, _ = analysis_service(database, store, [payload])
    try:
        draft = await generate_and_select_mentor(service, source_id, mentor.id)
        archived = await service.archive(
            draft.id,
            publish=True,
            actor_user_id=901,
            interaction_id=908,
        )

        assert archived.publication_id is not None
        assert archived.channel_id == 777
        assert archived.card is not None
        public_payload = asdict(archived.card)
        assert public_payload["key_levels"][0]["price"] is None
        forbidden = {
            "mentor",
            "mentor_id",
            "raw_text",
            "source_message_id",
            "confidence",
            "llm_model",
            "llm_workload",
            "prompt_version",
            "schema_version",
        }
        assert forbidden.isdisjoint(public_payload)

        failed = await service.fail_publication(
            archived.publication_id, "DISCORD_SEND_FAILED"
        )
        assert failed.status == AnalysisDraftStatus.PUBLISH_FAILED.value
        retried = await service.retry_publication(draft.id)
        assert retried.analysis_id == archived.analysis_id
        assert retried.publication_id == archived.publication_id
        published = await service.finalize_publication(
            archived.publication_id, message_id=888
        )
        assert published.status == AnalysisDraftStatus.PUBLISHED.value

        async with database.session() as session:
            analysis = await session.get(MentorAnalysis, archived.analysis_id)
            publication = await session.get(AnalysisPublication, archived.publication_id)
            level = await session.scalar(select(AnalysisKeyLevel))
            count = await session.scalar(select(func.count()).select_from(MentorAnalysis))
        assert analysis is not None and analysis.public_snapshot is not None
        assert forbidden.isdisjoint(analysis.public_snapshot)
        assert publication is not None
        assert publication.status == PublicationStatus.PUBLISHED.value
        assert publication.message_id == 888
        assert level is not None and level.price is None
        assert count == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_rewrite_creates_traced_revision_without_changing_raw_source(
    tmp_path: Path,
) -> None:
    database, store, _ = await setup_database(tmp_path)
    raw = "Original macro observation"
    source_id = await add_source(
        database,
        message_id=1401,
        kind=SourceKind.ANALYSIS,
        raw_text=raw,
    )
    original = valid_analysis_payload(summary="Original normalized draft")
    rewritten = valid_analysis_payload(summary="Concise revision")
    service, _, rewrite_parser = analysis_service(
        database, store, [original], [rewritten]
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
            assert draft is not None
            draft.status = AnalysisDraftStatus.PARSE_FAILED.value
            source = await session.get(SourceMessage, source_id)
            assert source is not None
            source.status = SourceStatus.FAILED.value
            await session.commit()
            draft_id = draft.id
        updated = await service.rewrite(
            draft_id,
            "更简洁",
            actor_user_id=901,
            interaction_id=909,
        )

        assert updated.revision == 2
        assert updated.status == AnalysisDraftStatus.PENDING_REVIEW.value
        assert updated.normalized["summary"] == "Concise revision"
        assert rewrite_parser.calls[0]["current_payload"] == original
        assert rewrite_parser.calls[0]["rewrite_instruction"] == "更简洁"
        async with database.session() as session:
            source = await session.get(SourceMessage, source_id)
            revision = await session.scalar(select(AnalysisDraftRevision))
            invocations = (
                await session.scalars(select(LlmInvocation).order_by(LlmInvocation.created_at))
            ).all()
        assert source is not None and source.raw_text == raw
        assert source.status == SourceStatus.PARSED.value
        assert revision is not None
        assert revision.normalized_json == rewritten
        assert revision.instruction == "更简洁"
        assert [item.workload for item in invocations] == [
            LlmWorkload.ANALYSIS_PARSE.value,
            LlmWorkload.ANALYSIS_REWRITE.value,
        ]
        assert revision.llm_invocation_id == invocations[1].id
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_same_mentor_and_symbol_from_new_source_creates_new_analysis(
    tmp_path: Path,
) -> None:
    database, store, mentor = await setup_database(tmp_path)
    first_source = await add_source(
        database,
        message_id=1501,
        kind=SourceKind.ANALYSIS,
        raw_text="First NVDA observation",
    )
    second_source = await add_source(
        database,
        message_id=1502,
        kind=SourceKind.ANALYSIS,
        raw_text="Second NVDA observation",
    )
    first_payload = valid_analysis_payload(summary="First immutable analysis")
    second_payload = valid_analysis_payload(summary="Second independent analysis")
    service, _, _ = analysis_service(database, store, [first_payload, second_payload])
    try:
        first_draft = await generate_and_select_mentor(service, first_source, mentor.id)
        first = await service.archive(
            first_draft.id,
            publish=False,
            actor_user_id=901,
            interaction_id=910,
        )
        second_draft = await generate_and_select_mentor(service, second_source, mentor.id)
        second = await service.archive(
            second_draft.id,
            publish=False,
            actor_user_id=901,
            interaction_id=911,
        )

        async with database.session() as session:
            rows = (
                await session.scalars(
                    select(MentorAnalysis).order_by(MentorAnalysis.analysis_code)
                )
            ).all()
        assert first.analysis_id != second.analysis_id
        assert [item.analysis_code for item in rows] == ["AN-0001", "AN-0002"]
        assert rows[0].normalized_json["summary"] == "First immutable analysis"
        assert rows[1].normalized_json["summary"] == "Second independent analysis"
    finally:
        await database.dispose()


@pytest.mark.parametrize("analysis_type", ["MARKET", "TICKER", "SECTOR", "MACRO"])
def test_all_supported_analysis_types_pass_archive_validation(analysis_type: str) -> None:
    AnalysisPipelineService._validate_archive(
        valid_analysis_payload(analysis_type=analysis_type)
    )


def test_analysis_views_have_stable_unique_persistent_component_ids() -> None:
    draft_id = uuid.uuid4()
    draft = AnalysisDraftSnapshot(
        id=draft_id,
        guild_id=GUILD_ID,
        draft_code="AN-D-TEST",
        status=AnalysisDraftStatus.PENDING_REVIEW.value,
        normalized=valid_analysis_payload(),
        mentor_name=None,
        missing_fields=(),
        warnings=(),
        confidence=Decimal("0.82"),
        review_channel_id=201,
        review_message_id=202,
        revision=1,
        version=3,
        chart_source=None,
    )
    controller = SimpleNamespace()

    review_ids = {
        item.custom_id for item in AnalysisReviewView(controller, draft).children
    }
    retry_ids = {item.custom_id for item in AnalysisRetryView(controller, draft).children}

    assert review_ids == {
        f"axis:analysis:{action}:{draft_id.hex}:v3"
        for action in ("mentor", "edit", "rewrite", "archive", "publish", "delete")
    }
    assert retry_ids == {f"axis:analysis:retry:{draft_id.hex}:v3"}
