from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReviewMessageRef:
    draft_id: uuid.UUID
    channel_id: int
    message_id: int
