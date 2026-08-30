from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import AuditLog, SourceAttachment, SourceMessage
from app.db.session import Database
from app.domain.enums import SourceKind, SourceStatus
from app.services.attachment_storage import (
    AttachmentStorageError,
    AttachmentValidationError,
    LocalAttachmentStore,
    StoredAttachment,
)


class IngestDisposition(StrEnum):
    RECEIVED = "RECEIVED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class IncomingAttachment:
    discord_attachment_id: int
    filename: str
    content_type: str | None
    size_bytes: int
    read: Callable[[], Awaitable[bytes]]


@dataclass(frozen=True, slots=True)
class IncomingSignal:
    guild_id: int
    message_id: int
    channel_id: int
    submitted_by: int
    content: str
    received_at: datetime
    attachments: Sequence[IncomingAttachment]
    source_kind: SourceKind = SourceKind.SIGNAL


@dataclass(frozen=True, slots=True)
class IngestResult:
    disposition: IngestDisposition
    source_message_id: str
    reason_code: str | None = None


class SignalInputService:
    def __init__(self, database: Database, attachment_store: LocalAttachmentStore) -> None:
        self.database = database
        self.attachment_store = attachment_store

    async def ingest(self, signal: IncomingSignal) -> IngestResult:
        existing = await self._find_existing(signal.guild_id, signal.message_id)
        if existing is not None:
            return IngestResult(IngestDisposition.DUPLICATE, str(existing.id))

        raw_text = signal.content.strip() or None
        if raw_text is None and not signal.attachments:
            return await self._persist(
                signal,
                raw_text=None,
                status=SourceStatus.REJECTED,
                stored_attachments=(),
                reason_code="EMPTY_SIGNAL",
            )

        try:
            prepared = []
            for attachment in signal.attachments:
                if attachment.size_bytes > self.attachment_store.max_bytes:
                    raise AttachmentValidationError("ATTACHMENT_TOO_LARGE")
                try:
                    data = await attachment.read()
                except Exception:
                    return await self._persist(
                        signal,
                        raw_text=raw_text,
                        status=SourceStatus.FAILED,
                        stored_attachments=(),
                        reason_code="ATTACHMENT_READ_FAILED",
                    )
                prepared.append(
                    self.attachment_store.prepare(
                        discord_attachment_id=attachment.discord_attachment_id,
                        filename=attachment.filename,
                        declared_content_type=attachment.content_type,
                        declared_size=attachment.size_bytes,
                        data=data,
                    )
                )

            stored = [
                await self.attachment_store.write(
                    guild_id=signal.guild_id,
                    message_id=signal.message_id,
                    attachment=attachment,
                )
                for attachment in prepared
            ]
        except AttachmentValidationError as exc:
            return await self._persist(
                signal,
                raw_text=raw_text,
                status=SourceStatus.REJECTED,
                stored_attachments=(),
                reason_code=exc.code,
            )
        except (AttachmentStorageError, OSError):
            return await self._persist(
                signal,
                raw_text=raw_text,
                status=SourceStatus.FAILED,
                stored_attachments=(),
                reason_code="ATTACHMENT_STORAGE_FAILED",
            )

        return await self._persist(
            signal,
            raw_text=raw_text,
            status=SourceStatus.RECEIVED,
            stored_attachments=stored,
            reason_code=None,
        )

    async def _find_existing(self, guild_id: int, message_id: int) -> SourceMessage | None:
        async with self.database.session() as session:
            return await session.scalar(
                select(SourceMessage).where(
                    SourceMessage.guild_id == guild_id,
                    SourceMessage.discord_message_id == message_id,
                )
            )

    async def _persist(
        self,
        signal: IncomingSignal,
        *,
        raw_text: str | None,
        status: SourceStatus,
        stored_attachments: Sequence[StoredAttachment],
        reason_code: str | None,
    ) -> IngestResult:
        disposition = IngestDisposition(status.value)
        async with self.database.session() as session:
            source = SourceMessage(
                guild_id=signal.guild_id,
                discord_message_id=signal.message_id,
                channel_id=signal.channel_id,
                submitted_by=signal.submitted_by,
                raw_text=raw_text,
                source_kind=signal.source_kind.value,
                status=status.value,
                received_at=signal.received_at,
            )
            session.add(source)
            try:
                await session.flush()
                for attachment in stored_attachments:
                    session.add(
                        SourceAttachment(
                            source_message_id=source.id,
                            discord_attachment_id=attachment.discord_attachment_id,
                            filename=attachment.display_filename,
                            content_type=attachment.content_type,
                            size_bytes=attachment.size_bytes,
                            source_url=None,
                            storage_key=attachment.storage_key,
                            checksum_sha256=attachment.checksum_sha256,
                        )
                    )
                session.add(
                    AuditLog(
                        guild_id=signal.guild_id,
                        actor_user_id=signal.submitted_by,
                        action_type=f"SOURCE_MESSAGE_{status.value}",
                        entity_type="source_message",
                        entity_id=str(source.id),
                        before_json=None,
                        after_json={
                            "status": status.value,
                            "attachment_count": len(stored_attachments),
                            "reason_code": reason_code,
                        },
                        discord_interaction_id=None,
                    )
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self._find_existing(signal.guild_id, signal.message_id)
                if existing is None:
                    raise
                return IngestResult(IngestDisposition.DUPLICATE, str(existing.id))

        return IngestResult(disposition, str(source.id), reason_code)
