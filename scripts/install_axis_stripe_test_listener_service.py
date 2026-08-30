#!/usr/bin/env python3
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

LABEL = "com.axis.stripe-test-listener"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path.home() / "Library" / "Application Support" / "AXIS"


def main() -> int:
    source_env = PROJECT_ROOT / ".env"
    source_runner = PROJECT_ROOT / "scripts" / "run_stripe_test_listener.py"
    runtime_python = RUNTIME_ROOT / ".venv" / "bin" / "python"
    if not source_env.is_file() or not source_runner.is_file() or not runtime_python.is_file():
        print(
            "AXIS Stripe Test listener installation stopped: runtime files are missing.",
            file=sys.stderr,
        )
        return 2

    runtime_scripts = RUNTIME_ROOT / "scripts"
    runtime_scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_runner, runtime_scripts / source_runner.name)
    shutil.copy2(source_env, RUNTIME_ROOT / ".env")
    os.chmod(RUNTIME_ROOT / ".env", 0o600)

    log_directory = RUNTIME_ROOT / "var" / "log"
    log_directory.mkdir(parents=True, exist_ok=True)
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    target = launch_agents / f"{LABEL}.plist"
    temporary = launch_agents / f".{LABEL}.plist.tmp"
    payload = {
        "Label": LABEL,
        "ProgramArguments": [
            str(runtime_python),
            str(runtime_scripts / source_runner.name),
        ],
        "WorkingDirectory": str(RUNTIME_ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
            "STRIPE_CLI_PATH": "/usr/local/bin/stripe",
        },
        "StandardOutPath": str(log_directory / "stripe-test-listener.stdout.log"),
        "StandardErrorPath": str(log_directory / "stripe-test-listener.stderr.log"),
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

    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    bootout = subprocess.run(
        ["launchctl", "bootout", service],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if bootout.returncode == 0:
        time.sleep(0.5)
    try:
        for attempt in range(2):
            bootstrap = subprocess.run(
                ["launchctl", "bootstrap", domain, str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if bootstrap.returncode == 0:
                break
            if attempt == 0:
                time.sleep(1)
        else:
            raise subprocess.CalledProcessError(bootstrap.returncode, bootstrap.args)
        subprocess.run(
            ["launchctl", "enable", service],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(
            ["launchctl", "kickstart", "-k", service],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except subprocess.CalledProcessError:
        print(
            "AXIS Stripe Test listener service installation failed.",
            file=sys.stderr,
        )
        return 2

    print("AXIS Stripe Test listener service is installed and started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
