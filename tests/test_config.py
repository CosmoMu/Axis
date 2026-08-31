from dataclasses import replace
from pathlib import Path

import pytest

from app.config import ConfigurationError, Settings
from app.integrations.stripe_config import StripeMode


def settings(*, apply_changes: bool, dry_run: bool) -> Settings:
    root = Path("/tmp/axis-test")
    return Settings(
        project_root=root,
        discord_bot_token="not-a-real-token",
        discord_guild_id=1543309921066684567,
        discord_application_id=None,
        discord_owner_user_id=None,
        database_url="",
        apply_changes=apply_changes,
        dry_run=dry_run,
        analysis_enabled=False,
        moomoo_enabled=False,
        daily_summary_enabled=True,
        short_term_tracking_enabled=False,
        axis_stock_analyst_enabled=False,
        moomoo_host="127.0.0.1",
        moomoo_port=11111,
        daily_summary_time_et="16:15",
        massive_api_key="",
        massive_base_url="https://api.massive.com",
        short_term_tracking_config_path=root / "short_term_tracking.yaml",
        blueprint_path=root / "blueprint.yaml",
        ids_path=root / "ids.json",
        report_path=root / "report.json",
        attachment_storage_path=root / "attachments",
        max_attachment_bytes=10 * 1024 * 1024,
        llm_provider="openai",
        openai_api_key="",
        llm_routing_path=root / "model_routing.yaml",
        llm_default_model_override=None,
        llm_signal_model_override=None,
        llm_signal_repair_model_override=None,
        llm_analysis_model_override=None,
        llm_analysis_rewrite_model_override=None,
        llm_timeout_seconds=45,
        llm_max_retries=2,
        llm_prompt_path=root / "llm_trade_prompt.txt",
        llm_analysis_prompt_path=root / "llm_analysis_prompt.txt",
    )


@pytest.mark.parametrize(
    ("apply_changes", "dry_run", "confirmed_guild_id"),
    [
        (False, True, 1543309921066684567),
        (True, True, 1543309921066684567),
        (True, False, 999),
        (True, False, None),
    ],
)
def test_apply_requires_all_three_gates(
    apply_changes: bool,
    dry_run: bool,
    confirmed_guild_id: int | None,
) -> None:
    with pytest.raises(ConfigurationError):
        settings(apply_changes=apply_changes, dry_run=dry_run).assert_apply_gate(confirmed_guild_id)


def test_apply_gate_accepts_exact_confirmation_only() -> None:
    settings(apply_changes=True, dry_run=False).assert_apply_gate(1543309921066684567)


def test_database_url_is_required_and_must_use_asyncpg() -> None:
    with pytest.raises(ConfigurationError):
        settings(apply_changes=False, dry_run=True).require_database_url()

    configured = replace(
        settings(apply_changes=False, dry_run=True),
        database_url="postgresql+asyncpg://axis@localhost/axis",
    )
    assert configured.require_database_url().startswith("postgresql+asyncpg://")


def test_llm_key_is_optional_at_startup_but_required_to_enable_parser() -> None:
    unconfigured = settings(apply_changes=False, dry_run=True)
    with pytest.raises(ConfigurationError):
        unconfigured.require_openai_api_key()

    configured = replace(unconfigured, openai_api_key="test-only-placeholder")
    assert configured.require_openai_api_key() == "test-only-placeholder"


def test_daily_summary_time_requires_valid_hhmm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_GUILD_ID", "1543309921066684567")
    monkeypatch.setenv("DAILY_SUMMARY_TIME_ET", "25:00")
    with pytest.raises(ConfigurationError, match="DAILY_SUMMARY_TIME_ET"):
        Settings.load(Path("/tmp/axis-test"))

    monkeypatch.setenv("DAILY_SUMMARY_TIME_ET", "9:05")
    assert Settings.load(Path("/tmp/axis-test")).daily_summary_time_et == "09:05"


def test_soft_open_and_results_review_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_GUILD_ID", "1543309921066684567")
    monkeypatch.setenv("PRODUCTION_DATA_START_DATE", "2026-08-31")
    monkeypatch.setenv("PRODUCTION_DATA_START_TIMEZONE", "America/New_York")
    monkeypatch.setenv("DEPLOYMENT_STAGE", "SOFT_OPEN")
    monkeypatch.setenv("RESULTS_REVIEW_ENABLED", "true")
    monkeypatch.setenv("RESULTS_REVIEW_DRAFT_DELAY_MINUTES", "1")
    monkeypatch.setenv("RESULTS_FINAL_PUBLISH_TIME", "16:15")
    monkeypatch.setenv("RESULTS_TIMEZONE", "America/New_York")
    configured = Settings.load(Path("/tmp/axis-test"))
    assert configured.production_data_start_date.isoformat() == "2026-08-31"
    assert configured.production_data_start_timezone == "America/New_York"
    assert configured.deployment_stage == "SOFT_OPEN"
    assert configured.results_review_enabled is True
    assert configured.results_review_draft_delay_minutes == 1
    assert configured.results_final_publish_time == "16:15"
    assert configured.results_timezone == "America/New_York"


def test_lab_gate_requires_all_deferred_features_off() -> None:
    configured = settings(apply_changes=False, dry_run=True)
    configured.assert_lab_disabled()
    with pytest.raises(ConfigurationError, match="AXIS LAB"):
        replace(configured, moomoo_enabled=True).assert_lab_disabled()
    with pytest.raises(ConfigurationError, match="AXIS LAB"):
        replace(configured, lab_enabled=True).assert_lab_disabled()


def test_stripe_requires_complete_dynamic_checkout_configuration() -> None:
    configured = settings(apply_changes=False, dry_run=True)
    assert not configured.stripe_configuration_ready()
    ready = replace(
        configured,
        stripe_enabled=True,
        stripe_test_secret_key="sk_test_placeholder",
        stripe_test_publishable_key="pk_test_placeholder",
        stripe_test_webhook_secret="whsec_placeholder",
        stripe_test_success_url="https://axis.example/success",
        stripe_test_cancel_url="https://axis.example/cancel",
        stripe_test_portal_return_url="https://axis.example/account",
        stripe_test_day_pass_product_id="prod_axis_test",
        stripe_test_day_pass_price_id="price_day_test",
        stripe_test_monthly_product_id="prod_axis_test",
        stripe_test_monthly_price_id="price_monthly_test",
    )
    assert ready.stripe_configuration_ready()
    assert ready.stripe_config().active.mode is StripeMode.TEST

    assert not replace(
        ready, stripe_test_day_pass_product_id=None
    ).stripe_configuration_ready()


def test_stripe_live_never_falls_back_to_test_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_GUILD_ID", "1543309921066684567")
    monkeypatch.setenv("STRIPE_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_legacy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_legacy")
    loaded = Settings.load(Path("/tmp/axis-test"))
    stripe_config = loaded.stripe_config()
    assert stripe_config.mode is StripeMode.LIVE
    assert stripe_config.test.secret_key == "sk_test_legacy"
    assert stripe_config.live.secret_key == ""
    assert not stripe_config.runtime_ready()
