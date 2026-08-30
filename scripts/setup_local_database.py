#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import getpass
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncpg  # noqa: E402

DATABASE_NAME = "axis"
DATABASE_ROLE = "axis_user"


def _harden_local_auth(hba_path: Path) -> None:
    original = hba_path.read_text(encoding="utf-8")
    updated_lines: list[str] = []
    for line in original.splitlines():
        line = re.sub(
            r"^(\s*local\s+all\s+all\s+)trust(\s*(?:#.*)?)$",
            r"\1peer\2",
            line,
        )
        line = re.sub(
            r"^(\s*host\s+all\s+all\s+(?:127\.0\.0\.1/32|::1/128)\s+)"
            r"trust(\s*(?:#.*)?)$",
            r"\1scram-sha-256\2",
            line,
        )
        updated_lines.append(line)
    updated = "\n".join(updated_lines) + "\n"
    if updated == original:
        return

    temporary = hba_path.with_name(f".{hba_path.name}.axis.tmp")
    mode = hba_path.stat().st_mode & 0o777
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, hba_path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_database_url(database_url: str) -> None:
    env_path = PROJECT_ROOT / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []

    replacement = f"DATABASE_URL={database_url}"
    updated: list[str] = []
    inserted = False
    for line in lines:
        if line.startswith("DATABASE_URL="):
            if not inserted:
                updated.append(replacement)
                inserted = True
            continue
        updated.append(line)
    if not inserted:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append(replacement)

    temporary = env_path.with_name(".env.database-setup.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("\n".join(updated) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, env_path)
        os.chmod(env_path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


async def _provision() -> None:
    password = secrets.token_urlsafe(36)
    admin = await asyncpg.connect(
        user=getpass.getuser(),
        database="postgres",
        host="/tmp",
    )
    try:
        await admin.execute("SET password_encryption = 'scram-sha-256'")
        role_exists = await admin.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = $1)",
            DATABASE_ROLE,
        )
        if not role_exists:
            await admin.execute('CREATE ROLE "axis_user" LOGIN')
        password_literal = await admin.fetchval("SELECT quote_literal($1)", password)
        await admin.execute(
            'ALTER ROLE "axis_user" WITH LOGIN NOSUPERUSER NOCREATEDB '
            f"NOCREATEROLE NOREPLICATION PASSWORD {password_literal}"
        )

        database_exists = await admin.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)",
            DATABASE_NAME,
        )
        if not database_exists:
            await admin.execute('CREATE DATABASE "axis" OWNER "axis_user"')
        else:
            await admin.execute('ALTER DATABASE "axis" OWNER TO "axis_user"')

        hba_path = Path(await admin.fetchval("SHOW hba_file"))
        _harden_local_auth(hba_path)
        await admin.fetchval("SELECT pg_reload_conf()")
    finally:
        await admin.close()

    verification = await asyncpg.connect(
        user=DATABASE_ROLE,
        password=password,
        database=DATABASE_NAME,
        host="127.0.0.1",
        port=5432,
    )
    try:
        await verification.fetchval("SELECT 1")
    finally:
        await verification.close()

    encoded_password = quote(password, safe="")
    _write_database_url(
        f"postgresql+asyncpg://{DATABASE_ROLE}:{encoded_password}@127.0.0.1:5432/{DATABASE_NAME}"
    )


def main() -> int:
    try:
        asyncio.run(_provision())
    except Exception:
        print(
            "AXIS local database setup failed; credentials and connection details were omitted.",
            file=sys.stderr,
        )
        return 2
    print("AXIS local database and .env DATABASE_URL are configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
