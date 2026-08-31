# AXIS Daily Results Review Operations

## Scope

`📋・results-review` 是 Daily Performance Publication Control，不是 Trade Delete Tool。
它只决定当天哪些已停止/关闭订单显示在 `📊・results`；真实 Trade、Event、Tracking、Mentor
Dataset、内部 Performance 与 Swing / LEAPS Daily Summary 永远不因 Exclude 被删除或改写。

## Runtime Configuration

```text
RESULTS_REVIEW_ENABLED=true
RESULTS_REVIEW_DRAFT_DELAY_MINUTES=1
RESULTS_FINAL_PUBLISH_TIME=16:15
RESULTS_TIMEZONE=America/New_York
```

数据库必须在 revision `20260830_0022`，Guild Config 必须保存
`results_review_channel_id=1543767142745243731`。Secret 只从 `.env` / Secret Store 读取。

## Daily Flow

1. Bot 从 XNYS trading calendar 读取当天实际 Market Close；Early Close 不使用固定 16:00。
2. Close + 1 minute 后，生成当天唯一 `AXIS DAILY RESULTS · DRAFT`。
3. 默认 Included：当天 STOPPED Short-Term、当天 CLOSED Swing、当天 CLOSED LEAPS。
4. Active Trade 不进入 Review；Loss Trade 不自动隐藏。
5. Manager / Owner 可使用 MANAGE TRADES、EDIT CARD、PREVIEW、PUBLISH NOW。
6. 未经人工操作时，`16:15 ET` 仍自动发布所有默认 Included Items。
7. Publish Now 后 Scheduled Job 只认领已有 Public Message，不重复发送。

Short-Term 始终使用完整追踪周期内的 `highest_price` 相对 `entry_price` 重新计算公开收益，
不使用当前价、停止价或单日快照，并按订单号数字升序显示。Swing / LEAPS 显示 TP / SL
event 与最高收益。Public Card 不显示 totals、win rate、average return 或 closed count；
Short-Term Results 不显示 LOTTO 标签。

## Manager Actions

- Exclude：选择当日 item 和固定 reason；保存 actor / time / before / after，只从 Public Snapshot
  移除该行。
- Include Again：只允许发布前恢复 item，并写 Audit。
- Edit Display：只改标题、日期、Section 顺序、Trade Display Text 或 Footer，不改 Trade。
- Correct Result：Market Data Error / Wrong Quote 的独立流程，保存 original、corrected、reason、
  actor 与 time。
- Preview：只向当前 Manager / Owner 返回 ephemeral Final Card，不发送 `📊・results`。
- Publish Now：立即锁定 Final Snapshot 并发布。普通 Include / Exclude 随后锁定。
- Public Correction：发布后的独立 Audit Workflow；原始 Final Snapshot 保持不可变。

Exclusion reasons：`DUPLICATE_SIGNAL`、`DATA_QUALITY_ISSUE`、`BAD_QUOTE`、
`WRONG_CONTRACT`、`MANUAL_CORRECTION`、`NOT_FOR_PUBLIC_SUMMARY`、`OTHER`。

## Test Environment

只在 `🧪・card-testing` 运行：

```text
/test-results-review
```

该命令使用内存 synthetic DTO。MANAGE / EDIT 回报自动化覆盖状态，PREVIEW 返回 ephemeral
Final Card，PUBLISH NOW 不写数据库且不向正式 Results 发送。不得在 Production input / review /
member channels 测试 Fake Result。

## Idempotency and Recovery

- 数据库唯一键：`guild_id + trading_date`。
- Public marker：`AXIS · DAILY-RESULTS-YYYYMMDD`。
- Draft Job 重跑或 Bot restart 复用原 Review Message。
- Publish claim / finalize 分离；Discord 发送成功后数据库 finalize 前崩溃时，恢复逻辑按 marker
  认领原 Message ID。
- `final_snapshot` 是会员当天实际看到内容的不可变证据。

## Health Check

```bash
.venv/bin/python scripts/verify_database.py
.venv/bin/python scripts/verify_discord_runtime.py
launchctl print gui/$(id -u)/com.axis.bot
```

正常输出：revision `20260830_0022`、`RESULTS_REVIEW_ENABLED:true`、Discord runtime PASS、
owner test commands `13`。没有 Eligible Trade 时 review/item count 为 0 是正常状态。

第一个正式交易日验收时记录：actual close、draft time、Review Message ID、Item include state、
Final Snapshot、Public Message ID、published time 和 Scheduled Job dedup。不要把 Secret、完整
`.env` 或带签名 URL 写入记录。
