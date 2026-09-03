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

当前 revision `20260903_0029`。0019–0022 增加 LOTTO、Short-Term policy/history、expiry trace
与 Daily Results Review；0023–0028 增加 Stripe 环境隔离、永久 Approval / Newcomer Gate 和会员
欢迎状态；0029 增加明确的 Swing `tracking_mode` 与独立 Simple Swing tracking/event/snapshot
表，并将迁移前 Swing 回填为 `LEGACY_SWING`：

```text
guild_config
input_code_counters
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
membership_sessions
membership_prices
membership_acknowledgements
membership_entitlements
membership_trials
payment_events
payment_webhook_events
system_alerts
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
daily_results_publications
daily_results_reviews
daily_results_items
swing_tracking
swing_tracking_events
swing_daily_snapshots
```

交易持仓以 `position_eighths` 保存，数据库约束范围为 `0..8`；事件增减范围为 `-8..8`。
Simple Tracked Swing 固定使用 0 仓位单位；`tracking_mode` 防止 Legacy Swing 被新 tracker 接管。
管理员写操作所需的 actor、before/after JSON 与 Discord Interaction ID 由 `audit_logs` 保存。
`llm_invocations` 保存实际 provider、model、workload、Prompt/Schema version、latency、
success 与 error_type；旧调用无法证明的字段不会伪造回填。
`trade_publications` 保存发布 claim/retry/finalize 状态；`trades` 保存官方 Results Message ID
和加权最终收益，避免重复发布。
Analysis 使用独立的 Draft、Revision、不可变 Mentor Analysis、child records 与 Publication，
不会复用或更新 Trade Domain；`source_messages.source_kind` 隔离两个处理队列。
`analysis_drafts.normalized_mentor_json`、`market_context_json`、`normalized_json` 分别保存
Mentor View、Stock Analyst Snapshot 与 Final Fused Analysis；`conflicts_json` 保存字段冲突。
归档层另存 Raw Source、以上三层和 Public Snapshot。`analysis_key_levels`、
`analysis_indicators` 使用 `MENTOR_INPUT` / `STOCK_ANALYST` provenance；
`analysis_scenarios` 保留后台多情景，`analysis_prediction_points` 保存公开单一路径的同源数据。
Chart storage/checksum 与 render error 支持确定性 PNG 的发布、失败降级和重试。
`input_code_counters` 在同一数据库事务内分别分配 Signal `S-00001` 与 Analysis `A-00001`
形式的 Manager-facing 顺序号；UUID 仍是内部主键。
`market_quote_snapshots` 保存 Moomoo 只读盘后参考价；`daily_summary_publications` 以
Guild、类别与交易日唯一，保存公开快照和 Discord 发布状态。
`daily_results_reviews` 以 Guild、交易日唯一保存 Draft / Final Snapshot、计划和实际发布时间、
Review / Public Message ID；`daily_results_items` 保存每笔 Eligible Trade 的公开展示、Include /
Exclude、原因与纠错值。Exclude 不级联删除或修改 `trades`、`trade_events` 或 tracking 历史。
`membership_sessions` 在进入动态 Checkout 前绑定 `discord_user_id`；0015 的价格目录、带版本
风险确认、终身一次 Trial、独立 Entitlement 和最小 Payment Event 记录支撑 Stripe 会员。
`payment_events` 按 provider event ID 幂等处理且不保存完整 Payload；旧
`payment_webhook_events` 仅保留兼容。`system_alerts` 保存持续故障的去重、计数和恢复状态。

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
