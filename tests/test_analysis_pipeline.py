from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest
from sqlalchemy import func, select

from app.bot.cards import build_analysis_review_embed, build_public_analysis_embed
from app.bot.views.analysis_views import AnalysisRetryView, AnalysisReviewView
from app.db.base import Base
from app.db.models import (
    AnalysisDraft,
    AnalysisDraftRevision,
    AnalysisIndicator,
    AnalysisKeyLevel,
    AnalysisPoint,
    AnalysisPredictionPoint,
    AnalysisPublication,
    AnalysisScenario,
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
from app.integrations.openai_analysis_parser import AnalysisParseResult
from app.integrations.openai_trade_parser import LlmInvocationTrace, TradeParseResult
from app.market_intelligence.stock_analyst import AxisStockAnalystError, AxisStockAnalystResult
from app.market_intelligence.stock_analyst.prediction_chart import (
    PredictionChartError,
    render_prediction_chart,
)
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
            "axis-analysis-rewrite-v7"
            if workload is LlmWorkload.ANALYSIS_REWRITE
            else "axis-analysis-parse-v7"
        ),
        schema_version="axis-analysis-v5",
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
            prompt_version="axis-analysis-parse-v7",
            schema_version="axis-analysis-v5",
        )

    async def parse(self, **kwargs: object) -> AnalysisParseResult:
        self.calls.append(kwargs)
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        return AnalysisParseResult(dict(payload), trace(self.workload))


class FakeTradeParser:
    def __init__(self) -> None:
        self.calls = 0

    async def parse(self, *, raw_text: str | None, attachments: list[object]) -> TradeParseResult:
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


class FakeStockAnalyst:
    def __init__(self, context: dict[str, object], chart_png: bytes = PNG) -> None:
        self.context = context
        self.chart_png = chart_png
        self.calls: list[tuple[str, bool, tuple[dict[str, object], ...] | None]] = []

    async def query(
        self,
        symbol: str,
        *,
        include_chart: bool = True,
        projection_points: tuple[dict[str, object], ...] | None = None,
    ) -> AxisStockAnalystResult:
        self.calls.append((symbol, include_chart, projection_points))
        return AxisStockAnalystResult(dict(self.context), self.chart_png if include_chart else None)


class FailingStockAnalyst:
    async def query(self, symbol: str, **kwargs: object) -> AxisStockAnalystResult:
        raise AxisStockAnalystError("AXIS_STOCK_HISTORY_INSUFFICIENT")


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
    stock_analyst: FakeStockAnalyst | FailingStockAnalyst | None = None,
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
            stock_analyst,  # type: ignore[arg-type]
        ),
        parse_parser,
        rewrite_parser,
    )


def axis_stock_context() -> dict[str, object]:
    return {
        "ticker": "NVDA",
        "as_of": "2026-08-28",
        "data_timestamp": "2026-08-28T20:00:00+00:00",
        "current_price": 178.0,
        "trend_label": "震荡偏多",
        "trend_score": 61.0,
        "indicator_scores": {"RSI14": 66.0, "MACD_ATR": 0.23},
        "sector_etf": "SMH",
        "sector_rotation": {"rotation_phase": "LEADING", "strength_score": 64.0},
        "money_flow": {"label": "偏流入", "score": 64.0, "signed_volume_ratio": 0.23},
        "point_of_control": 170.25,
        "value_area_low": 165.0,
        "value_area_high": 181.0,
        "support_levels": [{"price": 174.25}],
        "resistance_levels": [{"price": 182.5}],
        "scenarios": [
            {
                "scenario_id": "TREND_CONTINUATION",
                "label_zh": "多头延续",
                "model_weight_percent": 48.0,
                "targets": [182.5, 188.0],
                "invalidation": 174.25,
            },
            {
                "scenario_id": "STRUCTURAL_PULLBACK",
                "label_zh": "结构回踩",
                "model_weight_percent": 32.0,
                "targets": [174.25, 182.5],
                "invalidation": 169.0,
            },
            {
                "scenario_id": "SUPPORT_BREAKDOWN",
                "label_zh": "支撑失守",
                "model_weight_percent": 20.0,
                "targets": [169.0],
                "invalidation": 182.5,
            },
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
    service, analysis_parser, _ = analysis_service(database, store, [valid_analysis_payload()])
    trade_parser = FakeTradeParser()
    try:
        analysis_result = await service.process_next()
        signal_result = await DraftGenerationService(
            database,
            store,
            trade_parser,  # type: ignore[arg-type]
        ).process_next()

        assert analysis_result is not None
        assert signal_result is not None
        assert len(analysis_parser.calls) == 1
        assert trade_parser.calls == 1
        async with database.session() as session:
            analysis_draft = await session.scalar(select(AnalysisDraft))
            trade_draft = await session.scalar(select(TradeDraft))
        assert analysis_draft is not None
        assert trade_draft is not None
        assert analysis_draft.source_message_id == analysis_id
        assert trade_draft.source_message_id == signal_id
        assert analysis_draft.draft_code == "A-00001"
        assert trade_draft.draft_code == "S-00001"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_analysis_without_source_projection_uses_axis_text_context_only(
    tmp_path: Path,
) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1051,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 日 K 观点",
    )
    analyst = FakeStockAnalyst(axis_stock_context())
    service, _, _ = analysis_service(
        database,
        store,
        [valid_analysis_payload()],
        stock_analyst=analyst,
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        assert draft.chart_source is None
        assert draft.market_context_json["ticker"] == "NVDA"
        assert analyst.calls == [("NVDA", False, None)]
        assert any(
            item["source"] == "STOCK_ANALYST"
            for item in draft.normalized_json["key_levels"]
        )
        assert await service.media_for_draft(draft.id) is None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_stock_analyst_failure_keeps_llm_input_card_available(tmp_path: Path) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1056,
        kind=SourceKind.ANALYSIS,
        raw_text="SPCX 只按输入观点整理",
    )
    service, _, _ = analysis_service(
        database,
        store,
        [valid_analysis_payload()],
        stock_analyst=FailingStockAnalyst(),
    )
    try:
        result = await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))

        assert result.failed is False
        assert draft is not None
        assert draft.draft_code == "A-00001"
        assert draft.market_context_json == {}
        assert draft.chart_source is None
        assert "AXIS_STOCK_ANALYST_UNAVAILABLE" in draft.warnings
        assert draft.normalized_json["core_thesis"]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_source_projection_is_redrawn_for_review_and_publication(
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
            "path_points": [
                {
                    "sequence": 0,
                    "direction": "DOWN",
                    "price": 127.0,
                    "label": "回踩",
                    "source": "IMAGE",
                },
                {
                    "sequence": 1,
                    "direction": "UP",
                    "price": 136.0,
                    "label": "反弹",
                    "source": "IMAGE",
                },
                {
                    "sequence": 2,
                    "direction": "DOWN",
                    "price": None,
                    "label": "上行后回落",
                    "source": "IMAGE",
                },
            ],
        }
    )
    analyst = FakeStockAnalyst(axis_stock_context(), chart_png=PNG + b"-generated")
    service, _, _ = analysis_service(
        database,
        store,
        [payload],
        stock_analyst=analyst,
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        assert draft.chart_source == "AXIS_STOCK_ANALYST"
        assert draft.chart_source_attachment_id == source_attachment_id
        assert draft.chart_storage_key is not None
        assert analyst.calls == [("NVDA", False, None)]
        assert draft.normalized_json["source_projection"]["path_points"][0]["price"] == 127.0
        media = await service.media_for_draft(draft.id)
        assert media is not None
        assert media.data.startswith(b"\x89PNG\r\n\x1a\n")
        assert media.data != source_png
        first_retry = await service.retry_prediction_chart(draft.id)
        second_retry = await service.retry_prediction_chart(draft.id)
        assert second_retry.version == first_retry.version + 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_text_projection_levels_remain_text_only_without_source_image(
    tmp_path: Path,
) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1054,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 先回踩 127，再反弹 136，目标 155",
    )
    payload = valid_analysis_payload(
        source_projection={
            "present": False,
            "attachment_index": None,
            "evidence": "文字明确给出有顺序的未来点位",
            "path_points": [
                {
                    "sequence": 0,
                    "direction": "DOWN",
                    "price": 127.0,
                    "label": "回踩",
                    "source": "TEXT",
                },
                {
                    "sequence": 1,
                    "direction": "UP",
                    "price": 136.0,
                    "label": "反弹",
                    "source": "TEXT",
                },
                {
                    "sequence": 2,
                    "direction": "UP",
                    "price": 155.0,
                    "label": "目标",
                    "source": "TEXT",
                },
            ],
        }
    )
    analyst = FakeStockAnalyst(axis_stock_context(), chart_png=PNG + b"-text-path")
    service, _, _ = analysis_service(
        database,
        store,
        [payload],
        stock_analyst=analyst,
    )
    try:
        await service.generate(source_id)
        assert analyst.calls == [("NVDA", False, None)]
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        assert draft.chart_source is None
        assert draft.chart_source_attachment_id is None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_archive_preserves_model_a_training_provenance(tmp_path: Path) -> None:
    database, store, mentor = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1055,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 正在测试关键区域，所以现在关注。",
    )
    analyst = FakeStockAnalyst(axis_stock_context())
    service, _, _ = analysis_service(
        database,
        store,
        [valid_analysis_payload()],
        stock_analyst=analyst,
    )
    try:
        draft = await generate_and_select_mentor(service, source_id, mentor.id)
        archived = await service.archive(
            draft.id,
            publish=False,
            actor_user_id=901,
            interaction_id=9055,
        )
        async with database.session() as session:
            analysis = await session.get(MentorAnalysis, archived.analysis_id)
            levels = list(
                await session.scalars(select(AnalysisKeyLevel).order_by(AnalysisKeyLevel.source))
            )
            points = list(await session.scalars(select(AnalysisPoint)))
            indicators = list(await session.scalars(select(AnalysisIndicator)))

        assert analysis is not None
        assert analysis.why_now_json == ["输入指出价格正在测试关键区域"]
        assert {level.source for level in levels} == {"MENTOR_INPUT", "STOCK_ANALYST"}
        why_now = next(point for point in points if point.point_type == "WHY_NOW")
        assert why_now.source == "MENTOR_INPUT"
        assert {indicator.source for indicator in indicators} == {"STOCK_ANALYST"}
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_rewrite_refreshes_text_context_without_generating_media(
    tmp_path: Path,
) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1053,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 更新观点",
    )
    analyst = FakeStockAnalyst(axis_stock_context(), chart_png=PNG + b"-first")
    service, _, _ = analysis_service(
        database,
        store,
        [valid_analysis_payload()],
        rewrite_payloads=[valid_analysis_payload(summary="重写后的观点")],
        stock_analyst=analyst,
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        assert draft.chart_storage_key is None
        analyst.chart_png = PNG + b"-second"

        updated = await service.rewrite(
            draft.id,
            "重新整理",
            actor_user_id=301,
            interaction_id=None,
        )

        async with database.session() as session:
            refreshed = await session.get(AnalysisDraft, draft.id)
        assert refreshed is not None
        assert refreshed.chart_storage_key is None
        assert refreshed.chart_source is None
        assert updated.revision == 2
        assert await service.media_for_draft(draft.id) is None
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
        assert analysis.normalized_mentor_json == payload
        assert analysis.final_fused_json == analysis.normalized_json
        assert "top_scenario" in analysis.final_fused_json
        assert analysis.raw_source_json["text"] == raw
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
                "role": "WATCH",
                "price": None,
                "price_high": None,
                "strength": None,
                "description": "No explicit source price",
                "source": "MENTOR_INPUT",
            }
        ]
    )
    service, _, _ = analysis_service(database, store, [payload])
    try:
        draft = await generate_and_select_mentor(service, source_id, mentor.id)
        await service.attach_review_message(draft.id, channel_id=710, message_id=810)
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

        failed = await service.fail_publication(archived.publication_id, "DISCORD_SEND_FAILED")
        assert failed.status == AnalysisDraftStatus.PUBLISH_FAILED.value
        retried = await service.retry_publication(draft.id)
        assert retried.analysis_id == archived.analysis_id
        assert retried.publication_id == archived.publication_id
        published = await service.finalize_publication(archived.publication_id, message_id=888)
        assert published.status == AnalysisDraftStatus.PUBLISHED.value

        reopened = await service.reopen_for_review(draft.id, actor_user_id=901)
        assert reopened.status == AnalysisDraftStatus.PENDING_REVIEW.value
        preview = await service.preview_card(draft.id)
        assert preview.analysis_code == draft.draft_code
        revised_payload = dict(reopened.normalized)
        revised_payload["summary"] = "重新审核后的公开摘要"
        revised = await service.edit(
            draft.id,
            revised_payload,
            actor_user_id=901,
            interaction_id=909,
        )
        rearchived = await service.archive(
            revised.id,
            publish=True,
            actor_user_id=901,
            interaction_id=910,
        )
        assert rearchived.analysis_id == archived.analysis_id
        assert rearchived.publication_id == archived.publication_id
        assert rearchived.message_id == 888
        assert rearchived.card is not None
        assert rearchived.card.summary == "重新审核后的公开摘要"
        republished = await service.finalize_publication(
            archived.publication_id,
            message_id=888,
        )
        assert republished.status == AnalysisDraftStatus.PUBLISHED.value

        async with database.session() as session:
            stored_draft = await session.get(AnalysisDraft, draft.id)
            assert stored_draft is not None
            stored_draft.review_message_id = None
            analysis = await session.get(MentorAnalysis, archived.analysis_id)
            publication = await session.get(AnalysisPublication, archived.publication_id)
            level = await session.scalar(select(AnalysisKeyLevel))
            count = await session.scalar(select(func.count()).select_from(MentorAnalysis))
            await session.commit()
        assert analysis is not None and analysis.public_snapshot is not None
        assert forbidden.isdisjoint(analysis.public_snapshot)
        assert publication is not None
        assert publication.status == PublicationStatus.PUBLISHED.value
        assert publication.message_id == 888
        assert level is not None and level.price is None
        assert count == 1
        missing = await service.published_without_review_message(GUILD_ID)
        assert [item.id for item in missing] == [draft.id]
        restored = await service.attach_review_message(draft.id, channel_id=710, message_id=812)
        assert restored.review_message_id == 812
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
    service, _, rewrite_parser = analysis_service(database, store, [original], [rewritten])
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
        assert revision.normalized_json["summary"] == rewritten["summary"]
        assert "top_scenario" in revision.normalized_json
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
                await session.scalars(select(MentorAnalysis).order_by(MentorAnalysis.analysis_code))
            ).all()
        assert first.analysis_id != second.analysis_id
        assert [item.analysis_code for item in rows] == ["AN-0001", "AN-0002"]
        assert rows[0].normalized_json["summary"] == "First immutable analysis"
        assert rows[1].normalized_json["summary"] == "Second independent analysis"
    finally:
        await database.dispose()


def mentor_level(role: str, price: float, description: str) -> dict[str, object]:
    return {
        "symbol": "NVDA",
        "role": role,
        "price": price,
        "price_high": None,
        "strength": None,
        "description": description,
        "source": "MENTOR_INPUT",
    }


@pytest.mark.asyncio
async def test_final_fusion_is_mentor_first_and_persists_field_provenance(
    tmp_path: Path,
) -> None:
    database, store, mentor = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1601,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 支撑 174，突破 183，目标 190；ZCZL 与 MACD 改善。",
    )
    payload = valid_analysis_payload(
        key_levels=[
            mentor_level("SUPPORT", 174.0, "主要支撑"),
            mentor_level("BREAKOUT", 183.0, "关键突破"),
            mentor_level("TARGET", 190.0, "上方目标"),
            mentor_level("INVALIDATION", 171.0, "结构失效"),
        ],
        indicators=[
            {
                "indicator_name": "ZCZL",
                "value": 91,
                "interpretation": "多头结构保持完整",
                "source": "MENTOR_INPUT",
            },
            {
                "indicator_name": "MACD",
                "value": 78,
                "interpretation": "动能正在重新改善",
                "source": "MENTOR_INPUT",
            },
        ],
    )
    context = axis_stock_context()
    context["support_levels"] = [{"price": 172.8, "strength": 0.68}]
    context["resistance_levels"] = [{"price": 182.5, "strength": 0.82}]
    service, _, _ = analysis_service(
        database, store, [payload], stock_analyst=FakeStockAnalyst(context)
    )
    try:
        draft = await generate_and_select_mentor(service, source_id, mentor.id)
        levels = draft.normalized["key_levels"]
        assert [item["price"] for item in levels if item["role"] == "SUPPORT"] == [174.0]
        assert [item["price"] for item in levels if item["role"] == "BREAKOUT"] == [183.0]
        assert [item["price"] for item in levels if item["role"] == "TARGET"] == [190.0]
        assert not any(
            item["price"] == 182.5 and item["source"] == "STOCK_ANALYST"
            for item in levels
        )
        assert draft.normalized["conflict_detected"] is True
        assert {item["field"] for item in draft.conflicts} == {
            "SUPPORT",
            "TARGET",
            "INVALIDATION",
        }
        indicator_names = [item["indicator_name"] for item in draft.normalized["indicators"]]
        assert indicator_names[:2] == ["ZCZL", "MACD"]
        assert indicator_names.count("MACD") == 1
        assert "RSI14" in indicator_names

        archived = await service.archive(
            draft.id,
            publish=True,
            actor_user_id=901,
            interaction_id=1602,
        )
        assert archived.card is not None
        public_payload = asdict(archived.card)
        assert all("source" not in item for item in public_payload["key_levels"])
        assert all("source" not in item for item in public_payload["indicators"])
        embed_text = str(
            build_public_analysis_embed(archived.card, public_ref="AN-P-TEST").to_dict()
        )
        assert "MENTOR_INPUT" not in embed_text
        assert "STOCK_ANALYST" not in embed_text
        assert "观察周期" not in embed_text
        assert "依据" not in embed_text

        async with database.session() as session:
            analysis = await session.get(MentorAnalysis, archived.analysis_id)
            saved_levels = list(await session.scalars(select(AnalysisKeyLevel)))
            saved_indicators = list(await session.scalars(select(AnalysisIndicator)))
        assert analysis is not None and analysis.conflict_detected is True
        assert {item.source for item in saved_levels} == {"MENTOR_INPUT"}
        assert {item.source for item in saved_indicators} == {
            "MENTOR_INPUT",
            "STOCK_ANALYST",
        }
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_axis_fills_only_missing_level_roles(tmp_path: Path) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1611,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 目标 190，未提供支撑。",
    )
    payload = valid_analysis_payload(
        key_levels=[mentor_level("TARGET", 190.0, "上方目标")]
    )
    service, _, _ = analysis_service(
        database,
        store,
        [payload],
        stock_analyst=FakeStockAnalyst(axis_stock_context()),
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        supports = [
            item for item in draft.normalized_json["key_levels"] if item["role"] == "SUPPORT"
        ]
        targets = [
            item for item in draft.normalized_json["key_levels"] if item["role"] == "TARGET"
        ]
        assert supports and all(item["source"] == "STOCK_ANALYST" for item in supports)
        assert [item["price"] for item in targets] == [190.0]
        assert targets[0]["source"] == "MENTOR_INPUT"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_scenario_confidence_policy_publishes_only_one_top_path_and_chart(
    tmp_path: Path,
) -> None:
    database, store, mentor = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1621,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 突破 183 后观察 190，171 失效。",
    )
    payload = valid_analysis_payload(
        key_levels=[
            mentor_level("BREAKOUT", 183.0, "关键突破"),
            mentor_level("TARGET", 190.0, "上方目标"),
            mentor_level("INVALIDATION", 171.0, "结构失效"),
        ]
    )
    context = deepcopy(axis_stock_context())
    context["scenarios"][0]["model_weight_percent"] = 68.0  # type: ignore[index]
    context["scenarios"][1]["model_weight_percent"] = 22.0  # type: ignore[index]
    context["scenarios"][2]["model_weight_percent"] = 10.0  # type: ignore[index]
    analyst = FakeStockAnalyst(context)
    service, _, _ = analysis_service(database, store, [payload], stock_analyst=analyst)
    try:
        draft = await generate_and_select_mentor(service, source_id, mentor.id)
        assert draft.normalized["top_scenario"]["model_weight_percent"] == 68.0
        assert draft.normalized["top_scenario"]["direction_clear"] is True
        assert [item["price"] for item in draft.normalized["prediction_path"]] == [
            178.0,
            183.0,
            190.0,
        ]
        media = await service.media_for_draft(draft.id)
        assert media is not None and media.data.startswith(b"\x89PNG")

        archived = await service.archive(
            draft.id,
            publish=True,
            actor_user_id=901,
            interaction_id=1622,
        )
        assert archived.card is not None
        assert archived.card.top_scenario is not None
        public = asdict(archived.card)
        assert "scenarios" not in public
        assert public["top_scenario"]["model_weight_percent"] == 68.0
        async with database.session() as session:
            scenarios = list(
                await session.scalars(
                    select(AnalysisScenario).order_by(AnalysisScenario.position)
                )
            )
            points = list(
                await session.scalars(
                    select(AnalysisPredictionPoint).order_by(AnalysisPredictionPoint.sequence)
                )
            )
        assert len(scenarios) == 3
        assert [float(item.model_weight_percent) for item in scenarios] == [68.0, 22.0, 10.0]
        assert [float(item.price) for item in points] == [178.0, 183.0, 190.0]
    finally:
        await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("weights", [(42.0, 37.0, 21.0), (52.0, 45.0, 3.0)])
async def test_unclear_scenario_does_not_publish_directional_path(
    tmp_path: Path, weights: tuple[float, float, float]
) -> None:
    database, store, _ = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=int(sum(weights) * 100),
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 当前结构仍不明确。",
    )
    context = deepcopy(axis_stock_context())
    for scenario, weight in zip(context["scenarios"], weights, strict=True):  # type: ignore[arg-type]
        scenario["model_weight_percent"] = weight
    service, _, _ = analysis_service(
        database,
        store,
        [valid_analysis_payload()],
        stock_analyst=FakeStockAnalyst(context),
    )
    try:
        await service.generate(source_id)
        async with database.session() as session:
            draft = await session.scalar(select(AnalysisDraft))
        assert draft is not None
        assert draft.normalized_json["top_scenario"]["direction_clear"] is False
        assert draft.normalized_json["prediction_path"] == []
        assert await service.media_for_draft(draft.id) is None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_chart_failure_does_not_block_archive_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.analysis_pipeline as pipeline_module

    database, store, mentor = await setup_database(tmp_path)
    source_id = await add_source(
        database,
        message_id=1631,
        kind=SourceKind.ANALYSIS,
        raw_text="NVDA 突破 183 后观察 190。",
    )
    context = deepcopy(axis_stock_context())
    context["scenarios"][0]["model_weight_percent"] = 70.0  # type: ignore[index]
    context["scenarios"][1]["model_weight_percent"] = 20.0  # type: ignore[index]
    context["scenarios"][2]["model_weight_percent"] = 10.0  # type: ignore[index]
    payload = valid_analysis_payload(
        key_levels=[
            mentor_level("BREAKOUT", 183.0, "关键突破"),
            mentor_level("TARGET", 190.0, "目标"),
        ]
    )

    def fail_render(_: dict[str, object]) -> bytes:
        raise PredictionChartError("TEST_RENDER_FAILURE")

    monkeypatch.setattr(pipeline_module, "render_prediction_chart", fail_render)
    service, _, _ = analysis_service(
        database, store, [payload], stock_analyst=FakeStockAnalyst(context)
    )
    try:
        draft = await generate_and_select_mentor(service, source_id, mentor.id)
        assert draft.chart_render_error == "TEST_RENDER_FAILURE"
        monkeypatch.setattr(pipeline_module, "render_prediction_chart", render_prediction_chart)
        retried = await service.retry_prediction_chart(draft.id)
        assert retried.chart_render_error is None
        assert await service.media_for_draft(draft.id) is not None
        archived = await service.archive(
            retried.id,
            publish=False,
            actor_user_id=901,
            interaction_id=1632,
        )
        assert archived.analysis_id is not None
    finally:
        await database.dispose()


def test_public_analysis_is_neutral_and_image_independent() -> None:
    from app.market_intelligence.stock_analyst import sanitize_input_analysis

    payload = valid_analysis_payload(
        summary="如图所示，我认为 NVDA 仍在整理。",
        core_thesis="图中红线与箭头指向关键区域。",
        key_levels=[mentor_level("SUPPORT", 174.0, "图里的 Golden Zone")],
    )
    sanitized = sanitize_input_analysis(payload)
    public_text = str(sanitized)
    for forbidden in (
        "图中",
        "如图所示",
        "箭头",
        "红线",
        "蓝线",
        "我认为",
        "我觉得",
        "我关注",
        "Mentor 认为",
    ):
        assert forbidden not in public_text


def test_prediction_chart_is_deterministic_structural_png() -> None:
    payload = {
        "symbols": ["NVDA"],
        "top_scenario": {
            "model_weight_percent": 68,
            "direction_clear": True,
            "invalidation": 171,
        },
        "prediction_path": [
            {"type": "CURRENT", "price": 178, "label": "当前", "sequence": 0},
            {"type": "BREAKOUT", "price": 183, "label": "关键突破", "sequence": 1},
            {"type": "TARGET", "price": 190, "label": "目标", "sequence": 2},
        ],
    }
    first = render_prediction_chart(payload)
    second = render_prediction_chart(payload)
    assert first == second
    assert first.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("analysis_type", ["MARKET", "TICKER", "SECTOR", "MACRO"])
def test_all_supported_analysis_types_pass_archive_validation(analysis_type: str) -> None:
    AnalysisPipelineService._validate_archive(valid_analysis_payload(analysis_type=analysis_type))


def test_analysis_views_have_stable_unique_persistent_component_ids() -> None:
    draft_id = uuid.uuid4()
    draft = AnalysisDraftSnapshot(
        id=draft_id,
        guild_id=GUILD_ID,
        draft_code="AN-D-TEST",
        status=AnalysisDraftStatus.PENDING_REVIEW.value,
        normalized=valid_analysis_payload(),
        mentor_name="Mentor Zero",
        missing_fields=(),
        warnings=(),
        confidence=Decimal("0.82"),
        review_channel_id=201,
        review_message_id=202,
        revision=1,
        version=3,
        chart_source=None,
        normalized_mentor=valid_analysis_payload(),
        market_context={},
        conflicts=(),
        chart_render_error=None,
    )
    controller = SimpleNamespace()
    mentor_id = uuid.uuid4()
    review_view = AnalysisReviewView(
        controller,
        draft,
        mentor_choices=[(mentor_id, "Mentor Zero")],
    )
    review_ids = {item.custom_id for item in review_view.children}
    retry_ids = {item.custom_id for item in AnalysisRetryView(controller, draft).children}

    assert review_ids == {
        f"axis:analysis:mentor:select:{draft_id.hex}:v3"
    } | {
        f"axis:analysis:{action}:{draft_id.hex}:v3"
        for action in (
            "edit",
            "preview",
            "rewrite",
            "chart",
            "archive",
            "publish",
            "delete",
        )
    }
    mentor_select = next(
        item for item in review_view.children if isinstance(item, discord.ui.Select)
    )
    buttons = [item for item in review_view.children if isinstance(item, discord.ui.Button)]
    assert mentor_select.row == 0
    assert [option.value for option in mentor_select.options if option.default] == [str(mentor_id)]
    assert [(button.label, button.row) for button in buttons] == [
        ("编辑", 1),
        ("预览", 1),
        ("重新生成文本", 1),
        ("重新生成图片", 1),
        ("仅归档", 2),
        ("归档并发布", 2),
        ("删除", 2),
    ]
    review_embed = build_analysis_review_embed(draft).to_dict()
    assert review_embed["title"] == "最终分析预览 · AN-D-TEST"
    assert {field["name"] for field in review_embed["fields"]} >= {
        "标的",
        "当前观点",
        "导师",
        "核心逻辑",
    }
    assert retry_ids == {f"axis:analysis:retry:{draft_id.hex}:v3"}
