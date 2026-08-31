from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from app.integrations.stripe_config import (
    StripeConfig,
    StripeEnvironmentConfig,
    StripeMode,
)


class ConfigurationError(RuntimeError):
    """Raised when runtime configuration is absent or unsafe."""


def _parse_stripe_mode(name: str = "STRIPE_MODE") -> StripeMode:
    raw = os.getenv(name, StripeMode.TEST.value)
    try:
        return StripeMode.parse(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be test or live.") from exc


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} 必须是 true 或 false。")


def _parse_bool_alias(name: str, legacy_name: str, default: bool) -> bool:
    if os.getenv(name) is not None:
        return _parse_bool(name, default)
    return _parse_bool(legacy_name, default)


def _parse_optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是 Discord Snowflake 数字。") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} 必须大于 0。")
    return value


def _parse_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是正整数。") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} 必须大于 0。")
    return value


def _parse_nonnegative_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是非负整数。") from exc
    if value < 0:
        raise ConfigurationError(f"{name} 不能小于 0。")
    return value


def _parse_time_hhmm(name: str, default: str) -> str:
    raw = os.getenv(name, default).strip()
    parts = raw.split(":")
    if len(parts) != 2 or any(not part.isdigit() for part in parts):
        raise ConfigurationError(f"{name} 必须使用 HH:MM 格式。")
    hour, minute = (int(part) for part in parts)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ConfigurationError(f"{name} 必须是有效的 24 小时时间。")
    return f"{hour:02d}:{minute:02d}"


def _parse_optional_url(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"{name} 必须是有效的 http/https URL。")
    return raw


def _parse_date(name: str, default: str) -> date:
    raw = os.getenv(name, default).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须使用 YYYY-MM-DD 格式。") from exc


def _parse_timezone(name: str, default: str) -> str:
    raw = os.getenv(name, default).strip() or default
    try:
        ZoneInfo(raw)
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(f"{name} 不是有效时区。") from exc
    return raw


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    discord_bot_token: str
    discord_guild_id: int
    discord_application_id: int | None
    discord_owner_user_id: int | None
    database_url: str
    apply_changes: bool
    dry_run: bool
    analysis_enabled: bool
    moomoo_enabled: bool
    daily_summary_enabled: bool
    short_term_tracking_enabled: bool
    axis_stock_analyst_enabled: bool
    moomoo_host: str
    moomoo_port: int
    daily_summary_time_et: str
    massive_api_key: str
    massive_base_url: str
    short_term_tracking_config_path: Path
    blueprint_path: Path
    ids_path: Path
    report_path: Path
    attachment_storage_path: Path
    max_attachment_bytes: int
    llm_provider: str
    openai_api_key: str
    llm_routing_path: Path
    llm_default_model_override: str | None
    llm_signal_model_override: str | None
    llm_signal_repair_model_override: str | None
    llm_analysis_model_override: str | None
    llm_analysis_rewrite_model_override: str | None
    llm_timeout_seconds: int
    llm_max_retries: int
    llm_prompt_path: Path
    llm_analysis_prompt_path: Path
    production_data_start_date: date = date(2026, 8, 31)
    production_data_start_timezone: str = "America/New_York"
    deployment_stage: str = "SOFT_OPEN"
    results_review_enabled: bool = True
    results_review_draft_delay_minutes: int = 1
    results_final_publish_time: str = "16:15"
    results_timezone: str = "America/New_York"
    public_operator_name: str = "VALE"
    public_identity_forbidden_terms: tuple[str, ...] = ()
    lab_enabled: bool = False
    model_ab_enabled: bool = False
    membership_price_display: str = "价格见支付页面"
    subscription_url: str | None = None
    customer_portal_url: str | None = None
    payment_provider: str = "external"
    payment_webhook_host: str = "127.0.0.1"
    payment_webhook_port: int = 8787
    payment_webhook_secret: str = ""
    membership_session_ttl_minutes: int = 30
    system_alert_check_seconds: int = 30
    stripe_reconciliation_minutes: int = 15
    stripe_enabled: bool = False
    payments_enabled: bool = False
    stripe_mode: StripeMode = StripeMode.TEST
    stripe_test_secret_key: str = ""
    stripe_test_publishable_key: str = ""
    stripe_test_webhook_secret: str = ""
    stripe_test_webhook_url: str | None = None
    stripe_test_success_url: str | None = None
    stripe_test_cancel_url: str | None = None
    stripe_test_portal_return_url: str | None = None
    stripe_test_day_pass_product_id: str | None = None
    stripe_test_day_pass_price_id: str | None = None
    stripe_test_day_pass_pricing_version: str = "DAY_PASS_V1"
    stripe_test_monthly_product_id: str | None = None
    stripe_test_monthly_price_id: str | None = None
    stripe_test_monthly_pricing_version: str = "MONTHLY_V1"
    stripe_live_secret_key: str = ""
    stripe_live_publishable_key: str = ""
    stripe_live_webhook_secret: str = ""
    stripe_live_webhook_url: str | None = None
    stripe_live_success_url: str | None = None
    stripe_live_cancel_url: str | None = None
    stripe_live_portal_return_url: str | None = None
    stripe_live_day_pass_product_id: str | None = None
    stripe_live_day_pass_price_id: str | None = None
    stripe_live_day_pass_pricing_version: str = "DAY_PASS_V1"
    stripe_live_monthly_product_id: str | None = None
    stripe_live_monthly_price_id: str | None = None
    stripe_live_monthly_pricing_version: str = "MONTHLY_V1"
    stripe_live_webhook_relay_url: str | None = None
    stripe_live_webhook_relay_secret: str = ""
    stripe_live_webhook_relay_poll_seconds: int = 5

    @classmethod
    def load(cls, project_root: Path | None = None) -> Settings:
        root = (project_root or Path(__file__).resolve().parents[1]).resolve()
        load_dotenv(root / ".env", override=False)

        guild_id = _parse_optional_int("DISCORD_GUILD_ID")
        if guild_id is None:
            raise ConfigurationError("缺少 DISCORD_GUILD_ID。")

        ids_value = os.getenv("DISCORD_IDS_PATH", "config/discord_ids.json")
        report_value = os.getenv("DISCORD_DRY_RUN_REPORT", "var/discord/dry-run.json")
        attachment_value = os.getenv("ATTACHMENT_STORAGE_PATH", "var/attachments")
        llm_routing_value = os.getenv("LLM_ROUTING_CONFIG", "config/model_routing.yaml")
        llm_prompt_value = os.getenv("LLM_PROMPT_PATH", "config/llm_trade_prompt.txt")
        llm_analysis_prompt_value = os.getenv(
            "LLM_ANALYSIS_PROMPT_PATH", "config/llm_analysis_prompt.txt"
        )
        short_term_tracking_value = os.getenv(
            "SHORT_TERM_TRACKING_CONFIG", "config/short_term_tracking.yaml"
        )
        preferred_openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        legacy_openai_key = os.getenv("LLM_API_KEY", "").strip()
        default_model_override = os.getenv("LLM_DEFAULT_MODEL", "").strip()
        if not default_model_override:
            default_model_override = os.getenv("LLM_MODEL", "").strip()
        return cls(
            project_root=root,
            discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
            discord_guild_id=guild_id,
            discord_application_id=_parse_optional_int("DISCORD_APPLICATION_ID"),
            discord_owner_user_id=_parse_optional_int("DISCORD_OWNER_USER_ID"),
            database_url=os.getenv("DATABASE_URL", "").strip(),
            apply_changes=_parse_bool("APPLY_CHANGES", False),
            dry_run=_parse_bool("DRY_RUN", True),
            analysis_enabled=_parse_bool("FEATURE_ANALYSIS_ENABLED", False),
            moomoo_enabled=_parse_bool("FEATURE_MOOMOO_ENABLED", False),
            daily_summary_enabled=_parse_bool("FEATURE_DAILY_SUMMARY_ENABLED", True),
            short_term_tracking_enabled=_parse_bool("FEATURE_SHORT_TERM_TRACKING_ENABLED", False),
            axis_stock_analyst_enabled=_parse_bool_alias(
                "FEATURE_AXIS_STOCK_ANALYST_ENABLED",
                "FEATURE_COSMOS_STOCK_ANALYST_ENABLED",
                False,
            ),
            moomoo_host=os.getenv("MOOMOO_OPEND_HOST", "127.0.0.1").strip() or "127.0.0.1",
            moomoo_port=_parse_positive_int("MOOMOO_OPEND_PORT", 11111),
            daily_summary_time_et=_parse_time_hhmm("DAILY_SUMMARY_TIME_ET", "16:15"),
            massive_api_key=os.getenv("MASSIVE_API_KEY", "").strip(),
            massive_base_url=(
                os.getenv("MASSIVE_BASE_URL", "https://api.massive.com").strip()
                or "https://api.massive.com"
            ).rstrip("/"),
            short_term_tracking_config_path=(root / short_term_tracking_value).resolve(),
            blueprint_path=root / "config" / "discord_blueprint.yaml",
            ids_path=(root / ids_value).resolve(),
            report_path=(root / report_value).resolve(),
            attachment_storage_path=(root / attachment_value).resolve(),
            max_attachment_bytes=_parse_positive_int("MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024),
            llm_provider=os.getenv("LLM_PROVIDER", "openai").strip().lower(),
            openai_api_key=preferred_openai_key or legacy_openai_key,
            llm_routing_path=(root / llm_routing_value).resolve(),
            llm_default_model_override=default_model_override or None,
            llm_signal_model_override=os.getenv("LLM_SIGNAL_MODEL", "").strip() or None,
            llm_signal_repair_model_override=(
                os.getenv("LLM_SIGNAL_REPAIR_MODEL", "").strip() or None
            ),
            llm_analysis_model_override=(os.getenv("LLM_ANALYSIS_MODEL", "").strip() or None),
            llm_analysis_rewrite_model_override=(
                os.getenv("LLM_ANALYSIS_REWRITE_MODEL", "").strip() or None
            ),
            llm_timeout_seconds=_parse_positive_int("LLM_TIMEOUT_SECONDS", 45),
            llm_max_retries=_parse_nonnegative_int("LLM_MAX_RETRIES", 2),
            llm_prompt_path=(root / llm_prompt_value).resolve(),
            llm_analysis_prompt_path=(root / llm_analysis_prompt_value).resolve(),
            production_data_start_date=_parse_date("PRODUCTION_DATA_START_DATE", "2026-08-31"),
            production_data_start_timezone=_parse_timezone(
                "PRODUCTION_DATA_START_TIMEZONE", "America/New_York"
            ),
            deployment_stage=(
                os.getenv("DEPLOYMENT_STAGE", "SOFT_OPEN").strip().upper() or "SOFT_OPEN"
            ),
            results_review_enabled=_parse_bool("RESULTS_REVIEW_ENABLED", True),
            results_review_draft_delay_minutes=_parse_nonnegative_int(
                "RESULTS_REVIEW_DRAFT_DELAY_MINUTES", 1
            ),
            results_final_publish_time=_parse_time_hhmm("RESULTS_FINAL_PUBLISH_TIME", "16:15"),
            results_timezone=_parse_timezone("RESULTS_TIMEZONE", "America/New_York"),
            public_operator_name=(os.getenv("PUBLIC_OPERATOR_NAME", "VALE").strip() or "VALE")[:40],
            public_identity_forbidden_terms=tuple(
                item.strip()
                for item in os.getenv("PUBLIC_IDENTITY_FORBIDDEN_TERMS", "").split(",")
                if item.strip()
            ),
            lab_enabled=_parse_bool("FEATURE_LAB_ENABLED", False),
            model_ab_enabled=_parse_bool("FEATURE_MODEL_AB_ENABLED", False),
            membership_price_display=(
                os.getenv("MEMBERSHIP_PRICE_DISPLAY", "价格见支付页面").strip() or "价格见支付页面"
            ),
            subscription_url=_parse_optional_url("SUBSCRIPTION_URL"),
            customer_portal_url=_parse_optional_url("CUSTOMER_PORTAL_URL"),
            payment_provider=(
                os.getenv("PAYMENT_PROVIDER", "external").strip().lower() or "external"
            ),
            payment_webhook_host=(
                os.getenv("PAYMENT_WEBHOOK_HOST", "127.0.0.1").strip() or "127.0.0.1"
            ),
            payment_webhook_port=_parse_positive_int("PAYMENT_WEBHOOK_PORT", 8787),
            payment_webhook_secret=os.getenv("PAYMENT_WEBHOOK_SECRET", "").strip(),
            membership_session_ttl_minutes=_parse_positive_int(
                "MEMBERSHIP_SESSION_TTL_MINUTES", 30
            ),
            system_alert_check_seconds=_parse_positive_int("SYSTEM_ALERT_CHECK_SECONDS", 30),
            stripe_reconciliation_minutes=_parse_positive_int(
                "STRIPE_RECONCILIATION_MINUTES", 15
            ),
            stripe_enabled=_parse_bool("STRIPE_ENABLED", False),
            payments_enabled=_parse_bool("PAYMENTS_ENABLED", False),
            stripe_mode=_parse_stripe_mode(),
            # Legacy STRIPE_* aliases are accepted for TEST only. LIVE never falls back
            # to a shared credential or identifier.
            stripe_test_secret_key=(
                os.getenv("STRIPE_TEST_SECRET_KEY", "").strip()
                or os.getenv("STRIPE_SECRET_KEY", "").strip()
            ),
            stripe_test_publishable_key=os.getenv(
                "STRIPE_TEST_PUBLISHABLE_KEY", ""
            ).strip(),
            stripe_test_webhook_secret=(
                os.getenv("STRIPE_TEST_WEBHOOK_SECRET", "").strip()
                or os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
            ),
            stripe_test_webhook_url=_parse_optional_url("STRIPE_TEST_WEBHOOK_URL"),
            stripe_test_success_url=(
                _parse_optional_url("STRIPE_TEST_SUCCESS_URL")
                or _parse_optional_url("STRIPE_SUCCESS_URL")
            ),
            stripe_test_cancel_url=(
                _parse_optional_url("STRIPE_TEST_CANCEL_URL")
                or _parse_optional_url("STRIPE_CANCEL_URL")
            ),
            stripe_test_portal_return_url=(
                _parse_optional_url("STRIPE_TEST_PORTAL_RETURN_URL")
                or _parse_optional_url("STRIPE_PORTAL_RETURN_URL")
            ),
            stripe_test_day_pass_product_id=(
                os.getenv("STRIPE_TEST_DAY_PASS_PRODUCT_ID", "").strip()
                or os.getenv("STRIPE_DAY_PASS_PRODUCT_ID", "").strip()
                or None
            ),
            stripe_test_day_pass_price_id=(
                os.getenv("STRIPE_TEST_DAY_PASS_PRICE_ID", "").strip()
                or os.getenv("STRIPE_DAY_PASS_PRICE_ID", "").strip()
                or None
            ),
            stripe_test_day_pass_pricing_version=(
                os.getenv("STRIPE_TEST_DAY_PASS_PRICING_VERSION", "").strip()
                or os.getenv("STRIPE_DAY_PASS_PRICING_VERSION", "DAY_PASS_V1").strip()
                or "DAY_PASS_V1"
            ),
            stripe_test_monthly_product_id=(
                os.getenv("STRIPE_TEST_MONTHLY_PRODUCT_ID", "").strip()
                or os.getenv("STRIPE_MONTHLY_PRODUCT_ID", "").strip()
                or None
            ),
            stripe_test_monthly_price_id=(
                os.getenv("STRIPE_TEST_MONTHLY_PRICE_ID", "").strip()
                or os.getenv("STRIPE_MONTHLY_PRICE_ID", "").strip()
                or None
            ),
            stripe_test_monthly_pricing_version=(
                os.getenv("STRIPE_TEST_MONTHLY_PRICING_VERSION", "").strip()
                or os.getenv("STRIPE_MONTHLY_PRICING_VERSION", "MONTHLY_V1").strip()
                or "MONTHLY_V1"
            ),
            stripe_live_secret_key=os.getenv("STRIPE_LIVE_SECRET_KEY", "").strip(),
            stripe_live_publishable_key=os.getenv(
                "STRIPE_LIVE_PUBLISHABLE_KEY", ""
            ).strip(),
            stripe_live_webhook_secret=os.getenv(
                "STRIPE_LIVE_WEBHOOK_SECRET", ""
            ).strip(),
            stripe_live_webhook_url=_parse_optional_url("STRIPE_LIVE_WEBHOOK_URL"),
            stripe_live_success_url=_parse_optional_url("STRIPE_LIVE_SUCCESS_URL"),
            stripe_live_cancel_url=_parse_optional_url("STRIPE_LIVE_CANCEL_URL"),
            stripe_live_portal_return_url=_parse_optional_url(
                "STRIPE_LIVE_PORTAL_RETURN_URL"
            ),
            stripe_live_day_pass_product_id=(
                os.getenv("STRIPE_LIVE_DAY_PASS_PRODUCT_ID", "").strip() or None
            ),
            stripe_live_day_pass_price_id=(
                os.getenv("STRIPE_LIVE_DAY_PASS_PRICE_ID", "").strip() or None
            ),
            stripe_live_day_pass_pricing_version=(
                os.getenv("STRIPE_LIVE_DAY_PASS_PRICING_VERSION", "DAY_PASS_V1").strip()
                or "DAY_PASS_V1"
            ),
            stripe_live_monthly_product_id=(
                os.getenv("STRIPE_LIVE_MONTHLY_PRODUCT_ID", "").strip() or None
            ),
            stripe_live_monthly_price_id=(
                os.getenv("STRIPE_LIVE_MONTHLY_PRICE_ID", "").strip() or None
            ),
            stripe_live_monthly_pricing_version=(
                os.getenv("STRIPE_LIVE_MONTHLY_PRICING_VERSION", "MONTHLY_V1").strip()
                or "MONTHLY_V1"
            ),
            stripe_live_webhook_relay_url=_parse_optional_url(
                "STRIPE_LIVE_WEBHOOK_RELAY_URL"
            ),
            stripe_live_webhook_relay_secret=os.getenv(
                "STRIPE_LIVE_WEBHOOK_RELAY_SECRET", ""
            ).strip(),
            stripe_live_webhook_relay_poll_seconds=_parse_positive_int(
                "STRIPE_LIVE_WEBHOOK_RELAY_POLL_SECONDS", 5
            ),
        )

    def require_token(self) -> str:
        if not self.discord_bot_token:
            raise ConfigurationError(
                "缺少 DISCORD_BOT_TOKEN。请只把 Token 填入本地 .env，勿发送到聊天或提交 Git。"
            )
        return self.discord_bot_token

    def require_database_url(self) -> str:
        if not self.database_url:
            raise ConfigurationError(
                "缺少 DATABASE_URL。请只在本地 .env 或 Secret Manager 中配置数据库连接。"
            )
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ConfigurationError("DATABASE_URL 必须使用 postgresql+asyncpg://。")
        return self.database_url

    def require_openai_api_key(self) -> str:
        if self.llm_provider != "openai":
            raise ConfigurationError("LLM_PROVIDER 目前只支持 openai。")
        if not self.openai_api_key:
            raise ConfigurationError(
                "缺少 OPENAI_API_KEY。请只在本地 .env 或 Secret Manager 中配置。"
            )
        return self.openai_api_key

    def assert_apply_gate(self, confirmed_guild_id: int | None) -> None:
        if not self.apply_changes:
            raise ConfigurationError("写入已阻止：.env 中 APPLY_CHANGES 不是 true。")
        if self.dry_run:
            raise ConfigurationError("写入已阻止：.env 中 DRY_RUN 仍为 true。")
        if confirmed_guild_id != self.discord_guild_id:
            raise ConfigurationError(
                "写入已阻止：--confirm-guild-id 必须与 DISCORD_GUILD_ID 完全一致。"
            )

    def assert_lab_disabled(self) -> None:
        if self.lab_enabled or self.model_ab_enabled or self.moomoo_enabled:
            raise ConfigurationError(
                "当前规格禁止启动 AXIS LAB / Model A-B / Moomoo；请将三个开关保持 false。"
            )

    def stripe_config(self) -> StripeConfig:
        def environment(mode: StripeMode) -> StripeEnvironmentConfig:
            prefix = "stripe_live" if mode is StripeMode.LIVE else "stripe_test"
            return StripeEnvironmentConfig(
                mode=mode,
                secret_key=getattr(self, f"{prefix}_secret_key"),
                publishable_key=getattr(self, f"{prefix}_publishable_key"),
                webhook_secret=getattr(self, f"{prefix}_webhook_secret"),
                webhook_url=getattr(self, f"{prefix}_webhook_url"),
                success_url=getattr(self, f"{prefix}_success_url"),
                cancel_url=getattr(self, f"{prefix}_cancel_url"),
                portal_return_url=getattr(self, f"{prefix}_portal_return_url"),
                day_pass_product_id=getattr(self, f"{prefix}_day_pass_product_id"),
                day_pass_price_id=getattr(self, f"{prefix}_day_pass_price_id"),
                day_pass_pricing_version=getattr(
                    self, f"{prefix}_day_pass_pricing_version"
                ),
                monthly_product_id=getattr(self, f"{prefix}_monthly_product_id"),
                monthly_price_id=getattr(self, f"{prefix}_monthly_price_id"),
                monthly_pricing_version=getattr(
                    self, f"{prefix}_monthly_pricing_version"
                ),
            )

        return StripeConfig(
            enabled=self.stripe_enabled,
            payments_enabled=self.payments_enabled,
            mode=self.stripe_mode,
            test=environment(StripeMode.TEST),
            live=environment(StripeMode.LIVE),
        )

    def stripe_configuration_ready(self) -> bool:
        return self.stripe_config().runtime_ready()
