# AXIS 数据库操作说明

AXIS 使用 PostgreSQL、SQLAlchemy 2 async、asyncpg 和 Alembic。数据库凭据只能存在于
本机 `.env` 或部署环境的 Secret Manager，不得写入 `alembic.ini`、源码、日志或 Git。

## 配置

在本机 `.env` 中配置：

```text
DATABASE_URL=postgresql+asyncpg://axis_user:<password>@localhost:5432/axis
```

生产环境必须使用独立用户、强密码、TLS 和最小权限。示例中的 `<password>` 不是实际凭据。

本机首次开发可以在 PostgreSQL 服务启动后执行：

```bash
.venv/bin/python scripts/setup_local_database.py
```

该脚本会幂等创建本机 `axis_user` 与 `axis` 数据库、生成强随机密码、验证实际连接，并只把
编码后的 `DATABASE_URL` 写入 Git 忽略的 `.env`。它还会把本机 Unix Socket 认证收紧为
`peer`、TCP 回环认证收紧为 `SCRAM-SHA-256`，避免 Homebrew 初始 `trust` 配置绕过密码。
脚本不会输出密码或连接字符串。它只适用于本机开发；生产环境应使用托管 Secret Manager
和单独的生产凭据。

## 初始化或升级

```bash
.venv/bin/python scripts/init_database.py
```

该命令会：

1. 执行 `alembic upgrade head`；
2. 从本机忽略文件 `config/discord_ids.json` 读取目标 Guild 的 Role 与 Channel ID；
3. 幂等创建或更新 `guild_config`；
4. 保留控制面板 Message ID，后续创建面板时写入，防止重复面板。

迁移失败时不会打印 `DATABASE_URL`。未配置数据库连接时，脚本会安全停止。

## Schema

初版迁移创建 14 张表：

```text
guild_config
mentors
mentor_aliases
source_messages
source_attachments
trade_drafts
trades
trade_events
public_messages
memberships
membership_events
subscriptions
audit_logs
scheduled_jobs
```

交易持仓以 `position_eighths` 保存，数据库约束范围为 `0..8`；事件增减范围为 `-8..8`。
管理员写操作所需的 actor、before/after JSON 与 Discord Interaction ID 由 `audit_logs` 保存。

## 查看版本

```bash
.venv/bin/alembic current
.venv/bin/alembic history
```

## 回滚

生产环境回滚前必须先备份并审阅迁移。开发环境可回滚一个版本：

```bash
.venv/bin/alembic downgrade -1
```

不要在生产环境直接执行 `downgrade base`。
