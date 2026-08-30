from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when runtime configuration is absent or unsafe."""


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
        llm_routing_value = os.getenv(
            "LLM_ROUTING_CONFIG", "config/model_routing.yaml"
        )
        llm_prompt_value = os.getenv("LLM_PROMPT_PATH", "config/llm_trade_prompt.txt")
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
            blueprint_path=root / "config" / "discord_blueprint.yaml",
            ids_path=(root / ids_value).resolve(),
            report_path=(root / report_value).resolve(),
            attachment_storage_path=(root / attachment_value).resolve(),
            max_attachment_bytes=_parse_positive_int(
                "MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024
            ),
            llm_provider=os.getenv("LLM_PROVIDER", "openai").strip().lower(),
            openai_api_key=preferred_openai_key or legacy_openai_key,
            llm_routing_path=(root / llm_routing_value).resolve(),
            llm_default_model_override=default_model_override or None,
            llm_signal_model_override=os.getenv("LLM_SIGNAL_MODEL", "").strip() or None,
            llm_signal_repair_model_override=(
                os.getenv("LLM_SIGNAL_REPAIR_MODEL", "").strip() or None
            ),
            llm_analysis_model_override=(
                os.getenv("LLM_ANALYSIS_MODEL", "").strip() or None
            ),
            llm_analysis_rewrite_model_override=(
                os.getenv("LLM_ANALYSIS_REWRITE_MODEL", "").strip() or None
            ),
            llm_timeout_seconds=_parse_positive_int("LLM_TIMEOUT_SECONDS", 45),
            llm_max_retries=_parse_nonnegative_int("LLM_MAX_RETRIES", 2),
            llm_prompt_path=(root / llm_prompt_value).resolve(),
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
