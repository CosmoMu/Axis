from types import SimpleNamespace

from app.bot.message_input import extract_message_input


def attachment(attachment_id: int, filename: str) -> SimpleNamespace:
    async def read() -> bytes:
        return b"image"

    return SimpleNamespace(
        id=attachment_id,
        filename=filename,
        content_type="image/png",
        size=5,
        read=read,
    )


def test_forwarded_snapshots_are_combined_with_direct_message_input() -> None:
    direct = attachment(1, "direct.png")
    forwarded = attachment(2, "forwarded.png")
    message = SimpleNamespace(
        content="Manager context",
        attachments=[direct],
        message_snapshots=[
            SimpleNamespace(
                content="Forwarded mentor analysis",
                attachments=[forwarded, direct],
            )
        ],
    )
    result = extract_message_input(message)  # type: ignore[arg-type]
    assert result.content == "Manager context\n\n[Forwarded message 1]\nForwarded mentor analysis"
    assert [item.discord_attachment_id for item in result.attachments] == [1, 2]


def test_forwarded_only_content_is_not_treated_as_empty() -> None:
    message = SimpleNamespace(
        content="",
        attachments=[],
        message_snapshots=[SimpleNamespace(content="Forwarded only", attachments=[])],
    )
    result = extract_message_input(message)  # type: ignore[arg-type]
    assert result.content == "[Forwarded message 1]\nForwarded only"
    assert result.attachments == ()
