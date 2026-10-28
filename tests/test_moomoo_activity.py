from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.bot.cogs.moomoo_activity import MoomooActivityCog
from app.bot.moomoo_activity_cards import (
    activity_event_embed,
    activity_event_text,
    daily_summary_embeds,
    daily_summary_messages,
)
from app.db.base import Base
from app.db.models import GuildConfig, MoomooActivityDailySummary
from app.db.session import Database
from app.domain.personal_execution import PersonalBrokerEnvironment
from app.integrations.moomoo_activity import (
    ActivityAccount,
    ActivityFill,
    ActivityOrder,
    ActivityPosition,
    ActivitySnapshot,
    MoomooActivityReader,
)
from app.services.moomoo_activity import MoomooActivityEvent, MoomooActivityService

GUILD_ID = 1543309921066684567
ACCOUNT_REF = "acct_1234567890abcdef"


class FakeActivityReader:
    def __init__(self, snapshot: ActivitySnapshot) -> None:
        self.snapshot = snapshot

    async def read_snapshot(self) -> ActivitySnapshot:
        return self.snapshot


@pytest.mark.asyncio
async def test_activity_reader_reuses_blocking_sdk_read_after_timeout() -> None:
    reader = MoomooActivityReader(
        host="127.0.0.1",
        port=11111,
        environment=PersonalBrokerEnvironment.REAL,
        security_firm="FUTUCA",
    )
    started = threading.Event()
    release = threading.Event()
    calls = 0
    expected = make_snapshot()

    def blocking_read() -> ActivitySnapshot:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return expected

    reader._read_snapshot_sync = blocking_read  # type: ignore[method-assign]
    first = asyncio.create_task(reader.read_snapshot())
    assert await asyncio.to_thread(started.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(reader.read_snapshot())
    await asyncio.sleep(0.05)
    assert calls == 1
    release.set()
    assert await second == expected
    assert calls == 1


def make_snapshot(
    *,
    orders: tuple[ActivityOrder, ...] = (),
    fills: tuple[ActivityFill, ...] = (),
    observed_at: datetime | None = None,
) -> ActivitySnapshot:
    now = observed_at or datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
    return ActivitySnapshot(
        accounts=(
            ActivityAccount(
                account_ref=ACCOUNT_REF,
                equity=Decimal("1000"),
                buying_power=Decimal("500"),
                cash=Decimal("300"),
            ),
        ),
        positions=(
            ActivityPosition(
                account_ref=ACCOUNT_REF,
                instrument_code="US.SPY",
                quantity=Decimal("1"),
                average_cost=Decimal("700"),
                current_price=Decimal("705"),
                unrealized_pnl=Decimal("5"),
            ),
        ),
        orders=orders,
        fills=fills,
        observed_at=now,
    )


async def make_database() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        await session.commit()
    return database


@pytest.mark.asyncio
async def test_first_reconcile_is_quiet_then_new_fill_is_notified_once() -> None:
    database = await make_database()
    old_fill = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="old",
        broker_order_id="order-old",
        instrument_code="US.SPY",
        side="BUY",
        quantity=Decimal("1"),
        fill_price=Decimal("700"),
        executed_at=datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
    )
    reader = FakeActivityReader(make_snapshot(fills=(old_fill,)))
    service = MoomooActivityService(database, reader, guild_id=GUILD_ID)  # type: ignore[arg-type]
    await service.reconcile()
    assert await service.pending_events() == ()

    new_fill = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="new",
        broker_order_id="order-new",
        instrument_code="US.AAPL",
        side="SELL",
        quantity=Decimal("2"),
        fill_price=Decimal("250.5"),
        executed_at=datetime(2026, 10, 7, 15, 1, tzinfo=UTC),
    )
    reader.snapshot = make_snapshot(fills=(old_fill, new_fill))
    await service.reconcile()
    events = await service.pending_events()
    assert len(events) == 1
    assert events[0].kind == "FILL"
    assert events[0].instrument_code == "US.AAPL"
    await service.mark_notified(events[0])
    assert await service.pending_events() == ()
    await database.dispose()


@pytest.mark.asyncio
async def test_split_fills_for_one_order_are_published_as_one_aggregated_event() -> None:
    database = await make_database()
    reader = FakeActivityReader(make_snapshot())
    service = MoomooActivityService(database, reader, guild_id=GUILD_ID)  # type: ignore[arg-type]
    await service.reconcile()
    fills = (
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="split-1",
            broker_order_id="order-split",
            instrument_code="US.GOOGL261009C355000",
            side="BUY",
            quantity=Decimal("1"),
            fill_price=Decimal("0.80"),
            executed_at=datetime(2026, 10, 9, 13, 33, 42, 619000, tzinfo=UTC),
        ),
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="split-2",
            broker_order_id="order-split",
            instrument_code="US.GOOGL261009C355000",
            side="BUY",
            quantity=Decimal("1"),
            fill_price=Decimal("0.82"),
            executed_at=datetime(2026, 10, 9, 13, 33, 42, 662000, tzinfo=UTC),
        ),
    )
    reader.snapshot = make_snapshot(fills=fills)
    await service.reconcile()

    events = await service.pending_events()
    assert len(events) == 1
    assert events[0].quantity == Decimal("2")
    assert events[0].price == Decimal("0.81")
    assert len(events[0].record_ids) == 2

    await service.mark_notified(events[0])
    assert await service.pending_events() == ()
    await database.dispose()


@pytest.mark.asyncio
async def test_butterfly_order_is_published_as_one_strategy_event() -> None:
    database = await make_database()
    reader = FakeActivityReader(make_snapshot())
    service = MoomooActivityService(database, reader, guild_id=GUILD_ID)  # type: ignore[arg-type]
    await service.reconcile()
    executed_at = datetime(2026, 10, 27, 18, 12, 5, 867000, tzinfo=UTC)
    order_id = "butterfly-order"
    fills = (
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="butterfly-high",
            broker_order_id=order_id,
            instrument_code="US.SPXW261027C7745000",
            side="BUY",
            quantity=Decimal("1"),
            fill_price=Decimal("0.17"),
            executed_at=executed_at,
        ),
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="butterfly-middle",
            broker_order_id=order_id,
            instrument_code="US.SPXW261027C7730000",
            side="SELL_SHORT",
            quantity=Decimal("2"),
            fill_price=Decimal("0.72"),
            executed_at=executed_at,
        ),
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="butterfly-low",
            broker_order_id=order_id,
            instrument_code="US.SPXW261027C7715000",
            side="BUY",
            quantity=Decimal("1"),
            fill_price=Decimal("6.27"),
            executed_at=executed_at,
        ),
    )
    reader.snapshot = make_snapshot(fills=fills)
    await service.reconcile()

    events = await service.pending_events()
    assert len(events) == 1
    event = events[0]
    assert event.strategy_type == "BUTTERFLY"
    assert event.strategy_display == "SPXW 10/27 7715/7730/7745C"
    assert event.strategy_price_kind == "DEBIT"
    assert event.action == "BUY"
    assert event.quantity == Decimal("1")
    assert event.price == Decimal("5.00")
    assert len(event.record_ids) == 3

    embed = activity_event_embed(event)
    assert embed.title == "买入 · SPXW 10/27 蝶式策略"
    assert "7715/7730/7745C" in (embed.description or "")
    assert "净成本 $5 / 组" in (embed.description or "")
    assert [field.name for field in embed.fields] == ["策略数量", "总投入", "组合结构"]
    assert embed.fields[0].value == "**1 组**"
    assert embed.fields[1].value == "**$500**"
    assert "买 1×7715C" in embed.fields[2].value
    assert "卖 2×7730C" in embed.fields[2].value
    assert "买 1×7745C" in embed.fields[2].value

    await service.mark_notified(event)
    assert await service.pending_events() == ()

    closed_at = datetime(2026, 10, 27, 18, 16, 53, 415000, tzinfo=UTC)
    close_order_id = "butterfly-close-order"
    closing_fills = (
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="butterfly-close-high",
            broker_order_id=close_order_id,
            instrument_code="US.SPXW261027C7745000",
            side="SELL",
            quantity=Decimal("1"),
            fill_price=Decimal("0.22"),
            executed_at=closed_at,
        ),
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="butterfly-close-middle",
            broker_order_id=close_order_id,
            instrument_code="US.SPXW261027C7730000",
            side="BUY_BACK",
            quantity=Decimal("2"),
            fill_price=Decimal("0.92"),
            executed_at=closed_at,
        ),
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="butterfly-close-low",
            broker_order_id=close_order_id,
            instrument_code="US.SPXW261027C7715000",
            side="SELL",
            quantity=Decimal("1"),
            fill_price=Decimal("7.42"),
            executed_at=closed_at,
        ),
    )
    reader.snapshot = make_snapshot(fills=fills + closing_fills)
    await service.reconcile()

    close_event = (await service.pending_events())[0]
    assert close_event.action == "CLOSE"
    assert close_event.price == Decimal("5.80")
    assert close_event.total_profit_amount == Decimal("80.00")
    assert close_event.total_return_percent == Decimal("16.00")
    close_embed = activity_event_embed(close_event)
    assert close_embed.title == "清仓 · SPXW 10/27 蝶式策略"
    assert "+16%" in (close_embed.description or "")
    assert "+$80" in (close_embed.description or "")
    await database.dispose()


@pytest.mark.asyncio
async def test_vertical_order_is_published_as_one_strategy_event() -> None:
    database = await make_database()
    reader = FakeActivityReader(make_snapshot())
    service = MoomooActivityService(database, reader, guild_id=GUILD_ID)  # type: ignore[arg-type]
    await service.reconcile()
    executed_at = datetime(2026, 10, 28, 17, 26, 52, 437000, tzinfo=UTC)
    fills = (
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="vertical-long",
            broker_order_id="vertical-order",
            instrument_code="US.SPY261028P770000",
            side="BUY",
            quantity=Decimal("1"),
            fill_price=Decimal("1.63"),
            executed_at=executed_at,
        ),
        ActivityFill(
            account_ref=ACCOUNT_REF,
            broker_fill_id="vertical-short",
            broker_order_id="vertical-order",
            instrument_code="US.SPY261028P768000",
            side="SELL_SHORT",
            quantity=Decimal("1"),
            fill_price=Decimal("0.96"),
            executed_at=executed_at,
        ),
    )
    reader.snapshot = make_snapshot(fills=fills)
    await service.reconcile()

    events = await service.pending_events()
    assert len(events) == 1
    event = events[0]
    assert event.strategy_type == "VERTICAL_SPREAD"
    assert event.strategy_display == "SPY 10/28 770/768P"
    assert event.strategy_price_kind == "DEBIT"
    assert event.action == "BUY"
    assert event.quantity == Decimal("1")
    assert event.price == Decimal("0.67")
    assert len(event.record_ids) == 2

    embed = activity_event_embed(event)
    assert embed.title == "买入 · SPY 10/28 垂直价差"
    assert "770/768P" in (embed.description or "")
    assert "净成本 $0.67 / 组" in (embed.description or "")
    assert embed.fields[0].value == "**1 组**"
    assert embed.fields[1].value == "**$67**"
    assert "买 1×770P" in embed.fields[2].value
    assert "卖 1×768P" in embed.fields[2].value
    await database.dispose()


@pytest.mark.asyncio
async def test_second_buy_is_add_with_total_position_and_weighted_average() -> None:
    database = await make_database()
    reader = FakeActivityReader(make_snapshot())
    service = MoomooActivityService(database, reader, guild_id=GUILD_ID)  # type: ignore[arg-type]
    await service.reconcile()
    opening = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="opening-buy",
        broker_order_id="opening-order",
        instrument_code="US.MSTR261016C400000",
        side="BUY",
        quantity=Decimal("2"),
        fill_price=Decimal("2.00"),
        executed_at=datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
    )
    reader.snapshot = make_snapshot(fills=(opening,))
    await service.reconcile()
    opening_event = (await service.pending_events())[0]
    assert opening_event.action == "BUY"
    await service.mark_notified(opening_event)

    add = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="add-buy",
        broker_order_id="add-order",
        instrument_code=opening.instrument_code,
        side="BUY",
        quantity=Decimal("3"),
        fill_price=Decimal("3.00"),
        executed_at=datetime(2026, 10, 7, 15, 0, tzinfo=UTC),
    )
    reader.snapshot = make_snapshot(fills=(opening, add))
    await service.reconcile()
    event = (await service.pending_events())[0]
    assert event.action == "ADD"
    assert event.quantity == Decimal("3")
    assert event.position_quantity == Decimal("5")
    assert event.position_average_cost == Decimal("2.60")
    embed = activity_event_embed(event)
    assert embed.title == "加仓 · MSTR 10/16 400C"
    assert [field.name for field in embed.fields] == ["本次加仓", "当前持仓", "最新均价"]
    assert embed.fields[1].value == "**5 张**"
    assert embed.fields[2].value == "**$2.6**"
    assert "当前 5张" in activity_event_text(event)
    assert "最新均价 **$2.6**" in activity_event_text(event)
    await database.dispose()


@pytest.mark.asyncio
async def test_orders_are_not_notified_and_daily_summary_is_idempotent() -> None:
    database = await make_database()
    reader = FakeActivityReader(make_snapshot())
    service = MoomooActivityService(database, reader, guild_id=GUILD_ID)  # type: ignore[arg-type]
    await service.reconcile()
    order = ActivityOrder(
        account_ref=ACCOUNT_REF,
        broker_order_id="order-1",
        instrument_code="US.TSLA",
        side="BUY",
        quantity=Decimal("3"),
        filled_quantity=Decimal("0"),
        limit_price=Decimal("400"),
        average_fill_price=None,
        status="SUBMITTED",
        updated_at=datetime(2026, 10, 7, 15, 5, tzinfo=UTC),
    )
    reader.snapshot = make_snapshot(orders=(order,))
    await service.reconcile()
    assert await service.pending_events() == ()

    first = await service.prepare_daily_summary(date(2026, 10, 7))
    assert first is not None
    assert first.snapshot["positions"][0]["code"] == "US.SPY"
    await service.mark_summary_published(first.id, [123])
    assert await service.prepare_daily_summary(date(2026, 10, 7)) is None
    await database.dispose()


@pytest.mark.asyncio
async def test_daily_summary_deducts_public_fees_and_rolls_net_equity_forward() -> None:
    database = await make_database()
    previous_fill = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="previous-buy-two",
        broker_order_id="previous-order-buy-two",
        instrument_code="US.SPY261009C700000",
        side="BUY",
        quantity=Decimal("2"),
        fill_price=Decimal("2.00"),
        executed_at=datetime(2026, 10, 6, 15, 1, tzinfo=UTC),
    )
    fill = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="buy-two",
        broker_order_id="order-buy-two",
        instrument_code="US.SPY261009C700000",
        side="BUY",
        quantity=Decimal("2"),
        fill_price=Decimal("2.50"),
        executed_at=datetime(2026, 10, 7, 15, 1, tzinfo=UTC),
    )
    sell = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="sell-one",
        broker_order_id="order-sell-one",
        instrument_code="US.SPY261009C700000",
        side="SELL",
        quantity=Decimal("1"),
        fill_price=Decimal("3.00"),
        executed_at=datetime(2026, 10, 7, 15, 2, tzinfo=UTC),
    )
    reader = FakeActivityReader(
        make_snapshot(
            fills=(previous_fill, fill, sell),
            observed_at=datetime(2026, 10, 7, 13, 0, tzinfo=UTC),
        )
    )
    service = MoomooActivityService(database, reader, guild_id=GUILD_ID)  # type: ignore[arg-type]
    await service.reconcile()
    async with database.session() as session:
        session.add(
            MoomooActivityDailySummary(
                guild_id=GUILD_ID,
                session_date=date(2026, 10, 6),
                snapshot_json={
                    "accounts": [
                        {
                            "account": "账户 …cdef",
                            "equity": "900.00",
                        }
                    ]
                },
                discord_message_ids=[1],
                published_at=datetime(2026, 10, 6, 20, 15, tzinfo=UTC),
            )
        )
        await session.commit()

    claim = await service.prepare_daily_summary(date(2026, 10, 7))
    assert claim is not None
    account = claim.snapshot["accounts"][0]
    assert account["opening_equity"] == "898.70"
    assert account["commission"] == "2.31"
    assert account["pre_fee_equity"] == "1000.00"
    assert account["post_fee_equity"] == "997.69"
    assert account["pre_fee_profit"] == "101.30"
    assert account["post_fee_profit"] == "98.99"
    await database.dispose()


@pytest.mark.asyncio
async def test_fill_events_classify_buy_partial_sell_and_close() -> None:
    database = await make_database()
    reader = FakeActivityReader(make_snapshot())
    service = MoomooActivityService(database, reader, guild_id=GUILD_ID)  # type: ignore[arg-type]
    await service.reconcile()
    buy = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="buy",
        broker_order_id="order-buy",
        instrument_code="US.MSTR261009P155000",
        side="BUY",
        quantity=Decimal("8"),
        fill_price=Decimal("2.44"),
        executed_at=datetime(2026, 10, 7, 14, 1, tzinfo=UTC),
    )
    reader.snapshot = make_snapshot(fills=(buy,))
    await service.reconcile()
    event = (await service.pending_events())[0]
    assert event.action == "BUY"
    await service.mark_notified(event)

    partial = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="partial",
        broker_order_id="order-sell-1",
        instrument_code=buy.instrument_code,
        side="SELL",
        quantity=Decimal("2"),
        fill_price=Decimal("3.40"),
        executed_at=datetime(2026, 10, 7, 14, 2, tzinfo=UTC),
    )
    reader.snapshot = make_snapshot(fills=(buy, partial))
    await service.reconcile()
    event = (await service.pending_events())[0]
    assert event.action == "SELL"
    assert event.entry_price == Decimal("2.44")
    assert event.position_fraction == Decimal("0.25")
    await service.mark_notified(event)

    close = ActivityFill(
        account_ref=ACCOUNT_REF,
        broker_fill_id="close",
        broker_order_id="order-sell-2",
        instrument_code=buy.instrument_code,
        side="SELL",
        quantity=Decimal("6"),
        fill_price=Decimal("3.20"),
        executed_at=datetime(2026, 10, 7, 14, 3, tzinfo=UTC),
    )
    reader.snapshot = make_snapshot(fills=(buy, partial, close))
    await service.reconcile()
    event = (await service.pending_events())[0]
    assert event.action == "CLOSE"
    assert event.total_profit_amount == Decimal("648.00")
    assert event.total_return_percent is not None
    assert event.total_return_percent.quantize(Decimal("0.01")) == Decimal("33.20")
    summary = await service.prepare_daily_summary(date(2026, 10, 7))
    assert summary is not None
    assert summary.snapshot["performance"]["closed_count"] == 1
    assert summary.snapshot["performance"]["win_rate"] == "100"
    assert Decimal(summary.snapshot["performance"]["average_win"]).quantize(
        Decimal("0.01")
    ) == Decimal("33.20")
    assert summary.snapshot["performance"]["average_loss"] is None
    await database.dispose()


def test_plain_text_outputs_fit_discord_without_embed_permission() -> None:
    event = MoomooActivityEvent(
        kind="FILL",
        record_id=uuid.uuid4(),
        account_label="账户 …cdef",
        instrument_code="US.SPY",
        side="BUY",
        quantity=Decimal("2"),
        price=Decimal("700.5"),
        status=None,
        occurred_at=datetime(2026, 10, 7, 15, 1, tzinfo=UTC),
    )
    assert activity_event_text(event) == "**买入** · SPY @ $700.5\n2股"
    pages = daily_summary_messages(
        {
            "session_date": "2026-10-07",
            "fills": [
                {
                    "account": "账户 …cdef",
                    "code": "US.SPY",
                    "side": "BUY",
                    "quantity": "2",
                    "price": "700.5",
                    "time": "11:01 ET",
                }
            ],
            "accounts": [
                {
                    "account": "账户 …cdef",
                    "equity": "1000.00",
                    "cash": "300.00",
                    "buying_power": "500.00",
                }
            ],
            "positions": [],
        }
    )
    assert pages and all(len(page) <= 2000 for page in pages)
    assert "账户状态" in pages[0]
    assert "今日成交" not in pages[0]


def test_activity_text_matches_compact_option_examples() -> None:
    sell = MoomooActivityEvent(
        kind="FILL",
        record_id=uuid.uuid4(),
        account_label="账户 TEST-8070",
        instrument_code="US.MSTR261009P155000",
        side="SELL",
        quantity=Decimal("2"),
        price=Decimal("3.4"),
        status=None,
        occurred_at=None,
        action="SELL",
        entry_price=Decimal("2.44"),
        return_percent=Decimal("39.344"),
        position_fraction=Decimal("0.25"),
    )
    rendered = activity_event_text(sell)
    assert "**卖出** · MSTR 10/09 155P @ $3.4" in rendered
    assert "**+39.34%** · $2.44 → $3.4" in rendered
    assert "2张 · 1/4 仓位" in rendered
    assert "NVDA 10/16 200C" in activity_event_text(
        MoomooActivityEvent(
            kind="FILL",
            record_id=uuid.uuid4(),
            account_label="账户 TEST-8070",
            instrument_code="US.NVDA261016C200000",
            side="BUY",
            quantity=Decimal("2"),
            price=Decimal("3.175"),
            status=None,
            occurred_at=None,
            action="BUY",
        )
    )


def test_activity_embeds_use_axis_visual_hierarchy() -> None:
    sell = MoomooActivityEvent(
        kind="FILL",
        record_id=uuid.uuid4(),
        account_label="账户 TEST-8070",
        instrument_code="US.MSTR261009P155000",
        side="SELL",
        quantity=Decimal("2"),
        price=Decimal("3.4"),
        status=None,
        occurred_at=datetime(2026, 10, 7, 15, 1, tzinfo=UTC),
        action="SELL",
        entry_price=Decimal("2.44"),
        return_percent=Decimal("39.344"),
        position_fraction=Decimal("0.25"),
    )
    embed = activity_event_embed(sell)
    assert embed.title == "卖出 · MSTR 10/09 155P"
    assert "+39.34%" in (embed.description or "")
    assert embed.author.name == "AXIS · 1K 账户挑战"
    assert [field.name for field in embed.fields] == ["本次卖出", "仓位"]


def test_daily_summary_embeds_are_paginated_and_readable() -> None:
    snapshot = {
        "session_date": "2026-10-07",
        "fills": [
            {
                "account": "账户 TEST-8070",
                "code": f"US.TEST261016C{strike:03d}000",
                "side": "BUY",
                "quantity": "1",
                "price": "2.5",
            }
            for strike in range(100, 109)
        ],
        "accounts": [
            {
                "account": "账户 TEST-8070",
                "equity": "1250.80",
                "opening_equity": "1000.00",
                "commission": "6.51",
                "pre_fee_equity": "1250.80",
                "post_fee_equity": "1244.29",
                "pre_fee_profit": "250.80",
                "post_fee_profit": "244.29",
                "pre_fee_return_percent": "25.08",
                "post_fee_return_percent": "24.429",
            }
        ],
        "positions": [
            {
                "account": "账户 TEST-8070",
                "code": f"US.TEST261016C{strike:03d}000",
                "quantity": "1",
                "average_cost": "2.5",
                "current_price": "3",
                "unrealized_pnl": "50",
            }
            for strike in range(100, 106)
        ],
        "performance": {
            "closed_count": 3,
            "win_count": 2,
            "win_rate": "66.6667",
            "average_win": "12.345",
            "average_loss": "-8.5",
        },
    }
    embeds = daily_summary_embeds(snapshot)
    assert len(embeds) == 2
    assert embeds[0].title == "1K 挑战 · 收盘总结 · 2026-10-07"
    assert "日初净值**　$1,000" in embeds[0].fields[0].value
    assert "收盘净值 · 扣费前**　$1,250.8" in embeds[0].fields[0].value
    assert "佣金及交易费**　-$6.51" in embeds[0].fields[0].value
    assert "收盘净值 · 扣费后**　$1,244.29" in embeds[0].fields[0].value
    assert "今日净收益**　+$244.29　**+24.43%**" in embeds[0].fields[0].value
    assert [field.name for field in embeds[0].fields] == [
        "账户状态",
        "胜率",
        "平均盈利",
        "平均亏损",
        "当前持仓",
    ]
    assert embeds[0].fields[1].value == "**66.67%**"
    assert embeds[0].fields[2].value == "**+12.34%**"
    assert embeds[0].fields[3].value == "**-8.5%**"
    assert "今日成交" not in str(embeds[0].to_dict())
    assert embeds[1].title == "当前持仓 · PAGE 2"


def test_daily_summary_without_positions_explicitly_says_no_positions() -> None:
    embeds = daily_summary_embeds(
        {
            "session_date": "2026-10-08",
            "fills": [{"code": "US.SPY", "side": "BUY", "quantity": "2", "price": "700"}],
            "accounts": [{"equity": "1000", "equity_change_percent": "2"}],
            "positions": [],
        }
    )

    assert len(embeds) == 1
    assert [field.name for field in embeds[0].fields] == [
        "账户状态",
        "胜率",
        "平均盈利",
        "平均亏损",
        "当前持仓",
    ]
    assert embeds[0].fields[4].value == "无持仓"
    assert "今日成交" not in str(embeds[0].to_dict())


def test_daily_summary_groups_butterfly_and_calendar_positions() -> None:
    embeds = daily_summary_embeds(
        {
            "session_date": "2026-10-21",
            "accounts": [],
            "performance": {},
            "positions": [
                {
                    "code": "US.META261023C780/800/820",
                    "quantity": "2",
                    "average_cost": "0.74",
                    "current_price": "0.62",
                    "unrealized_pnl": "-24",
                    "unrealized_pnl_ratio": "-16.22",
                    "strategy_type": "BUTTERFLY",
                    "position_type": "COMBINED",
                },
                {
                    "code": "US.IBM261023C260/261120C260",
                    "quantity": "1",
                    "average_cost": "2.8",
                    "current_price": "2.95",
                    "unrealized_pnl": "15",
                    "unrealized_pnl_ratio": "5.36",
                    "strategy_type": "CALENDAR_SPREAD",
                    "position_type": "COMBINED",
                },
                {
                    "code": "US.SPY261028P768/770",
                    "quantity": "1",
                    "average_cost": "0.67",
                    "current_price": "0.69",
                    "unrealized_pnl": "2",
                    "unrealized_pnl_ratio": "2.99",
                    "strategy_type": "SPREAD",
                    "position_type": "COMBINED",
                },
            ],
        }
    )

    positions = embeds[0].fields[-1].value
    assert "META 10/23 780/800/820C · 蝶式" in positions
    assert "2组" in positions
    assert "-$24" in positions
    assert "-16.22%" in positions
    assert "IBM 10/23–11/20 260C · 日历价差" in positions
    assert "1组" in positions
    assert "+$15" in positions
    assert "+5.36%" in positions
    assert "SPY 10/28 768/770P · 垂直价差" in positions
    assert "+$2" in positions
    assert "+2.99%" in positions


@pytest.mark.asyncio
async def test_activity_dispatch_finds_existing_event_by_title_and_timestamp() -> None:
    occurred_at = datetime(2026, 10, 22, 18, 6, 30, 394000, tzinfo=UTC)
    embed = activity_event_embed(
        MoomooActivityEvent(
            kind="FILL",
            record_id=uuid.uuid4(),
            account_label="账户 TEST-8070",
            instrument_code="US.SPXW261022C7680000",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1.05"),
            status=None,
            occurred_at=occurred_at,
            action="BUY",
        )
    )
    existing = SimpleNamespace(
        author=SimpleNamespace(id=123),
        embeds=[embed],
    )

    class FakeChannel:
        async def history(self, *, limit: int):
            assert limit == 100
            yield existing

    cog = object.__new__(MoomooActivityCog)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=123))
    found = await cog._find_existing_event(FakeChannel(), embed)

    assert found is existing
