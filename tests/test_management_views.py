import pytest

from app.bot.views.management_views import MemberControlView, MentorControlView


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
        "axis:mentor:edit:v1",
    }
    assert {item.custom_id for item in member.children} == {
        "axis:member:lookup:v1",
        "axis:member:gift:v1",
        "axis:member:extend:v1",
        "axis:member:cancel:v1",
        "axis:member:remove:v1",
    }
