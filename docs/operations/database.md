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

当前 revision `20260830_0009` 使用 24 张业务表：

```text
guild_config
mentors
mentor_aliases
source_messages
source_attachments
trade_drafts
trades
trade_events
trade_publications
llm_invocations
memberships
membership_events
subscriptions
audit_logs
scheduled_jobs
analysis_drafts
analysis_draft_revisions
mentor_analyses
analysis_symbols
analysis_key_levels
analysis_points
analysis_publications
market_quote_snapshots
daily_summary_publications
```

交易持仓以 `position_eighths` 保存，数据库约束范围为 `0..8`；事件增减范围为 `-8..8`。
管理员写操作所需的 actor、before/after JSON 与 Discord Interaction ID 由 `audit_logs` 保存。
`llm_invocations` 保存实际 provider、model、workload、Prompt/Schema version、latency、
success 与 error_type；旧调用无法证明的字段不会伪造回填。
`trade_publications` 保存发布 claim/retry/finalize 状态；`trades` 保存官方 Results Message ID
和加权最终收益，避免重复发布。
Analysis 使用独立的 Draft、Revision、不可变 Mentor Analysis、child records 与 Publication，
不会复用或更新 Trade Domain；`source_messages.source_kind` 隔离两个处理队列。
`analysis_drafts` 的 Cosmos context 与图片来源/storage checksum 字段让审核卡和会员卡读取
同一份已批准图片；0009 不修改已经归档的历史 Analysis snapshot。
`market_quote_snapshots` 保存 Moomoo 只读盘后参考价；`daily_summary_publications` 以
Guild、类别与交易日唯一，保存公开快照和 Discord 发布状态。

## 只读健康检查

```bash
.venv/bin/python scripts/verify_database.py
```

只输出 revision、选定业务表行数和非 Secret feature flags，不输出连接字符串。

## 备份与恢复

参见 `docs/operations/backup-restore.md`。恢复具有破坏性，必须先在非生产数据库验证备份，
并提供 Guild ID 与固定确认短语；当前生产数据库未执行恢复演练。

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
