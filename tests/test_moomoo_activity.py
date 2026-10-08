from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.bot.moomoo_activity_cards import (
    activity_event_embed,
    activity_event_text,
    daily_summary_embeds,
    daily_summary_messages,
)
from app.db.base import Base
from app.db.models import GuildConfig
from app.db.session import Database
from app.integrations.moomoo_activity import (
    ActivityAccount,
    ActivityFill,
    ActivityOrder,
    ActivityPosition,
    ActivitySnapshot,
)
from app.services.moomoo_activity import MoomooActivityEvent, MoomooActivityService

GUILD_ID = 1543309921066684567
ACCOUNT_REF = "acct_1234567890abcdef"


class FakeActivityReader:
    def __init__(self, snapshot: ActivitySnapshot) -> None:
        self.snapshot = snapshot

    async def read_snapshot(self) -> ActivitySnapshot:
        return self.snapshot


def make_snapshot(
    *,
    orders: tuple[ActivityOrder, ...] = (),
    fills: tuple[ActivityFill, ...] = (),
) -> ActivitySnapshot:
    now = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
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
                "equity_change_percent": "25",
            }
        ],
        "positions": [],
    }
    embeds = daily_summary_embeds(snapshot)
    assert len(embeds) == 2
    assert embeds[0].title == "收盘汇总 · 2026-10-07"
    assert "相比昨日 **+25%**" in embeds[0].fields[0].value
    assert embeds[1].title == "今日成交 · PAGE 2"
