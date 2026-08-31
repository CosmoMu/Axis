import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.bot.views.management_views import (
    MemberControlView,
    MemberDetailView,
    MentorControlView,
    MentorDetailView,
    membership_embed,
)
from app.services.membership_management import MembershipSnapshot
from app.services.mentor_management import MentorSnapshot


@pytest.mark.asyncio
async def test_control_panels_are_persistent_and_use_fixed_custom_ids() -> None:
    controller = object()
    mentor = MentorControlView(controller)  # type: ignore[arg-type]
    member = MemberControlView(controller)  # type: ignore[arg-type]
    assert mentor.is_persistent()
    assert member.is_persistent()
    assert {item.custom_id for item in mentor.children} == {
        "axis:mentor:select:v1",
        "axis:mentor:add:v1",
    }
    assert [item.custom_id for item in member.children] == ["axis:member:user-select:v2"]


def test_mentor_edit_and_delete_are_only_in_selected_mentor_detail() -> None:
    mentor = MentorSnapshot(
        id=uuid.uuid4(),
        guild_id=1543309921066684567,
        name="Abitrade",
        short_code="ABI",
        aliases=(),
        is_active=True,
        active_trades=(),
        historical_trades=(),
    )
    detail = MentorDetailView(object(), mentor)  # type: ignore[arg-type]
    assert [item.label for item in detail.children] == [
        "编辑",
        "停用",
        "修改订单 Mentor",
        "删除 Mentor",
    ]


def test_member_search_detail_and_membership_times() -> None:
    controller = object()
    detail = MemberDetailView(  # type: ignore[arg-type]
        controller,
        100000000000000001,
        has_active_membership=True,
    )
    assert [item.label for item in detail.children] == ["查看信息", "赠送会员", "移除会员"]
    assert all(not item.disabled for item in detail.children)

    started = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
    snapshot = MembershipSnapshot(
        id=uuid.uuid4(),
        guild_id=1543309921066684567,
        user_id=100000000000000001,
        status="ACTIVE",
        source="GIFT",
        provider=None,
        provider_customer_id=None,
        provider_subscription_id=None,
        starts_at=started,
        ends_at=started + timedelta(days=30),
        cancel_at_period_end=False,
        version=1,
    )
    embed = membership_embed(snapshot, snapshot.user_id, has_member_role=True)
    fields = {field.name: field.value for field in embed.fields}
    assert fields["加入服务器时间"] == "—"
    assert fields["加入会员时间"].startswith("<t:")
    assert fields["到期日期"].startswith("<t:")
    assert fields["Member Role"] == "Active"
