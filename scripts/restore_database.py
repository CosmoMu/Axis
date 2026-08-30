#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import ConfigurationError, Settings  # noqa: E402
from scripts.backup_database import _connection  # noqa: E402

RESTORE_CONFIRMATION = "RESTORE_AXIS_DATABASE"


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore an AXIS PostgreSQL custom backup.")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--confirm-guild-id", type=int, required=True)
    parser.add_argument("--confirm-restore", required=True)
    args = parser.parse_args()
    backup = args.backup.expanduser().resolve()

    try:
        settings = Settings.load(PROJECT_ROOT)
        if args.confirm_guild_id != settings.discord_guild_id:
            raise ConfigurationError("Guild confirmation mismatch")
        if args.confirm_restore != RESTORE_CONFIRMATION:
            raise ConfigurationError("Restore confirmation mismatch")
        if not backup.is_file():
            raise FileNotFoundError("Backup does not exist")
        connection, environment = _connection(make_url(settings.require_database_url()))
        pg_restore = shutil.which("pg_restore")
        if not pg_restore:
            raise FileNotFoundError("pg_restore is unavailable")
        subprocess.run(
            [pg_restore, "--list", str(backup)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(
            [
                pg_restore,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                *connection,
                str(backup),
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except Exception:
        print("AXIS restore failed; connection details were omitted.", file=sys.stderr)
        return 2

    print("AXIS restore completed. Run scripts/init_database.py before starting the Bot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
