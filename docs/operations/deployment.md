# AXIS Deployment

## macOS LaunchAgent（当前本机）

```bash
./scripts/install_axis_bot_service.py
```

脚本把代码、非 Secret 配置、忽略的 Discord IDs 与权限为 `0600` 的 `.env` 部署到
`~/Library/Application Support/AXIS`，然后幂等重启 `com.axis.bot`。

部署顺序：backup → tests/lint → `init_database.py` → feature flag disabled 部署 → health
check → 授权后的 feature enable → live acceptance。

部署后执行只读 Discord 验收：

```bash
.venv/bin/python scripts/verify_discord_runtime.py
```

该脚本验证四种用户身份加 Bot 的权限、五条 GENERAL Guide Message ID 与 7 个 Owner-only
测试命令，不发送消息或修改服务器。

启用 Core Moomoo 总结时，另外安装 OpenD 登录 LaunchAgent：

```bash
.venv/bin/python scripts/install_moomoo_opend_launch_agent.py
```

该脚本只登记 `/Applications/moomoo_OpenD.app` 在下次 macOS 登录时启动，不读取任何账户
Secret，也不会启动 AXIS LAB 或交易功能。行情与每日总结操作见
`docs/operations/daily-market-summaries.md`。

## Docker 基础镜像

项目提供 `Dockerfile` 与 `compose.yaml`。`.dockerignore` 排除 `.env`、`var/`、Git 和手工
输入资料。构建镜像不包含 Secret；运行时由部署平台 Secret Store 注入环境变量。

容器启动前必须单独执行迁移：

```bash
docker compose run --rm axis-bot python scripts/init_database.py
docker compose up -d axis-bot
```

如果 PostgreSQL 位于宿主机，容器中的 `DATABASE_URL` 不能使用 `127.0.0.1`，应指向可解析
的数据库主机。生产环境还需要 TLS、只读 Secret 挂载、集中日志、健康告警和 off-host
backup。
