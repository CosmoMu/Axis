from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import discord
import pytest
from sqlalchemy import func, select

from app.bot.cards import build_public_preview_embed, build_review_embed
from app.bot.views.review_views import ReviewDraftView
from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, Mentor, SourceMessage, TradeDraft
from app.db.session import Database
from app.domain.enums import DraftStatus, SourceStatus
from app.services.card_review import (
    CardReviewService,
    DraftEdit,
    ReviewChoice,
    ReviewConflictError,
    ReviewValidationError,
    public_preview_payload,
    publication_missing_fields,
)

GUILD_ID = 1543309921066684567


async def review_database() -> tuple[Database, TradeDraft, Mentor]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        mentor = Mentor(guild_id=GUILD_ID, name="Vincent", short_code="VIN")
        session.add(mentor)
        source = SourceMessage(
            guild_id=GUILD_ID,
            discord_message_id=101,
            channel_id=201,
            submitted_by=301,
            raw_text="test signal",
            status=SourceStatus.PARSED.value,
            received_at=datetime.now(UTC),
        )
        session.add(source)
        await session.flush()
        draft = TradeDraft(
            guild_id=GUILD_ID,
            draft_code="D-TEST",
            source_message_id=source.id,
            status=DraftStatus.PENDING_REVIEW.value,
            intent="NEW_TRADE",
            action="ENTRY",
            action_stage="NONE",
            category_suggestion="SHORT_TERM",
            selected_category=None,
            ticker="GOOGL",
            expiry=date(2026, 9, 18),
            strike=Decimal("200"),
            option_side="CALL",
            entry_low=Decimal("1.2"),
            entry_high=Decimal("1.3"),
            position_delta_eighths=1,
            position_after_eighths=1,
            parser_confidence=Decimal("0.93"),
            parse_payload={},
            missing_fields=[],
            warnings=["expiry_year_unspecified"],
            internal_notes="internal-only",
            version=1,
        )
        session.add(draft)
        await session.commit()
    return database, draft, mentor


def complete_edit() -> DraftEdit:
    return DraftEdit(
        intent="NEW_TRADE",
        action="ENTRY",
        action_stage="NONE",
        selected_category="SHORT_TERM",
        ticker="GOOGL",
        expiry=date(2026, 9, 18),
        strike=Decimal("200"),
        option_side="CALL",
        entry_low=Decimal("1.2"),
        entry_high=Decimal("1.3"),
        action_price=None,
        avg_cost=None,
        sl=Decimal("0.8"),
        tp1=Decimal("1.6"),
        tp2=Decimal("2.0"),
        current_pnl_pct=None,
        position_delta_eighths=1,
        position_after_eighths=1,
    )


@pytest.mark.asyncio
async def test_review_edit_mentor_and_approval_are_audited_and_versioned() -> None:
    database, draft, mentor = await review_database()
    service = CardReviewService(database)
    try:
        initial = await service.get(draft.id)
        assert publication_missing_fields(initial) == ("mentor", "category")

        edited = await service.edit(
            draft.id,
            values=complete_edit(),
            expected_version=1,
            actor_user_id=501,
            interaction_id=601,
        )
        assert edited.version == 2
        assert edited.selected_category == "SHORT_TERM"

        with pytest.raises(ReviewConflictError):
            await service.edit(
                draft.id,
                values=complete_edit(),
                expected_version=1,
                actor_user_id=502,
                interaction_id=602,
            )

        mentored = await service.select_mentor(
            draft.id,
            mentor_id=mentor.id,
            expected_version=2,
            actor_user_id=501,
            interaction_id=603,
        )
        assert mentored.version == 3
        assert mentored.mentor_name == "Vincent"
        assert publication_missing_fields(mentored) == ()

        approved = await service.approve(
            draft.id,
            expected_version=3,
            actor_user_id=501,
            interaction_id=604,
        )
        repeated = await service.approve(
            draft.id,
            expected_version=3,
            actor_user_id=501,
            interaction_id=605,
        )
        assert approved.status == DraftStatus.READY.value
        assert repeated.status == DraftStatus.READY.value
        assert repeated.version == approved.version == 4

        async with database.session() as session:
            actions = (
                await session.scalars(
                    select(AuditLog.action_type).order_by(AuditLog.created_at, AuditLog.id)
                )
            ).all()
        assert actions == [
            "TRADE_DRAFT_EDITED",
            "TRADE_DRAFT_MENTOR_SELECTED",
            "TRADE_DRAFT_APPROVED",
        ]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_category_select_changes_only_category_and_is_audited() -> None:
    database, draft, _ = await review_database()
    service = CardReviewService(database)
    try:
        selected = await service.select_category(
            draft.id,
            category="SWING",
            expected_version=1,
            actor_user_id=501,
            interaction_id=606,
        )
        unchanged = await service.select_category(
            draft.id,
            category="SWING",
            expected_version=2,
            actor_user_id=501,
            interaction_id=607,
        )

        assert selected.selected_category == "SWING"
        assert selected.version == unchanged.version == 2
        async with database.session() as session:
            actions = list(await session.scalars(select(AuditLog.action_type)))
        assert actions == ["TRADE_DRAFT_CATEGORY_SELECTED"]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_review_view_starts_with_category_select_and_embed_is_compact() -> None:
    database, draft, mentor = await review_database()
    service = CardReviewService(database)
    try:
        snapshot = await service.get(draft.id)
        view = ReviewDraftView(
            SimpleNamespace(),
            snapshot,
            mentor_choices=[ReviewChoice(str(mentor.id), mentor.name, "Code: VIN")],
            trade_choices=[],
        )
        selects = [item for item in view.children if isinstance(item, discord.ui.Select)]
        category_select, mentor_select, trade_select = selects
        defaults = [option.value for option in category_select.options if option.default]
        embed = build_review_embed(snapshot)

        assert len(selects) == 3
        assert category_select.custom_id.startswith("axis:review:category:select:")
        assert defaults == ["SHORT_TERM"]
        assert category_select.row == 0
        assert mentor_select.custom_id.startswith("axis:review:mentor:select:")
        assert mentor_select.row == 1
        assert mentor_select.disabled is False
        assert trade_select.custom_id.startswith("axis:review:trade:select:")
        assert trade_select.row == 2
        assert trade_select.disabled is True
        assert all(
            getattr(item, "custom_id", "").split(":")[2] not in {"mentor", "trade"}
            for item in view.children
            if isinstance(item, discord.ui.Button)
        )
        assert len(embed.fields) <= 4
        assert "GOOGL" in (embed.description or "")
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_incomplete_draft_cannot_be_approved() -> None:
    database, draft, _ = await review_database()
    service = CardReviewService(database)
    try:
        with pytest.raises(ReviewValidationError) as caught:
            await service.approve(
                draft.id,
                expected_version=1,
                actor_user_id=501,
                interaction_id=601,
            )
        assert caught.value.code == "DRAFT_INCOMPLETE"
        assert caught.value.missing_fields == ("mentor", "category")
        async with database.session() as session:
            audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
        assert audit_count == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_review_message_attachment_is_idempotent() -> None:
    database, draft, _ = await review_database()
    service = CardReviewService(database)
    try:
        first = await service.attach_review_message(draft.id, channel_id=700, message_id=800)
        second = await service.attach_review_message(draft.id, channel_id=701, message_id=801)
        assert first.review_channel_id == second.review_channel_id == 700
        assert first.review_message_id == second.review_message_id == 800
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_public_preview_uses_whitelist_and_internal_review_keeps_context() -> None:
    database, draft, mentor = await review_database()
    service = CardReviewService(database)
    try:
        edited = await service.edit(
            draft.id,
            values=complete_edit(),
            expected_version=1,
            actor_user_id=501,
            interaction_id=600,
        )
        selected = await service.select_mentor(
            draft.id,
            mentor_id=mentor.id,
            expected_version=edited.version,
            actor_user_id=501,
            interaction_id=601,
        )
        public_text = str(build_public_preview_embed(public_preview_payload(selected)).to_dict())
        internal_text = str(build_review_embed(selected).to_dict())

        for forbidden in (
            "Vincent",
            "Mentor",
            "confidence",
            "internal-only",
            "source",
            "submitted_by",
            "Market",
            "Bid",
            "Ask",
            "Stop",
        ):
            assert forbidden not in public_text
        assert "SL" in public_text
        assert "Vincent" in internal_text
        assert "confidence" in internal_text
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_delete_is_soft_idempotent_and_audited_once() -> None:
    database, draft, _ = await review_database()
    service = CardReviewService(database)
    try:
        deleted = await service.delete(
            draft.id,
            expected_version=1,
            actor_user_id=501,
            interaction_id=601,
        )
        repeated = await service.delete(
            draft.id,
            expected_version=1,
            actor_user_id=501,
            interaction_id=602,
        )
        assert deleted.status == repeated.status == DraftStatus.DELETED.value
        assert deleted.version == repeated.version == 2
        async with database.session() as session:
            audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
        assert audit_count == 1
    finally:
        await database.dispose()
