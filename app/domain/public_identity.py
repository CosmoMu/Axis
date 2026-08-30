from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class PublicIdentityViolation(ValueError):
    def __init__(self, code: str, field: str) -> None:
        super().__init__(code)
        self.code = code
        self.field = field


@dataclass(frozen=True, slots=True)
class PublicIdentityPolicy:
    """Single boundary for content that can leave AXIS private/admin surfaces."""

    operator_name: str = "VALE"
    owner_user_id: int | None = None
    additional_forbidden_terms: tuple[str, ...] = ()

    @property
    def forbidden_terms(self) -> tuple[str, ...]:
        return ("axis desk", "cosmo", "cosmos", *self.additional_forbidden_terms)

    def assert_public(self, value: Any, *, field: str = "public_payload") -> None:
        for path, text in self._strings(value, field):
            normalized = text.casefold()
            if any(term.casefold() in normalized for term in self.forbidden_terms if term.strip()):
                raise PublicIdentityViolation("PUBLIC_IDENTITY_FORBIDDEN_TERM", path)
            if self.owner_user_id is not None and str(self.owner_user_id) in text:
                raise PublicIdentityViolation("PUBLIC_IDENTITY_OWNER_ID", path)
            if re.search(r"<@!?\d{15,22}>", text):
                raise PublicIdentityViolation("PUBLIC_IDENTITY_DISCORD_ACCOUNT", path)
            if re.search(r"\b(?:private note|owner note|internal owner)\b", normalized):
                raise PublicIdentityViolation("PUBLIC_IDENTITY_PRIVATE_NOTE", path)

    @classmethod
    def _strings(cls, value: Any, path: str) -> list[tuple[str, str]]:
        if value is None:
            return []
        if isinstance(value, str):
            return [(path, value)]
        if isinstance(value, dict):
            result: list[tuple[str, str]] = []
            for key, item in value.items():
                result.extend(cls._strings(item, f"{path}.{key}"))
            return result
        if isinstance(value, (list, tuple, set)):
            result = []
            for index, item in enumerate(value):
                result.extend(cls._strings(item, f"{path}[{index}]"))
            return result
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return cls._strings(to_dict(), path)
        return []
