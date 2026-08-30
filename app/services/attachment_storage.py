from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path


class AttachmentValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AttachmentStorageError(RuntimeError):
    """Raised when a validated attachment cannot be stored safely."""


@dataclass(frozen=True, slots=True)
class PreparedAttachment:
    discord_attachment_id: int
    display_filename: str
    content_type: str
    size_bytes: int
    extension: str
    checksum_sha256: str
    data: bytes


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    discord_attachment_id: int
    display_filename: str
    content_type: str
    size_bytes: int
    storage_key: str
    checksum_sha256: str


_MIME_TO_EXTENSION = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_EXTENSION_ALIASES = {
    ".png": ".png",
    ".jpg": ".jpg",
    ".jpeg": ".jpg",
    ".webp": ".webp",
}


def _detected_extension(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _display_filename(filename: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1]
    printable = "".join(character if character.isprintable() else "_" for character in leaf)
    return (printable or "attachment")[:255]


class LocalAttachmentStore:
    def __init__(self, root: Path, *, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def prepare(
        self,
        *,
        discord_attachment_id: int,
        filename: str,
        declared_content_type: str | None,
        declared_size: int,
        data: bytes,
    ) -> PreparedAttachment:
        if declared_size > self.max_bytes or len(data) > self.max_bytes:
            raise AttachmentValidationError("ATTACHMENT_TOO_LARGE")
        if not data:
            raise AttachmentValidationError("ATTACHMENT_EMPTY")
        if declared_size != len(data):
            raise AttachmentValidationError("ATTACHMENT_SIZE_MISMATCH")

        mime = (declared_content_type or "").split(";", 1)[0].strip().lower()
        declared_extension = _MIME_TO_EXTENSION.get(mime)
        filename_extension = _EXTENSION_ALIASES.get(Path(filename).suffix.lower())
        detected_extension = _detected_extension(data)
        if not declared_extension or not filename_extension or not detected_extension:
            raise AttachmentValidationError("ATTACHMENT_TYPE_UNSUPPORTED")
        if len({declared_extension, filename_extension, detected_extension}) != 1:
            raise AttachmentValidationError("ATTACHMENT_TYPE_MISMATCH")

        return PreparedAttachment(
            discord_attachment_id=discord_attachment_id,
            display_filename=_display_filename(filename),
            content_type=mime,
            size_bytes=len(data),
            extension=detected_extension,
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            data=data,
        )

    async def write(
        self,
        *,
        guild_id: int,
        message_id: int,
        attachment: PreparedAttachment,
    ) -> StoredAttachment:
        storage_key = (
            f"{guild_id}/{message_id}/"
            f"{attachment.discord_attachment_id}{attachment.extension}"
        )
        path = self.root / storage_key
        await asyncio.to_thread(self._write_atomic, path, attachment)
        return StoredAttachment(
            discord_attachment_id=attachment.discord_attachment_id,
            display_filename=attachment.display_filename,
            content_type=attachment.content_type,
            size_bytes=attachment.size_bytes,
            storage_key=storage_key,
            checksum_sha256=attachment.checksum_sha256,
        )

    async def read_verified(self, storage_key: str, checksum_sha256: str) -> bytes:
        if not storage_key or not checksum_sha256:
            raise AttachmentStorageError("attachment metadata is incomplete")
        candidate = (self.root / storage_key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise AttachmentStorageError("attachment path is invalid")
        try:
            data = await asyncio.to_thread(candidate.read_bytes)
        except OSError as exc:
            raise AttachmentStorageError("attachment read failed") from exc
        if not data or len(data) > self.max_bytes:
            raise AttachmentStorageError("attachment size is invalid")
        if hashlib.sha256(data).hexdigest() != checksum_sha256:
            raise AttachmentStorageError("attachment checksum differs")
        return data

    def _write_atomic(self, path: Path, attachment: PreparedAttachment) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing_checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if existing_checksum == attachment.checksum_sha256:
                return
            raise AttachmentStorageError("existing attachment checksum differs")

        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as output:
                output.write(attachment.data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise AttachmentStorageError("attachment write failed") from exc
        finally:
            temporary.unlink(missing_ok=True)
