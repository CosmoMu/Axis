# AXIS Owner Operations

## Owner-only 权限

`🚨・system-alerts` 与 `🧪・card-testing` 位于 `⚙️・MANAGER`，但普通 Manager 明确
DENY VIEW。Blueprint 使用 `DISCORD_OWNER_USER_ID` 对单个 Owner 建立 overwrite，不创建
额外 Staff Role。

权限目标：

| Identity | System Alerts | Card Testing |
| --- | --- | --- |
| Public / Member | 不可见 | 不可见 |
| Manager | 不可见 | 不可见 |
| Owner | View / Send / Interact | View / Send / Interact |
| AXIS BOT | View / Send / Manage | View / Send / Manage |

只读生产验收：

```bash
.venv/bin/python scripts/verify_discord_runtime.py
```

## Card Testing

Owner 只能在 `🧪・card-testing` 使用：

```text
/test-signal-card
/test-analysis-card
/test-entry-card
/test-add-card
/test-tp-card
/test-runner-card
/test-close-card
/test-results-review
```

这些命令直接构建内存 `PublicTradeCard` / `PublicAnalysisCard` Preview DTO，不调用正式
Trade、Analysis、Publication 或 Results service，不向会员频道发送，也不写数据库。
`/test-results-review` 使用内存 TEST DTO 预览 Draft、Manager buttons 和 Final Card；它的
Publish Now 仅返回测试回执，不会发送到 `📊・results`。

## System Alerts

正常运行时频道保持安静。只发送第一条持续 `ERROR` / `WARNING`，以及恢复后的单条
`RECOVERY`。当前覆盖：

- Discord Gateway
- PostgreSQL
- OpenAI 最近调用
- Scheduled Jobs / Membership Expiry / Backup Job
- Signal Processing / Analysis Processing
- Membership Payment / Role sync
- Stripe Webhook Relay / Subscription Reconciliation；故障后的下一次成功轮询即使没有待处理
  event，也会发送一次 `RECOVERY`
- Moomoo OpenD / Quote（仅 feature enabled 时）

每个 fingerprint 按 Guild、service、error type 与 affected scope 生成，并持久化：

```text
severity
service
error_type
first_seen
last_seen
occurrence_count
resolved_at
last_notified_at
```

同一持续错误只增加 occurrence count；恢复后再次出现会开启新一轮 alert。Database 完全离线
时，Bot 先用进程内状态避免刷屏；数据库恢复后补写持续时间和次数，再发送 Recovery。

`SYSTEM_ALERT_CHECK_SECONDS` 控制健康检查间隔，默认 30 秒。不要把普通成功日志或每次
健康检查结果发送到 Discord。
