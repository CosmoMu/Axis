from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

import stripe


class StripeGatewayError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class StripeCheckout:
    id: str
    url: str


class StripeGateway(Protocol):
    async def create_checkout(
        self,
        *,
        price_id: str,
        membership_session_id: str,
        discord_user_id: int,
        membership_type: str,
        pricing_version: str,
        monthly: bool,
    ) -> StripeCheckout: ...

    async def create_portal(self, *, customer_id: str) -> str: ...

    async def cancel_at_period_end(self, *, subscription_id: str) -> None: ...

    async def cancel_subscription(self, *, subscription_id: str) -> None: ...

    def construct_event(self, body: bytes, signature: str | None) -> dict[str, Any]: ...


class StripeSdkGateway:
    def __init__(
        self,
        *,
        secret_key: str,
        webhook_secret: str,
        success_url: str,
        cancel_url: str,
        portal_return_url: str,
    ) -> None:
        if not all((secret_key, webhook_secret, success_url, cancel_url, portal_return_url)):
            raise StripeGatewayError("STRIPE_CONFIGURATION_INCOMPLETE")
        self.client = stripe.StripeClient(secret_key)
        self.webhook_secret = webhook_secret
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.portal_return_url = portal_return_url

    async def create_checkout(
        self,
        *,
        price_id: str,
        membership_session_id: str,
        discord_user_id: int,
        membership_type: str,
        pricing_version: str,
        monthly: bool,
    ) -> StripeCheckout:
        metadata = {
            "discord_user_id": str(discord_user_id),
            "membership_type": membership_type,
            "pricing_version": pricing_version,
            "membership_session_id": membership_session_id,
        }
        params: dict[str, Any] = {
            "mode": "subscription" if monthly else "payment",
            "line_items": [{"price": price_id, "quantity": 1}],
            "client_reference_id": membership_session_id,
            "metadata": metadata,
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
        }
        if monthly:
            params["subscription_data"] = {"metadata": metadata}
        try:
            result = await asyncio.to_thread(self.client.v1.checkout.sessions.create, params)
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_CHECKOUT_CREATE_FAILED") from exc
        url = str(result.url or "")
        if not result.id or not url:
            raise StripeGatewayError("STRIPE_CHECKOUT_URL_MISSING")
        return StripeCheckout(str(result.id), url)

    async def create_portal(self, *, customer_id: str) -> str:
        try:
            result = await asyncio.to_thread(
                self.client.v1.billing_portal.sessions.create,
                {"customer": customer_id, "return_url": self.portal_return_url},
            )
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_PORTAL_CREATE_FAILED") from exc
        url = str(result.url or "")
        if not url:
            raise StripeGatewayError("STRIPE_PORTAL_URL_MISSING")
        return url

    async def cancel_at_period_end(self, *, subscription_id: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.v1.subscriptions.update,
                subscription_id,
                {"cancel_at_period_end": True},
            )
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_SUBSCRIPTION_UPDATE_FAILED") from exc

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.v1.subscriptions.cancel,
                subscription_id,
                {},
            )
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_SUBSCRIPTION_CANCEL_FAILED") from exc

    def construct_event(self, body: bytes, signature: str | None) -> dict[str, Any]:
        if not signature:
            raise StripeGatewayError("STRIPE_SIGNATURE_MISSING")
        try:
            event = stripe.Webhook.construct_event(body, signature, self.webhook_secret)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise StripeGatewayError("STRIPE_SIGNATURE_INVALID") from exc
        return _plain_dict(event)


def _plain_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain_dict(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_dict(item) for item in value]
    return value
