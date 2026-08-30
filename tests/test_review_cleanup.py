from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bot.review_cleanup import delete_owned_bot_message


class FakeMessage:
    def __init__(self, author_id: int) -> None:
        self.author = SimpleNamespace(id=author_id)
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeChannel:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message

    async def fetch_message(self, message_id: int) -> FakeMessage:
        assert message_id == 800
        return self.message


def fake_bot(message: FakeMessage) -> SimpleNamespace:
    channel = FakeChannel(message)
    return SimpleNamespace(
        user=SimpleNamespace(id=100),
        get_channel=lambda channel_id: channel if channel_id == 700 else None,
    )


@pytest.mark.asyncio
async def test_cleanup_deletes_only_message_owned_by_axis_bot() -> None:
    owned = FakeMessage(author_id=100)
    assert await delete_owned_bot_message(
        fake_bot(owned),  # type: ignore[arg-type]
        channel_id=700,
        message_id=800,
    )
    assert owned.deleted is True

    manager_message = FakeMessage(author_id=200)
    assert not await delete_owned_bot_message(
        fake_bot(manager_message),  # type: ignore[arg-type]
        channel_id=700,
        message_id=800,
    )
    assert manager_message.deleted is False
