#!/usr/bin/env python3
from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

LABEL = "com.axis.moomoo-opend"
DEFAULT_APP = Path("/Applications/moomoo_OpenD.app")


def main() -> int:
    app_path = DEFAULT_APP.resolve()
    if not app_path.is_dir():
        print("OpenD LaunchAgent installation stopped: application is missing.", file=sys.stderr)
        return 2

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    target = launch_agents / f"{LABEL}.plist"
    temporary = launch_agents / f".{LABEL}.plist.tmp"
    payload = {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/open", "-W", str(app_path)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ProcessType": "Interactive",
    }
    try:
        with temporary.open("wb") as output:
            plistlib.dump(payload, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    print("OpenD LaunchAgent is installed for the next macOS login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
