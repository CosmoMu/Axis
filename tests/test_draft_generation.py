from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import (
    AuditLog,
    GuildConfig,
    LlmInvocation,
    SourceAttachment,
    SourceMessage,
    TradeDraft,
)
from app.db.session import Database
from app.domain.enums import DraftStatus, LlmWorkload, SourceStatus
from app.integrations.openai_trade_parser import (
    LlmInvocationTrace,
    TradeParseError,
    TradeParseResult,
)
from app.services.attachment_storage import LocalAttachmentStore
from app.services.draft_generation import (
    DraftGenerationDisposition,
    DraftGenerationService,
)
from app.services.option_contracts import ListedOptionContract, OptionContractResolver
from tests.test_openai_trade_parser import valid_payload

GUILD_ID = 1543309921066684567


class FakeParser:
    def __init__(
        self,
        *,
        fail: bool = False,
        payload: dict[str, object] | None = None,
        expected_attachment_count: int = 1,
        expected_raw_text: str = "SPY 700C entry",
    ) -> None:
        self.fail = fail
        self.payload = payload or valid_payload()
        self.expected_attachment_count = expected_attachment_count
        self.expected_raw_text = expected_raw_text
        self.calls = 0

    async def parse(self, *, raw_text: str | None, attachments: list[object]) -> TradeParseResult:
        self.calls += 1
        trace = LlmInvocationTrace(
            provider="openai",
            model="gpt-5.6-terra",
            workload=LlmWorkload.SIGNAL_PARSE,
            prompt_version="axis-trade-parse-v1",
            schema_version="axis-trade-v1",
            latency_ms=12,
            success=not self.fail,
            error_type="LLM_REQUEST_FAILED" if self.fail else None,
            response_id=None if self.fail else "resp_test",
        )
        if self.fail:
            raise TradeParseError("LLM_REQUEST_FAILED", trace=trace)
        assert raw_text == self.expected_raw_text
        assert len(attachments) == self.expected_attachment_count
        return TradeParseResult(self.payload, trace)


async def database_with_source(
    tmp_path: Path,
    *,
    message_id: int,
    with_attachment: bool,
    raw_text: str = "SPY 700C entry",
) -> tuple[Database, LocalAttachmentStore, SourceMessage]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        source = SourceMessage(
            guild_id=GUILD_ID,
            discord_message_id=message_id,
            channel_id=200,
            submitted_by=300,
            raw_text=raw_text,
            status=SourceStatus.RECEIVED.value,
            received_at=datetime.now(UTC),
        )
        session.add(source)
        await session.flush()
        if with_attachment:
            data = b"\x89PNG\r\n\x1a\naxis-image"
            prepared = store.prepare(
                discord_attachment_id=400,
                filename="chart.png",
                declared_content_type="image/png",
                declared_size=len(data),
                data=data,
            )
            stored = await store.write(
                guild_id=GUILD_ID,
                message_id=message_id,
                attachment=prepared,
            )
            session.add(
                SourceAttachment(
                    source_message_id=source.id,
                    discord_attachment_id=stored.discord_attachment_id,
                    filename=stored.display_filename,
                    content_type=stored.content_type,
                    size_bytes=stored.size_bytes,
                    source_url=None,
                    storage_key=stored.storage_key,
                    checksum_sha256=stored.checksum_sha256,
                )
            )
        await session.commit()
    return database, store, source


@pytest.mark.asyncio
async def test_generation_is_idempotent_and_short_term_has_no_position(tmp_path: Path) -> None:
    database, store, source = await database_with_source(
        tmp_path,
        message_id=1001,
        with_attachment=True,
    )
    fake_parser = FakeParser()
    service = DraftGenerationService(database, store, fake_parser)
    try:
        first = await service.generate(source.id)
        second = await service.generate(source.id)

        assert first.disposition is DraftGenerationDisposition.CREATED
        assert second.disposition is DraftGenerationDisposition.EXISTING
        assert first.draft_code == second.draft_code
        assert first.draft_code == "S-00001"
        assert fake_parser.calls == 1
        async with database.session() as session:
            draft = await session.scalar(select(TradeDraft))
            saved_source = await session.get(SourceMessage, source.id)
            draft_count = await session.scalar(select(func.count()).select_from(TradeDraft))
            invocation = await session.scalar(select(LlmInvocation))
            audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
        assert draft is not None
        assert draft.status == DraftStatus.PENDING_REVIEW.value
        assert draft.position_delta_eighths is None
        assert draft.position_after_eighths is None
        assert draft.category_suggestion == "SHORT_TERM"
        assert draft.selected_category == "SHORT_TERM"
        assert "DEFAULT_POSITION_APPLIED" not in draft.warnings
        assert draft.mentor_id is None
        assert invocation is not None
        assert invocation.workload == LlmWorkload.SIGNAL_PARSE.value
        assert invocation.success is True
        assert draft.llm_invocation_id == invocation.id
        assert saved_source is not None and saved_source.status == SourceStatus.PARSED.value
        assert draft_count == 1
        assert audit_count == 1
    finally:
        await database.dispose()


class FastSignalCatalog:
    async def list_option_contracts(
        self,
        *,
        underlying: str,
        start: date,
        end: date,
        strike: Decimal,
        option_side: str,
    ) -> tuple[ListedOptionContract, ...]:
        expiry = date.today()
        if (
            underlying == "SPY"
            and strike == Decimal("775")
            and option_side == "CALL"
            and start <= expiry <= end
        ):
            return (
                ListedOptionContract(
                    "O:SPY", "SPY", expiry, Decimal("775"), "CALL"
                ),
            )
        return ()


@pytest.mark.asyncio
async def test_short_term_fast_input_resolves_and_persists_zero_dte(tmp_path: Path) -> None:
    raw = "SPY 775C .48"
    database, store, source = await database_with_source(
        tmp_path,
        message_id=1005,
        with_attachment=False,
        raw_text=raw,
    )
    payload = valid_payload()
    payload.update(
        {
            "expiry_input": None,
            "expiry_precision": None,
            "resolved_expiry": None,
            "expiry_resolution_status": "UNRESOLVED",
        }
    )
    service = DraftGenerationService(
        database,
        store,
        FakeParser(
            payload=payload,
            expected_attachment_count=0,
            expected_raw_text=raw,
        ),
        OptionContractResolver(FastSignalCatalog()),
    )
    try:
        result = await service.generate(source.id)
        assert result.disposition is DraftGenerationDisposition.CREATED
        async with database.session() as session:
            draft = await session.scalar(select(TradeDraft))
        assert draft is not None
        assert draft.selected_category == "SHORT_TERM"
        assert draft.expiry == date.today()
        assert draft.expiry_precision == "AUTO_NEAREST"
        assert draft.expiry_resolution_status == "AUTO_RESOLVED"
        assert draft.contract_validation_status == "VALID"
        assert draft.option_contract_code == "O:SPY"
        assert draft.entry_low == Decimal("0.4800")
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_swing_without_expiry_does_not_use_auto_nearest(tmp_path: Path) -> None:
    raw = "RIVN 18C .90 SWING"
    database, store, source = await database_with_source(
        tmp_path,
        message_id=1006,
        with_attachment=False,
        raw_text=raw,
    )
    payload = valid_payload()
    payload.update(
        {
            "ticker": "RIVN",
            "strike": 18,
            "category_suggestion": "SWING",
            "expiry_input": None,
            "expiry_precision": None,
            "resolved_expiry": None,
            "expiry_resolution_status": "UNRESOLVED",
        }
    )
    service = DraftGenerationService(
        database,
        store,
        FakeParser(
            payload=payload,
            expected_attachment_count=0,
            expected_raw_text=raw,
        ),
        OptionContractResolver(FastSignalCatalog()),
    )
    try:
        await service.generate(source.id)
        async with database.session() as session:
            draft = await session.scalar(select(TradeDraft))
        assert draft is not None
        assert draft.selected_category == "SWING"
        assert draft.expiry is None
        assert draft.expiry_precision is None
        assert "expiry" in draft.missing_fields
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_parse_failure_creates_one_safe_failed_draft(tmp_path: Path) -> None:
    database, store, source = await database_with_source(
        tmp_path,
        message_id=1002,
        with_attachment=False,
    )
    fake_parser = FakeParser(fail=True)
    service = DraftGenerationService(database, store, fake_parser)
    try:
        result = await service.generate(source.id)
        duplicate = await service.generate(source.id)
        assert result.disposition is DraftGenerationDisposition.FAILED
        assert duplicate.disposition is DraftGenerationDisposition.EXISTING
        assert fake_parser.calls == 1
        async with database.session() as session:
            draft = await session.scalar(select(TradeDraft))
            saved_source = await session.get(SourceMessage, source.id)
            audit = await session.scalar(select(AuditLog))
            invocation = await session.scalar(select(LlmInvocation))
        assert draft is not None and draft.status == DraftStatus.PARSE_FAILED.value
        assert draft.selected_category == "SWING"
        assert draft.warnings == ["LLM_REQUEST_FAILED"]
        assert saved_source is not None and saved_source.status == SourceStatus.FAILED.value
        assert audit is not None and audit.after_json["reason_code"] == "LLM_REQUEST_FAILED"
        assert invocation is not None
        assert invocation.success is False
        assert invocation.error_type == "LLM_REQUEST_FAILED"
        assert draft.llm_invocation_id == invocation.id
        assert "SPY" not in str(audit.after_json)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_fourth_add_position_is_never_defaulted(tmp_path: Path) -> None:
    database, store, source = await database_with_source(
        tmp_path,
        message_id=1003,
        with_attachment=False,
    )
    payload = valid_payload()
    payload.update(
        {
            "intent": "UPDATE_TRADE",
            "action": "ADD",
            "add_stage": "FOURTH",
            "position_delta_eighths": None,
            "position_after_eighths": None,
            "category_suggestion": "SWING",
        }
    )
    service = DraftGenerationService(
        database,
        store,
        FakeParser(payload=payload, expected_attachment_count=0),
    )
    try:
        result = await service.generate(source.id)
        assert result.disposition is DraftGenerationDisposition.CREATED
        async with database.session() as session:
            draft = await session.scalar(select(TradeDraft))
        assert draft is not None
        assert draft.position_delta_eighths is None
        assert draft.position_after_eighths is None
        assert "position" in draft.missing_fields
        assert "DEFAULT_POSITION_APPLIED" not in draft.warnings
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_impossible_past_expiry_is_removed_before_review(tmp_path: Path) -> None:
    database, store, source = await database_with_source(
        tmp_path,
        message_id=1004,
        with_attachment=False,
    )
    payload = valid_payload()
    payload.update(
        {
            "expiry_input": "1202-01-31",
            "expiry_precision": "EXACT_DATE",
            "resolved_expiry": "1202-01-31",
            "category_suggestion": "LEAPS",
        }
    )
    service = DraftGenerationService(
        database,
        store,
        FakeParser(payload=payload, expected_attachment_count=0),
    )
    try:
        result = await service.generate(source.id)
        assert result.disposition is DraftGenerationDisposition.CREATED
        async with database.session() as session:
            draft = await session.scalar(select(TradeDraft))
        assert draft is not None
        assert draft.expiry is None
        assert "expiry" in draft.missing_fields
        assert "EXPIRY_IN_PAST_REQUIRES_REVIEW" in draft.warnings
    finally:
        await database.dispose()
