from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.ephemeral import send_temporary_ephemeral


@pytest.mark.asyncio
async def test_temporary_ephemeral_initial_response_uses_delete_after() -> None:
    response = SimpleNamespace(is_done=lambda: False, send_message=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    interaction = SimpleNamespace(response=response, followup=followup)

    await send_temporary_ephemeral(interaction, "saved", delete_after=4)

    response.send_message.assert_awaited_once_with(
        "saved",
        ephemeral=True,
        delete_after=4,
    )
    followup.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_temporary_ephemeral_followup_schedules_message_deletion() -> None:
    message = SimpleNamespace(delete=AsyncMock())
    response = SimpleNamespace(is_done=lambda: True, send_message=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock(return_value=message))
    interaction = SimpleNamespace(response=response, followup=followup)

    await send_temporary_ephemeral(interaction, "saved", delete_after=4)

    followup.send.assert_awaited_once_with(
        "saved",
        ephemeral=True,
        wait=True,
    )
    message.delete.assert_awaited_once_with(delay=4)
    response.send_message.assert_not_awaited()
