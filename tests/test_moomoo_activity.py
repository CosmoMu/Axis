from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.bot.moomoo_activity_cards import activity_event_text, daily_summary_messages
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
async def test_new_submitted_order_and_daily_summary_are_idempotent() -> None:
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
    events = await service.pending_events()
    assert len(events) == 1
    assert events[0].kind == "ORDER"

    first = await service.prepare_daily_summary(date(2026, 10, 7))
    assert first is not None
    assert first.snapshot["positions"][0]["code"] == "US.SPY"
    await service.mark_summary_published(first.id, [123])
    assert await service.prepare_daily_summary(date(2026, 10, 7)) is None
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
    assert "买入 **SPY** × 2" in activity_event_text(event)
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
