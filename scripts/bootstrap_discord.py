#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
import discord  # noqa: E402

from app.bot.blueprint import BlueprintError  # noqa: E402
from app.bot.bootstrap import run_bootstrap  # noqa: E402
from app.config import ConfigurationError, Settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读盘点 AXIS Discord，并生成幂等 Bootstrap dry-run。"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="请求写入；仍需 .env 的 APPLY_CHANGES=true、DRY_RUN=false 和 Guild ID 确认。",
    )
    parser.add_argument(
        "--confirm-guild-id",
        type=int,
        help="apply 时必须再次提供与 DISCORD_GUILD_ID 相同的 Guild ID。",
    )
    parser.add_argument(
        "--allow-axis-renames",
        action="store_true",
        help="仅允许重命名 discord_ids.json 已登记的 AXIS Category 与 Channel。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        settings = Settings.load(PROJECT_ROOT)
        return asyncio.run(
            run_bootstrap(
                settings,
                apply=args.apply,
                confirmed_guild_id=args.confirm_guild_id,
                allow_axis_renames=args.allow_axis_renames,
            )
        )
    except discord.LoginFailure:
        print("Discord 登录失败。请检查本地 .env 中的 Token；Token 未被输出。", file=sys.stderr)
    except (ConfigurationError, BlueprintError) as exc:
        print(f"Bootstrap 已停止：{exc}", file=sys.stderr)
    except discord.Forbidden:
        print("Discord 拒绝请求：Bot 缺少读取或 Bootstrap 权限。", file=sys.stderr)
    except discord.HTTPException as exc:
        print(f"Discord API 请求失败（HTTP {exc.status}）；响应正文未写入日志。", file=sys.stderr)
    except aiohttp.ClientError:
        print("连接 Discord API 失败；网络错误详情未写入日志，服务器未发生修改。", file=sys.stderr)
    except TimeoutError:
        print("连接 Discord 超时；服务器未发生修改。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
