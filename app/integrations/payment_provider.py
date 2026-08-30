from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class PaymentProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CheckoutMetadata:
    session_id: str
    discord_user_id: int
    provider: str


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    provider: str
    provider_event_id: str
    event_type: str
    membership_session_id: str | None
    discord_user_id: int | None
    provider_customer_id: str | None
    provider_subscription_id: str | None
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool


class PaymentProvider(Protocol):
    name: str

    def checkout_url(self, base_url: str, metadata: CheckoutMetadata) -> str: ...

    def verify_signature(self, body: bytes, signature: str | None, secret: str) -> bool: ...

    def parse_event(self, payload: dict[str, Any]) -> PaymentEvent: ...


def _timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if not isinstance(value, str):
        raise PaymentProviderError("PAYMENT_TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaymentProviderError("PAYMENT_TIMESTAMP_INVALID") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class ExternalCheckoutProvider:
    """Provider-neutral checkout URL and signed webhook contract.

    The external checkout must preserve the two metadata values and echo them in
    webhook payloads. No payment vendor is coupled to AXIS core business code.
    """

    def __init__(self, name: str = "external") -> None:
        normalized = name.strip().lower()
        if not normalized or len(normalized) > 32:
            raise PaymentProviderError("PAYMENT_PROVIDER_INVALID")
        self.name = normalized

    def checkout_url(self, base_url: str, metadata: CheckoutMetadata) -> str:
        split = urlsplit(base_url)
        query = dict(parse_qsl(split.query, keep_blank_values=True))
        query.update(
            {
                "discord_user_id": str(metadata.discord_user_id),
                "membership_session_id": metadata.session_id,
                "payment_provider": metadata.provider,
            }
        )
        return urlunsplit(
            (split.scheme, split.netloc, split.path, urlencode(query), split.fragment)
        )

    def verify_signature(self, body: bytes, signature: str | None, secret: str) -> bool:
        if not secret or not signature:
            return False
        provided = signature.removeprefix("sha256=").strip().lower()
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(provided, expected)

    def parse_event(self, payload: dict[str, Any]) -> PaymentEvent:
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        raw_user_id = metadata.get("discord_user_id", payload.get("discord_user_id"))
        discord_user_id = None
        if raw_user_id not in {None, ""}:
            try:
                discord_user_id = int(raw_user_id)
            except (TypeError, ValueError) as exc:
                raise PaymentProviderError("PAYMENT_DISCORD_USER_ID_INVALID") from exc
            if discord_user_id <= 0:
                raise PaymentProviderError("PAYMENT_DISCORD_USER_ID_INVALID")
        event_id = str(payload.get("event_id") or "").strip()
        event_type = str(payload.get("event_type") or "").strip().lower()
        status = str(payload.get("status") or "").strip().upper()
        if not event_id:
            raise PaymentProviderError("PAYMENT_EVENT_ID_REQUIRED")
        if event_type not in {
            "subscription.active",
            "subscription.updated",
            "subscription.past_due",
            "subscription.cancelled",
            "subscription.expired",
        }:
            raise PaymentProviderError("PAYMENT_EVENT_TYPE_UNSUPPORTED")
        if status not in {
            "ACTIVE",
            "PAST_DUE",
            "CANCEL_AT_PERIOD_END",
            "CANCELLED",
            "EXPIRED",
        }:
            raise PaymentProviderError("PAYMENT_STATUS_INVALID")
        subscription_id = str(payload.get("subscription_id") or "").strip()
        if not subscription_id:
            raise PaymentProviderError("PAYMENT_SUBSCRIPTION_ID_REQUIRED")
        session_id = str(
            metadata.get("membership_session_id") or payload.get("membership_session_id") or ""
        ).strip()
        return PaymentEvent(
            provider=self.name,
            provider_event_id=event_id[:255],
            event_type=event_type,
            membership_session_id=session_id[:64] or None,
            discord_user_id=discord_user_id,
            provider_customer_id=(
                str(payload["customer_id"])[:255]
                if payload.get("customer_id") is not None
                else None
            ),
            provider_subscription_id=subscription_id[:255],
            status=status,
            current_period_start=_timestamp(payload.get("current_period_start")),
            current_period_end=_timestamp(payload.get("current_period_end")),
            cancel_at_period_end=bool(payload.get("cancel_at_period_end", False)),
        )
