from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url

from scripts.backup_database import _connection
from scripts.restore_database import RESTORE_CONFIRMATION

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_backup_arguments_never_contain_password() -> None:
    url = make_url("postgresql+asyncpg://axis_user:top-secret@db.example:5432/axis")

    arguments, environment = _connection(url)

    assert "top-secret" not in " ".join(arguments)
    assert arguments == [
        "--username",
        "axis_user",
        "--host",
        "db.example",
        "--port",
        "5432",
        "--dbname",
        "axis",
    ]
    assert environment["PGPASSWORD"] == "top-secret"


def test_restore_requires_a_deliberate_confirmation_phrase() -> None:
    assert RESTORE_CONFIRMATION == "RESTORE_AXIS_DATABASE"


def test_container_context_excludes_local_secrets_and_runtime_data() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert "var" in ignored
