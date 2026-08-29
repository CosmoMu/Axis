from dataclasses import replace
from pathlib import Path

import pytest

from app.config import ConfigurationError, Settings


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
        blueprint_path=root / "blueprint.yaml",
        ids_path=root / "ids.json",
        report_path=root / "report.json",
        attachment_storage_path=root / "attachments",
        max_attachment_bytes=10 * 1024 * 1024,
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
