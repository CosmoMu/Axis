#!/usr/bin/env python3
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

LABEL = "com.axis.bot"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path.home() / "Library" / "Application Support" / "AXIS"


def _deploy_runtime() -> None:
    source_env = PROJECT_ROOT / ".env"
    source_ids = PROJECT_ROOT / "config" / "discord_ids.json"
    if not source_env.is_file() or not source_ids.is_file():
        raise FileNotFoundError("runtime configuration is missing")

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        PROJECT_ROOT / "app",
        RUNTIME_ROOT / "app",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (RUNTIME_ROOT / "app/integrations/cosmos_stock_analyst.py").unlink(missing_ok=True)
    runtime_venv = RUNTIME_ROOT / ".venv"
    source_venv = PROJECT_ROOT / ".venv"
    if not runtime_venv.exists():
        shutil.copytree(
            source_venv,
            runtime_venv,
            symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    else:
        source_sites = list((source_venv / "lib").glob("python*/site-packages"))
        runtime_sites = list((runtime_venv / "lib").glob("python*/site-packages"))
        if len(source_sites) != 1 or len(runtime_sites) != 1:
            raise FileNotFoundError("python site-packages directory is missing")
        shutil.copytree(
            source_sites[0],
            runtime_sites[0],
            dirs_exist_ok=True,
            symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    (RUNTIME_ROOT / "scripts").mkdir(parents=True, exist_ok=True)
    (RUNTIME_ROOT / "config").mkdir(parents=True, exist_ok=True)
    for filename in (
        "run_bot.py",
        "refresh_analysis_enrichment.py",
    ):
        shutil.copy2(PROJECT_ROOT / "scripts" / filename, RUNTIME_ROOT / "scripts")
    (RUNTIME_ROOT / "scripts/query_cosmos_stock_analyst.py").unlink(missing_ok=True)
    shutil.copy2(source_ids, RUNTIME_ROOT / "config" / "discord_ids.json")
    for filename in (
        "model_routing.yaml",
        "llm_trade_schema.json",
        "llm_analysis_schema.json",
        "llm_analysis_prompt.txt",
        "llm_trade_prompt.txt",
        "short_term_tracking.yaml",
        "short_term_tracking_v2.yaml",
    ):
        shutil.copy2(
            PROJECT_ROOT / "config" / filename,
            RUNTIME_ROOT / "config" / filename,
        )
    shutil.copy2(source_env, RUNTIME_ROOT / ".env")
    os.chmod(RUNTIME_ROOT / ".env", 0o600)


def main() -> int:
    source_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    source_runner = PROJECT_ROOT / "scripts" / "run_bot.py"
    if not source_python.is_file() or not source_runner.is_file():
        print("AXIS BOT service installation stopped: runtime files are missing.", file=sys.stderr)
        return 2

    try:
        _deploy_runtime()
    except OSError:
        print(
            "AXIS BOT runtime deployment failed; sensitive details were omitted.",
            file=sys.stderr,
        )
        return 2

    python = RUNTIME_ROOT / ".venv" / "bin" / "python"
    runner = RUNTIME_ROOT / "scripts" / "run_bot.py"
    log_directory = RUNTIME_ROOT / "var" / "log"
    log_directory.mkdir(parents=True, exist_ok=True)
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    target = launch_agents / f"{LABEL}.plist"
    temporary = launch_agents / f".{LABEL}.plist.tmp"

    payload = {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(runner)],
        "WorkingDirectory": str(RUNTIME_ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(log_directory / "axis-bot.stdout.log"),
        "StandardErrorPath": str(log_directory / "axis-bot.stderr.log"),
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
            "AXIS BOT service installation failed; runtime details were omitted.",
            file=sys.stderr,
        )
        return 2

    print("AXIS BOT background service is installed and started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
