from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.bot.cogs.signal_input import is_signal_manager
from app.bot.intents import axis_intents
from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, SourceAttachment, SourceMessage
from app.db.session import Database
from app.domain.enums import SourceStatus
from app.services.attachment_storage import AttachmentValidationError, LocalAttachmentStore
from app.services.signal_input import (
    IncomingAttachment,
    IncomingSignal,
    IngestDisposition,
    SignalInputService,
)

GUILD_ID = 1543309921066684567
CHANNEL_ID = 1543397041881878570
USER_ID = 123456789012345678


async def _database() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        await session.commit()
    return database


def _signal(
    *,
    message_id: int,
    content: str = "SPY 600C entry 1.25",
    attachments: tuple[IncomingAttachment, ...] = (),
) -> IncomingSignal:
    return IncomingSignal(
        guild_id=GUILD_ID,
        message_id=message_id,
        channel_id=CHANNEL_ID,
        submitted_by=USER_ID,
        content=content,
        received_at=datetime.now(UTC),
        attachments=attachments,
    )


def _attachment(
    *,
    attachment_id: int,
    filename: str,
    content_type: str,
    data: bytes,
) -> IncomingAttachment:
    async def read() -> bytes:
        return data

    return IncomingAttachment(
        discord_attachment_id=attachment_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        read=read,
    )


def test_attachment_accepts_discord_filename_mime_disagreement(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"discord-converted-image"
    prepared = LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024).prepare(
        discord_attachment_id=7000,
        filename="image.webp",
        declared_content_type="image/png",
        declared_size=len(png),
        data=png,
    )
    assert prepared.extension == ".png"
    assert prepared.content_type == "image/png"
    assert prepared.display_filename == "image.webp"


def test_attachment_rejects_when_matching_metadata_disagrees_with_magic(
    tmp_path: Path,
) -> None:
    jpeg = b"\xff\xd8\xff" + b"actual-jpeg"
    store = LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024)
    with pytest.raises(AttachmentValidationError, match="ATTACHMENT_TYPE_MISMATCH"):
        store.prepare(
            discord_attachment_id=7000,
            filename="image.png",
            declared_content_type="image/png",
            declared_size=len(jpeg),
            data=jpeg,
        )


def test_attachment_rejects_when_conflicting_metadata_both_disagree_with_magic(
    tmp_path: Path,
) -> None:
    jpeg = b"\xff\xd8\xff" + b"actual-jpeg"
    store = LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024)
    with pytest.raises(AttachmentValidationError, match="ATTACHMENT_TYPE_MISMATCH"):
        store.prepare(
            discord_attachment_id=7000,
            filename="image.webp",
            declared_content_type="image/png",
            declared_size=len(jpeg),
            data=jpeg,
        )


@pytest.mark.asyncio
async def test_signal_ingest_stores_validated_attachment_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = await _database()
    png = b"\x89PNG\r\n\x1a\n" + b"axis-image"
    service = SignalInputService(
        database,
        LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024),
    )
    signal = _signal(
        message_id=9001,
        attachments=(
            _attachment(
                attachment_id=7001,
                filename="../../mentor-chart.png",
                content_type="image/png",
                data=png,
            ),
        ),
    )
    try:
        first = await service.ingest(signal)
        second = await service.ingest(signal)

        assert first.disposition is IngestDisposition.RECEIVED
        assert second.disposition is IngestDisposition.DUPLICATE
        assert first.source_message_id == second.source_message_id

        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(SourceMessage)) == 1
            assert await session.scalar(select(func.count()).select_from(SourceAttachment)) == 1
            assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1
            source = await session.scalar(select(SourceMessage))
            attachment = await session.scalar(select(SourceAttachment))
            audit = await session.scalar(select(AuditLog))

        assert source is not None and source.status == SourceStatus.RECEIVED.value
        assert attachment is not None
        assert attachment.filename == "mentor-chart.png"
        assert attachment.source_url is None
        assert attachment.storage_key == f"{GUILD_ID}/9001/7001.png"
        assert (tmp_path / "attachments" / attachment.storage_key).read_bytes() == png
        assert audit is not None
        assert audit.after_json == {
            "status": "RECEIVED",
            "attachment_count": 1,
            "reason_code": None,
        }
        assert "SPY" not in str(audit.after_json)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_signal_ingest_rejects_attachment_with_spoofed_image_type(tmp_path: Path) -> None:
    database = await _database()
    service = SignalInputService(
        database,
        LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024),
    )
    signal = _signal(
        message_id=9002,
        attachments=(
            _attachment(
                attachment_id=7002,
                filename="payload.png",
                content_type="image/png",
                data=b"not-a-real-image",
            ),
        ),
    )
    try:
        result = await service.ingest(signal)
        assert result.disposition is IngestDisposition.REJECTED
        assert result.reason_code == "ATTACHMENT_TYPE_UNSUPPORTED"
        async with database.session() as session:
            source = await session.scalar(select(SourceMessage))
            attachment_count = await session.scalar(
                select(func.count()).select_from(SourceAttachment)
            )
        assert source is not None and source.status == SourceStatus.REJECTED.value
        assert attachment_count == 0
        assert not (tmp_path / "attachments").exists()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_empty_signal_is_rejected_without_calling_attachment_storage(tmp_path: Path) -> None:
    database = await _database()
    service = SignalInputService(
        database,
        LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024),
    )
    try:
        result = await service.ingest(_signal(message_id=9003, content="   "))
        assert result.disposition is IngestDisposition.REJECTED
        assert result.reason_code == "EMPTY_SIGNAL"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_rejected_source_can_be_revalidated_without_deleting_audit(
    tmp_path: Path,
) -> None:
    database = await _database()
    service = SignalInputService(
        database,
        LocalAttachmentStore(tmp_path / "attachments", max_bytes=10 * 1024 * 1024),
    )
    try:
        rejected = await service.ingest(_signal(message_id=9004, content=""))
        retried = await service.retry_rejected(
            _signal(message_id=9004, content="forwarded analysis text")
        )
        duplicate = await service.retry_rejected(
            _signal(message_id=9004, content="forwarded analysis text")
        )
        assert rejected.disposition is IngestDisposition.REJECTED
        assert retried.disposition is IngestDisposition.RECEIVED
        assert duplicate.disposition is IngestDisposition.DUPLICATE
        async with database.session() as session:
            source = await session.scalar(select(SourceMessage))
            actions = list(
                await session.scalars(
                    select(AuditLog.action_type).order_by(AuditLog.created_at, AuditLog.id)
                )
            )
        assert source is not None and source.status == SourceStatus.RECEIVED.value
        assert actions == ["SOURCE_MESSAGE_REJECTED", "SOURCE_MESSAGE_RETRIED"]
    finally:
        await database.dispose()


def test_signal_intents_are_explicit_and_minimal() -> None:
    intents = axis_intents()
    assert intents.guilds
    assert intents.guild_messages
    assert intents.message_content
    assert intents.members
    assert not intents.dm_messages
    assert not intents.presences


def test_signal_manager_accepts_owner_or_manager_only() -> None:
    common = {
        "guild_owner_id": 1,
        "configured_owner_id": 2,
        "manager_role_id": 10,
    }
    assert is_signal_manager(user_id=1, role_ids=(), **common)
    assert is_signal_manager(user_id=2, role_ids=(), **common)
    assert is_signal_manager(user_id=3, role_ids=(10,), **common)
    assert not is_signal_manager(user_id=3, role_ids=(11,), **common)
