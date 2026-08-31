from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class StripeMode(StrEnum):
    TEST = "test"
    LIVE = "live"

    @classmethod
    def parse(cls, value: str) -> StripeMode:
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            raise ValueError("STRIPE_MODE must be test or live") from exc

    @property
    def database_value(self) -> str:
        return self.value.upper()

    @property
    def metadata_value(self) -> str:
        return "PRODUCTION" if self is StripeMode.LIVE else "TEST"

    @property
    def livemode(self) -> bool:
        return self is StripeMode.LIVE


@dataclass(frozen=True, slots=True)
class StripeEnvironmentConfig:
    mode: StripeMode
    secret_key: str
    publishable_key: str
    webhook_secret: str
    webhook_url: str | None
    success_url: str | None
    cancel_url: str | None
    portal_return_url: str | None
    day_pass_product_id: str | None
    day_pass_price_id: str | None
    day_pass_pricing_version: str
    monthly_product_id: str | None
    monthly_price_id: str | None
    monthly_pricing_version: str

    def runtime_missing(self) -> tuple[str, ...]:
        values = {
            "secret_key": self.secret_key,
            "webhook_secret": self.webhook_secret,
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
            "portal_return_url": self.portal_return_url,
            "day_pass_product_id": self.day_pass_product_id,
            "day_pass_price_id": self.day_pass_price_id,
            "monthly_product_id": self.monthly_product_id,
            "monthly_price_id": self.monthly_price_id,
        }
        return tuple(name for name, value in values.items() if not value)

    def readiness_issues(self) -> tuple[str, ...]:
        issues = list(self.runtime_missing())
        if not self.publishable_key:
            issues.append("publishable_key")
        expected_secret = "sk_live_" if self.mode is StripeMode.LIVE else "sk_test_"
        expected_publishable = "pk_live_" if self.mode is StripeMode.LIVE else "pk_test_"
        if self.secret_key and not self.secret_key.startswith(expected_secret):
            issues.append("secret_key_mode_mismatch")
        if self.publishable_key and not self.publishable_key.startswith(expected_publishable):
            issues.append("publishable_key_mode_mismatch")
        if self.webhook_secret and not self.webhook_secret.startswith("whsec_"):
            issues.append("webhook_secret_invalid")
        if self.mode is StripeMode.LIVE:
            parsed_webhook = urlparse(self.webhook_url or "")
            if (
                parsed_webhook.scheme != "https"
                or not parsed_webhook.netloc
                or parsed_webhook.path.rstrip("/") != "/webhooks/stripe"
            ):
                issues.append("public_https_webhook_url")
        if (
            self.day_pass_product_id
            and self.monthly_product_id
            and self.day_pass_product_id != self.monthly_product_id
        ):
            issues.append("product_id_mismatch")
        return tuple(dict.fromkeys(issues))

    @property
    def runtime_ready(self) -> bool:
        return not self.runtime_missing()

    @property
    def live_ready(self) -> bool:
        return not self.readiness_issues()


@dataclass(frozen=True, slots=True)
class StripeConfig:
    enabled: bool
    payments_enabled: bool
    mode: StripeMode
    test: StripeEnvironmentConfig
    live: StripeEnvironmentConfig

    @property
    def active(self) -> StripeEnvironmentConfig:
        return self.live if self.mode is StripeMode.LIVE else self.test

    def runtime_ready(self) -> bool:
        return self.enabled and self.active.runtime_ready

    def readiness_issues(self) -> tuple[str, ...]:
        issues: list[str] = []
        if not self.enabled:
            issues.append("stripe_disabled")
        issues.extend(self.active.readiness_issues())
        if self.payments_enabled and not self.active.live_ready:
            issues.append("payments_enabled_without_complete_environment")
        return tuple(dict.fromkeys(issues))
