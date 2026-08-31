# AXIS Soft Open Reset Report — 2026-08-30

## Outcome

- Soft Open Date: `2026-08-31`
- Production timezone: `America/New_York`
- Reset Time: `2026-08-30 19:32:39 ET` (`2026-08-30 23:32:39 UTC`)
- Target Guild: `1543309921066684567`
- Result: **PASS**
- Production boundary: 2026-08-31 起真实 Signal、Trade、Event、Tracking、Analysis、Results、
  Summary 与 Historical Performance 永久保存；禁止再次全量 Reset 或重新编号。

## Backup

Reset 前完成并验证两份 Git-ignored、权限 `0600` 的本地备份：

| Backup Reference | SHA-256 | Verification |
| --- | --- | --- |
| `var/backups/axis_pre_soft_open_2026-08-30.dump` | `0cfe15eb812f8c2d3b1e1aaddb2d0acab63d47a598c06dd93fb57723113e499d` | `pg_restore --list` readable |
| `var/backups/axis_pre_soft_open_2026-08-30.tar.gz` | `59d7ba57f3c69a95c76379ca8fc2297b2e6db76bb98fa9d44382f67a4f054c1f` | archive readable |

归档范围包含 PostgreSQL、Guild Config、Discord Resource IDs、Mentor Registry、当时的 Test
Trade / Analysis / Results 和非 Secret 配置。Dump、archive、`.env` 与 Secret 均未加入 Git。

## Dry Run and Database Reset

Dry Run 在 Apply 前完成并经 Owner 确认。分类主记录与关联删除统计：

| Domain | Dry Run / Deleted |
| --- | ---: |
| Short-Term Test Trades | 2 |
| Swing Test Trades | 1 |
| LEAPS Test Trades | 3 |
| Trade Drafts | 13 |
| Trade Events | 6 |
| Trade Publications | 6 |
| Short-Term Tracking / Events | 2 / 3 |
| Analysis Drafts | 8 |
| Analysis Revisions / Mentor Analyses / Publications | 5 / 4 / 4 |
| Analysis Symbols / Levels / Points | 3 / 15 / 43 |
| Analysis Prediction Points / Scenarios / Indicators | 0 / 0 / 0 |
| Source Messages / Attachments / LLM Invocations | 22 / 8 / 25 |
| Daily Results / Daily Summary / Market Snapshots | 0 / 0 / 0 |
| Membership Sessions / Entitlements / Trials | 4 / 3 / 1 |
| Payment Events / Membership Acknowledgements | 3 / 1 |
| System Alerts / Test Audit Logs | 3 / 103 |

`mentors=1`、`guild_config=1` 与两个 Membership Price 配置被保留。Bot 重启后从真实 Discord
Member Role 幂等恢复了一个 `MANUAL_ROLE` entitlement；它不是 Fake Trial、Fake Gift 或
Stripe Test membership，因此作为真实访问状态保留。

Reset 后数据库验证：Short-Term、Swing、LEAPS、Analysis、Daily Results、Daily Summary、
Tracking、Test Payment 与 Test Alert 均为 `0`；Alembic revision 为 `20260830_0022`。

## Public Sequence Reset

| Sequence | Status |
| --- | --- |
| SHORT_TERM | PASS — 下一笔 `ST-0001` |
| SWING | PASS — 下一笔 `SW-0001` |
| LEAPS | PASS — 下一笔 `LP-0001` |
| Signal Input | PASS — 下一笔 `S-00001` |
| Analysis Input | PASS — 下一笔 `A-00001` |

最新补充规格使用了 `AN-0001` 作为条件示例；当前已锁定并已在产品中使用的 Analysis 格式是
`A-00001`，因此只把 Analysis counter 复位到 1，没有另行改变公开 ID 格式。UUID generation
未修改。Reset marker `SOFT_OPEN_RESET_APPLIED` 已写入，第二次 Apply 会被拒绝。

## Discord Message Cleanup

没有删除、重建、移动或重命名任何既有 Category、Channel 或 Role。Apply 前 21 个既有
Channel 共删除 110 条开发测试消息：

| Channel | Deleted |
| --- | ---: |
| `👋・welcome` | 1 |
| `💳・subscriptions` | 1 |
| `📊・results` | 1 |
| `💬・lobby` | 0 |
| `🏆・member-wins` | 2 |
| `⚡・short-term` | 5 |
| `〽️・swing` | 1 |
| `♾️・leaps` | 3 |
| `🛋️・member-lounge` | 0 |
| `📥・signal-input` | 39 |
| `✅・signal-review` | 14 |
| `💭・analysis-input` | 26 |
| `📝・analysis-review` | 10 |
| `🧭・mentor-control` | 1 |
| `👤・member-control` | 1 |
| `🤫・在这交流` | 1 |
| `🚨・system-alerts` | 4 |
| `🧪・card-testing` | 0 |
| `🟢・lab-signals` | 0 |
| `🧬・mentor-status` | 0 |
| `🗂️・lab-history` | 0 |
| **Total** | **110** |

逐条删除首次运行在 Discord API 时限内完成 63 条后停止；脚本以幂等批量方式安全续跑，最终
只读复核确认以上 21 个频道在 reseed 前均为 0。没有重复删除或资源漂移。

## Preserved Resources and Persistent Reseed

- Mentor Count Preserved: `1 / 1`
- Existing Channel IDs Preserved: `21 / 21`
- New Results Review Channel: `📋・results-review`，ID `1543767142745243731`
- Current Channel Count: `22`
- Category IDs Preserved: `4 / 4`
- Role IDs Preserved: `5 / 5`（含 `@everyone` 与 Discord managed Server Booster；3 个 AXIS Role）
- Permissions、channel order 与 topics: preserved；Results Review 只增加目标权限覆盖。
- Persistent Message Reseed: **PASS** — Welcome、Subscription、Results Guide、Member Wins
  Guide、Short-Term Risk Notice、Mentor Control、Member Control 共 7 条；Lobby 继续使用 topic。
- Fake Signal、Fake Analysis、Fake Result 与 Fake Trade: not seeded。
- Bot Restart Status: **PASS** — LaunchAgent running，persistent views recovered。

## Results Review Enablement

- `📋・results-review` 已由幂等 Bootstrap 只创建缺失资源；dry run `REUSE=28 / CREATE=1 /
  UPDATE=0 / BLOCK=0`，Apply 后再次盘点无漂移。
- `RESULTS_REVIEW_ENABLED=true`；真实收盘后 1 分钟生成 Draft，最终公开时间 `16:15 ET`。
- Include / Exclude / Re-Include、Exclusion Reason、Display Edit、Correct Result、Preview、
  Publish Now、Scheduled Publish、Final Snapshot 与 Public Correction Audit 已实现。
- Exclude 只影响当天公开 Results，不删除或修改 Trade、Event、Tracking、Mentor Dataset、内部
  Performance 或 Swing / LEAPS Daily Summary。
- `/test-results-review` 已同步到目标 Guild；使用内存 TEST DTO，不写 Production 数据，也不
  向 `📊・results` 发布。

## Verification

- Full pytest: **198 passed / 0 failed / 0 skipped**
- Ruff: **PASS**
- Python compileall: **PASS**
- Database verifier: **PASS** — revision `20260830_0022`
- Discord runtime verifier: **PASS** — public/member/manager/owner/bot permissions，persistent
  guides idempotent，13 Owner test commands
- Bot connect / persistent views / Mentor Control / Member Control / input pipelines / tracking
  loop / Daily Results job / Swing Summary / LEAPS Summary: **READY**

## Warnings

- Short-Term / Massive 真实 quote、TP、Protection、Overnight 与重启 E2E 仍未验收。
- 第一个带 Eligible Production Trade 的 `16:15 ET` Daily Results 公开发布尚待真实交易日验收。
- Pre-Soft-Open backup 当前只有本地副本；off-host backup 与完整 restore rehearsal 仍待完成。
- Soft Open 不代表整个 Stripe 已进入 Live；Stripe 仍是 Test Mode / Live Pending。
