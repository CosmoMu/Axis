from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import discord
import pytest
from sqlalchemy import func, select

from app.bot.cards import (
    build_complete_review_embed,
    build_public_preview_embed,
    build_review_embed,
)
from app.bot.cogs.card_review import CardReviewCog
from app.bot.views.review_views import (
    ContractEditModal,
    ExpirySelect,
    ReviewDraftView,
    ShortTermEditModal,
    StockStructureEditModal,
    SwingEditMenuView,
    TargetsLogicEditModal,
    TradeValuesEditModal,
)
from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, Mentor, SourceMessage, TradeDraft
from app.db.session import Database
from app.domain.enums import DraftStatus, SourceStatus
from app.market_intelligence.trade_plan import TradePlanArtifact
from app.services.card_review import (
    CardReviewService,
    DraftEdit,
    ReviewChoice,
    ReviewConflictError,
    ReviewValidationError,
    public_preview_payload,
    publication_missing_fields,
)
from app.services.option_contracts import (
    ListedOptionContract,
    OptionContractResolver,
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
            category_suggestion="SWING",
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
            parse_payload={
                "plan_current_stock": 201.0,
                "plan_stock_sl": 190.0,
                "plan_stock_pt1": 210.0,
                "plan_stock_pt2": 220.0,
            },
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
        selected_category="SWING",
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


class ReviewOptionCatalog:
    def __init__(self, contracts: tuple[ListedOptionContract, ...]) -> None:
        self.contracts = contracts

    async def list_option_contracts(
        self,
        *,
        underlying: str,
        start: date,
        end: date,
        strike: Decimal,
        option_side: str,
    ) -> tuple[ListedOptionContract, ...]:
        return tuple(
            item
            for item in self.contracts
            if item.underlying == underlying
            and start <= item.expiry <= end
            and item.strike == strike
            and item.option_side == option_side
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
        assert edited.selected_category == "SWING"

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
        complete = build_complete_review_embed(snapshot, public_preview_payload(snapshot))
        buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]

        assert len(selects) == 3
        assert category_select.custom_id.startswith("axis:review:category:select:")
        assert defaults == ["SWING"]
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
        assert [item.label for item in buttons] == [
            "编辑必填项",
            "重新生成图片",
            "确认发布",
            "LOTTO · NO",
            "删除",
        ]
        assert "会员卡片预览" in (complete.title or "")
        assert "当前股价" in str(complete.to_dict())
        assert "止盈目标" in str(complete.to_dict())
        assert "审核信息" in str(complete.to_dict())

        menu = SwingEditMenuView(SimpleNamespace(), snapshot)
        menu_selects = [item for item in menu.children if isinstance(item, discord.ui.Select)]
        menu_buttons = [item for item in menu.children if isinstance(item, discord.ui.Button)]
        assert len(menu_selects) == 1
        assert [item.label for item in menu_buttons] == [
            "编辑合约",
            "价格 / 仓位",
            "正股结构",
            "目标 / 逻辑",
        ]

        contract_modal = ContractEditModal(SimpleNamespace(), snapshot)
        assert [item.text for item in contract_modal.children] == [
            "Ticker",
            "Expiry",
            "Strike",
            "Call / Put",
        ]
        assert isinstance(contract_modal.children[-1].component, discord.ui.Select)

        values_modal = TradeValuesEditModal(SimpleNamespace(), snapshot)
        assert [item.text for item in values_modal.children] == [
            "入场价",
            "入场价上限",
            "当前平均成本",
            "期权 SL",
            "操作后总持仓",
        ]
        assert isinstance(values_modal.children[-1].component, discord.ui.Select)

        structure_modal = StockStructureEditModal(SimpleNamespace(), snapshot)
        assert [item.text for item in structure_modal.children] == [
            "当前股价",
            "Starter",
            "Add Zone 下限",
            "Add Zone 上限",
            "正股 SL",
        ]

        target_modal = TargetsLogicEditModal(SimpleNamespace(), snapshot)
        assert [item.text for item in target_modal.children] == [
            "正股 PT1",
            "正股 PT2",
            "正股 PT3",
            "Fib 0.618",
            "会员卡片交易逻辑",
        ]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_review_presentation_attaches_complete_card_chart() -> None:
    database, draft, _ = await review_database()
    service = CardReviewService(database)
    try:
        snapshot = await service.get(draft.id)

        class Plan:
            async def prepare(self, card):
                return TradePlanArtifact(card=card, chart_png=b"chart-png", provenance={})

        controller = CardReviewCog.__new__(CardReviewCog)
        controller.service = service
        controller.trade_plan_service = Plan()
        controller._review_artifacts = {}
        embed, view, chart, filename = await controller._review_presentation(snapshot)

        assert chart == b"chart-png"
        assert filename == "axis-d-test-v1-entry-plan.png"
        assert embed.image.url == f"attachment://{filename}"
        assert "会员卡片预览" in (embed.title or "")
        assert view is not None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_entry_plan_edit_persists_targets_and_rejects_wrong_order() -> None:
    database, draft, _ = await review_database()
    service = CardReviewService(database)
    try:
        valid = replace(
            complete_edit(),
            current_stock=Decimal("201"),
            starter=Decimal("201"),
            add_zone_low=Decimal("195"),
            add_zone_high=Decimal("198"),
            stock_sl=Decimal("190"),
            stock_pt1=Decimal("210"),
            stock_pt2=Decimal("220"),
            stock_pt3=Decimal("230"),
            fib_0618=Decimal("196"),
            public_thesis="结构守稳后观察目标推进。",
            replace_plan=True,
        )
        updated = await service.edit(
            draft.id,
            values=valid,
            expected_version=1,
            actor_user_id=501,
            interaction_id=801,
        )
        assert updated.stock_pt1 == Decimal("210.0")
        assert updated.stock_pt2 == Decimal("220.0")
        assert updated.stock_pt3 == Decimal("230.0")
        assert updated.public_thesis == "结构守稳后观察目标推进。"

        invalid = replace(valid, stock_pt2=Decimal("205"))
        with pytest.raises(ReviewValidationError, match="PLAN_TARGET_ORDER_INVALID"):
            await service.edit(
                draft.id,
                values=invalid,
                expected_version=updated.version,
                actor_user_id=501,
                interaction_id=802,
            )
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
async def test_published_review_card_with_cleared_reference_can_be_restored() -> None:
    database, draft, _ = await review_database()
    service = CardReviewService(database)
    try:
        await service.attach_review_message(draft.id, channel_id=700, message_id=800)
        async with database.session() as session:
            stored = await session.get(TradeDraft, draft.id)
            assert stored is not None
            stored.status = DraftStatus.PUBLISHED.value
            stored.review_message_id = None
            await session.commit()

        missing = await service.published_without_review_message(GUILD_ID)
        assert [item.id for item in missing] == [draft.id]
        restored = await service.attach_review_message(draft.id, channel_id=700, message_id=802)
        assert restored.review_message_id == 802
        assert await service.published_without_review_message(GUILD_ID) == []
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


@pytest.mark.asyncio
async def test_short_term_review_is_minimal_and_requires_no_mentor_or_position() -> None:
    database, draft, mentor = await review_database()
    service = CardReviewService(database)
    try:
        short = await service.select_category(
            draft.id,
            category="SHORT_TERM",
            expected_version=1,
            actor_user_id=501,
            interaction_id=700,
        )
        assert publication_missing_fields(short) == ()
        assert short.mentor_id is None
        assert short.position_after_eighths is None

        view = ReviewDraftView(
            SimpleNamespace(),
            short,
            mentor_choices=[ReviewChoice(str(mentor.id), mentor.name)],
            trade_choices=[],
        )
        selects = [item for item in view.children if isinstance(item, discord.ui.Select)]
        buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
        rendered = str(build_review_embed(short).to_dict())

        assert len(selects) == 2
        assert [item.label for item in buttons] == [
            "EDIT",
            "LOTTO · NO",
            "PUBLISH",
            "DELETE",
        ]
        for forbidden in (
            "Mentor",
            "关联订单",
            "仓位",
            "TP1",
            "TP2",
            "SL",
            "confidence",
            "缺失",
        ):
            assert forbidden not in rendered
        assert "待审核 · SHORT-TERM" in rendered
        assert "$1.25" in rendered

        modal = ShortTermEditModal(SimpleNamespace(), short)
        assert [item.label for item in modal.children] == [
            "Ticker",
            "Expiry · 0DTE / MM/DD / YYYY-MM-DD",
            "Strike",
            "Call / Put",
            "Entry Price",
        ]

        approved = await service.approve(
            draft.id,
            expected_version=short.version,
            actor_user_id=501,
            interaction_id=701,
        )
        assert approved.status == DraftStatus.READY.value
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_month_year_expirations_are_selectable_and_survive_service_restart() -> None:
    database, draft, _mentor = await review_database()
    contracts = (
        ListedOptionContract(
            "O:GOOGL260904C00200000", "GOOGL", date(2026, 9, 4), Decimal("200"), "CALL"
        ),
        ListedOptionContract(
            "O:GOOGL260911C00200000", "GOOGL", date(2026, 9, 11), Decimal("200"), "CALL"
        ),
    )
    resolver = OptionContractResolver(
        ReviewOptionCatalog(contracts), today=date(2026, 8, 30)
    )
    async with database.session() as session:
        stored = await session.get(TradeDraft, draft.id)
        assert stored is not None
        stored.selected_category = "SHORT_TERM"
        stored.category_suggestion = "SHORT_TERM"
        stored.mentor_id = None
        stored.expiry = None
        stored.expiry_input = "9/2026"
        stored.expiry_precision = "MONTH_YEAR"
        stored.expiry_resolution_status = "UNRESOLVED"
        stored.contract_validation_status = "UNVALIDATED"
        await session.commit()
    service = CardReviewService(database, resolver)
    try:
        unresolved = await service.ensure_expiry_resolution(draft.id)
        assert unresolved.expiry is None
        assert unresolved.expiry_candidates == (date(2026, 9, 4), date(2026, 9, 11))
        view = ReviewDraftView(
            SimpleNamespace(), unresolved, mentor_choices=[], trade_choices=[]
        )
        expiry_select = next(item for item in view.children if isinstance(item, ExpirySelect))
        assert {option.label for option in expiry_select.options} >= {
            "09/04/2026",
            "09/11/2026",
        }
        leaps_view = ReviewDraftView(
            SimpleNamespace(),
            replace(
                unresolved,
                selected_category="LEAPS",
                category_suggestion="LEAPS",
            ),
            mentor_choices=[],
            trade_choices=[],
        )
        leaps_expiry = next(
            item for item in leaps_view.children if isinstance(item, ExpirySelect)
        )
        assert {option.value for option in leaps_expiry.options} == {
            "DATE:2026-09-04",
            "DATE:2026-09-11",
        }

        selected = await service.select_expiry(
            draft.id,
            selection="DATE:2026-09-11",
            expected_version=unresolved.version,
            actor_user_id=501,
            interaction_id=702,
        )
        assert selected.expiry == date(2026, 9, 11)
        assert selected.expiry_resolution_status == "MANAGER_CONFIRMED"
        assert selected.contract_validation_status == "VALID"

        restarted_service = CardReviewService(database, resolver)
        reloaded = await restarted_service.get(draft.id)
        assert reloaded.expiry == date(2026, 9, 11)
        assert reloaded.option_contract_code == "O:GOOGL260911C00200000"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_invalid_contract_is_visible_in_review_and_cannot_be_approved() -> None:
    database, draft, _mentor = await review_database()
    service = CardReviewService(
        database,
        OptionContractResolver(ReviewOptionCatalog(()), today=date(2026, 8, 30)),
    )
    try:
        short = await service.select_category(
            draft.id,
            category="SHORT_TERM",
            expected_version=1,
            actor_user_id=501,
            interaction_id=703,
        )
        assert short.contract_validation_status == "NOT_FOUND"
        rendered = str(build_review_embed(short).to_dict())
        assert "Contract not found." in rendered
        with pytest.raises(ReviewValidationError) as caught:
            await service.approve(
                draft.id,
                expected_version=short.version,
                actor_user_id=501,
                interaction_id=704,
            )
        assert "contract" in caught.value.missing_fields
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_legacy_impossible_year_is_recovered_from_original_month_day() -> None:
    database, draft, _mentor = await review_database()
    listed = ListedOptionContract(
        "O:SPY260902C00200000",
        "SPY",
        date(2026, 9, 2),
        Decimal("200"),
        "CALL",
    )
    async with database.session() as session:
        stored = await session.get(TradeDraft, draft.id)
        assert stored is not None
        source = await session.get(SourceMessage, stored.source_message_id)
        assert source is not None
        source.raw_text = None
        stored.selected_category = "SHORT_TERM"
        stored.category_suggestion = "SHORT_TERM"
        stored.ticker = "SPY"
        stored.expiry = date(9221, 9, 2)
        stored.expiry_input = "9221-09-02"
        stored.expiry_precision = "EXACT_DATE"
        stored.strike = Decimal("200")
        stored.option_side = "CALL"
        stored.contract_validation_status = "UNVALIDATED"
        await session.commit()
    service = CardReviewService(
        database,
        OptionContractResolver(ReviewOptionCatalog((listed,)), today=date(2026, 8, 30)),
    )
    try:
        repaired = await service.ensure_expiry_resolution(draft.id)
        assert repaired.expiry_input == "9/2"
        assert repaired.expiry_precision == "MONTH_DAY"
        assert repaired.expiry == date(2026, 9, 2)
        assert repaired.contract_validation_status == "VALID"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_lotto_toggle_is_persisted_versioned_and_preserved_across_category_changes() -> None:
    database, draft, _mentor = await review_database()
    service = CardReviewService(database)
    try:
        initial = await service.get(draft.id)
        assert initial.is_lotto is False
        missing_before = publication_missing_fields(initial)
        lotto = await service.toggle_lotto(
            draft.id,
            expected_version=initial.version,
            actor_user_id=501,
            interaction_id=720,
        )
        assert lotto.is_lotto is True
        assert publication_missing_fields(lotto) == missing_before
        swing_view = ReviewDraftView(
            SimpleNamespace(), lotto, mentor_choices=[], trade_choices=[]
        )
        assert "LOTTO · YES" in [
            item.label for item in swing_view.children if isinstance(item, discord.ui.Button)
        ]
        short = await service.select_category(
            draft.id,
            category="SHORT_TERM",
            expected_version=lotto.version,
            actor_user_id=501,
            interaction_id=721,
        )
        assert short.is_lotto is True
        short_view = ReviewDraftView(
            SimpleNamespace(), short, mentor_choices=[], trade_choices=[]
        )
        assert "LOTTO · YES" in [
            item.label for item in short_view.children if isinstance(item, discord.ui.Button)
        ]
        leaps = await service.select_category(
            draft.id,
            category="LEAPS",
            expected_version=short.version,
            actor_user_id=501,
            interaction_id=722,
        )
        edited = await service.edit(
            draft.id,
            values=replace(complete_edit(), selected_category="LEAPS"),
            expected_version=leaps.version,
            actor_user_id=501,
            interaction_id=723,
        )
        assert edited.is_lotto is True
        leaps_view = ReviewDraftView(
            SimpleNamespace(), edited, mentor_choices=[], trade_choices=[]
        )
        assert "LOTTO · YES" in [
            item.label for item in leaps_view.children if isinstance(item, discord.ui.Button)
        ]
        restored = await service.toggle_lotto(
            draft.id,
            expected_version=edited.version,
            actor_user_id=501,
            interaction_id=724,
        )
        assert restored.is_lotto is False
        async with database.session() as session:
            actions = list(
                await session.scalars(
                    select(AuditLog.action_type).where(
                        AuditLog.action_type == "TRADE_DRAFT_LOTTO_TOGGLED"
                    )
                )
            )
        assert actions == ["TRADE_DRAFT_LOTTO_TOGGLED", "TRADE_DRAFT_LOTTO_TOGGLED"]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_category_switch_rebuilds_short_term_and_mentor_review_requirements() -> None:
    database, draft, mentor = await review_database()
    service = CardReviewService(database)
    try:
        short = await service.select_category(
            draft.id,
            category="SHORT_TERM",
            expected_version=1,
            actor_user_id=501,
            interaction_id=710,
        )
        swing = await service.select_category(
            draft.id,
            category="SWING",
            expected_version=short.version,
            actor_user_id=501,
            interaction_id=711,
        )
        assert publication_missing_fields(swing) == ()
        assert swing.swing_mode == "SIMPLE_TRACKED_SWING"
        swing_view = ReviewDraftView(
            SimpleNamespace(),
            swing,
            mentor_choices=[ReviewChoice(str(mentor.id), mentor.name)],
            trade_choices=[],
        )
        assert (
            len([item for item in swing_view.children if isinstance(item, discord.ui.Select)]) == 1
        )

        leaps = await service.select_category(
            draft.id,
            category="LEAPS",
            expected_version=swing.version,
            actor_user_id=501,
            interaction_id=712,
        )
        assert publication_missing_fields(leaps) == ("mentor", "position_after_eighths")
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_operation_select_sets_clear_defaults_and_is_audited() -> None:
    database, draft, _mentor = await review_database()
    service = CardReviewService(database)
    try:
        add = await service.select_operation(
            draft.id,
            intent="UPDATE_TRADE",
            action="ADD",
            action_stage="FIRST",
            expected_version=1,
            actor_user_id=501,
            interaction_id=801,
        )
        assert add.intent == "UPDATE_TRADE"
        assert add.action == "ADD"
        assert add.action_stage == "FIRST"
        assert add.position_after_eighths == 2
        assert publication_missing_fields(add) == (
            "mentor",
            "matched_trade",
            "action_price",
        )

        entry = await service.select_operation(
            draft.id,
            intent="NEW_TRADE",
            action="ENTRY",
            action_stage="NONE",
            expected_version=add.version,
            actor_user_id=501,
            interaction_id=802,
        )
        assert entry.position_delta_eighths == 1
        assert entry.position_after_eighths == 1
        assert publication_missing_fields(entry) == ("mentor", "category")
        async with database.session() as session:
            actions = list(await session.scalars(select(AuditLog.action_type)))
        assert actions == [
            "TRADE_DRAFT_OPERATION_SELECTED",
            "TRADE_DRAFT_OPERATION_SELECTED",
        ]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_incomplete_add_lists_each_required_value_separately() -> None:
    database, draft, mentor = await review_database()
    service = CardReviewService(database)
    try:
        snapshot = await service.get(draft.id)
        incomplete = replace(
            snapshot,
            intent="UPDATE_TRADE",
            action="ADD",
            action_stage=None,
            selected_category="SWING",
            mentor_id=mentor.id,
            mentor_name=mentor.name,
            matched_trade_id=None,
            matched_trade_code=None,
            action_price=None,
            avg_cost=Decimal("1.75"),
            position_delta_eighths=None,
            position_after_eighths=None,
        )
        assert publication_missing_fields(incomplete) == (
            "matched_trade",
            "add_stage",
            "action_price",
            "position_after_eighths",
        )
        rendered = str(build_review_embed(incomplete).to_dict())
        for label in (
            "关联已有订单",
            "第几次加仓",
            "本次操作价格",
            "操作后总持仓",
        ):
            assert label in rendered
    finally:
        await database.dispose()
