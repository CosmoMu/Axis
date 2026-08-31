import uuid

import pytest

from app.bot.views.management_views import (
    MemberControlView,
    MentorControlView,
    MentorDetailView,
)
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
    assert {item.custom_id for item in member.children} == {
        "axis:member:lookup:v1",
        "axis:member:gift:v1",
        "axis:member:extend:v1",
        "axis:member:cancel:v1",
        "axis:member:remove:v1",
    }


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
