#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import ConfigurationError, Settings  # noqa: E402


def _connection(url: URL) -> tuple[list[str], dict[str, str]]:
    if not url.database or not url.username:
        raise ConfigurationError("DATABASE_URL 缺少 database 或 username。")
    arguments = ["--username", url.username]
    if url.host:
        arguments.extend(["--host", url.host])
    if url.port:
        arguments.extend(["--port", str(url.port)])
    arguments.extend(["--dbname", url.database])
    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    return arguments, environment


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_output() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "var" / "backups" / f"axis-{timestamp}.dump"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and verify an AXIS PostgreSQL backup.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = (args.output or _default_output()).expanduser().resolve()
    if output.exists():
        print("Backup stopped: output already exists.", file=sys.stderr)
        return 2

    try:
        settings = Settings.load(PROJECT_ROOT)
        connection, environment = _connection(make_url(settings.require_database_url()))
        pg_dump = shutil.which("pg_dump")
        pg_restore = shutil.which("pg_restore")
        if not pg_dump or not pg_restore:
            raise FileNotFoundError("PostgreSQL client tools are unavailable")
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(output),
                *connection,
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        os.chmod(output, 0o600)
        subprocess.run(
            [pg_restore, "--list", str(output)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        checksum = _checksum(output)
    except Exception:
        output.unlink(missing_ok=True)
        print("AXIS backup failed; connection details were omitted.", file=sys.stderr)
        return 2

    print(f"backup={output}")
    print(f"sha256={checksum}")
    print("verification=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
