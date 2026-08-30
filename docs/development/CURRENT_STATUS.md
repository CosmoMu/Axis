# AXIS Current Development Status

**更新：** 2026-08-30

**Database:** `20260830_0011`

**Discord Bootstrap:** `REUSE=27 / CREATE=0 / UPDATE=0 / BLOCK=0`

**AXIS LAB:** DEFERRED

**Core Gate A:** PASS

## Stage 1 — Infrastructure: PARTIAL

Implemented:

- Python 3.12 / discord.py / SQLAlchemy / Alembic / PostgreSQL。
- Secret-only configuration、safe LaunchAgent deployment。
- Discord inventory、dry-run、三重 Apply Gate、saved-ID reconciliation。
- 20 个 v2 Channel、Manager / Member Role 与权限；包含 Manager-only
  `🧪・card-testing`。
- Workload Model Router 和 LLM invocation trace schema。
- Persistent Card Review Views。

Missing:

- Docker / production deployment target。
- 完整 backup / restore 自动化。

Tests: Router、Bootstrap、DB metadata 和安全约束已覆盖。

## Stage 2 — Signal Pipeline: COMPLETE

Implemented:

- Text / PNG / JPEG / WEBP / multi-image intake。
- 安全附件落盘、checksum 与幂等 Source Message。
- OpenAI Responses API、Structured Output、`SIGNAL_PARSE` routing。
- Draft、默认仓位阶梯、missing fields、failure Draft。
- Card Review、Mentor/Trade 选择、编辑、Public Preview、并发版本与审计。
- LLM provider/model/workload/Prompt/Schema/latency/result trace。
- 确认后创建或更新 Trade，并写入不可重复的 Trade Event。
- 数据库预约、Discord marker 恢复和事务 finalize 组成的幂等会员卡片发布。
- Public DTO 白名单边界与固定 `axis:active:*:v1` persistent button。
- `查看当前订单` ephemeral Active View；关闭、清仓和 Cancel 订单自动排除。

Needs migration: none after `0005`。

## Stage 3 — Mentor / Member / Results: COMPLETE

Implemented:

- Mentor create / rename / aliases / deactivate / reactivate / Trade reassign。
- Mentor 与 Member 长期控制面板，Message ID 入库并重启复用。
- Member lookup / gift / extend / cancel-at-expiry / immediate remove。
- 7 / 30 / 90 / Lifetime / Custom duration。
- Owner 手工 Member Role add/remove 与数据库双向同步。
- Scheduled Job 到期、Role reconciliation 和完整 Membership Event/Audit。
- 基于全部 position event 的 weighted Results 与幂等官方发布。

## Stage 4 — Analysis Pipeline: COMPLETE / LIVE ENABLED

Implemented:

- `analysis-input` 与 Signal 完全隔离的 Source queue。
- `ANALYSIS_PARSE` / `ANALYSIS_REWRITE`，支持 text / image / multi-image。
- MARKET / TICKER / SECTOR / MACRO、stance、horizon 与 no-invention prompt。
- 独立 Draft / Revision / Mentor Analysis / children / Publication 表。
- Mentor selection、edit、rewrite、archive-only、archive + publish、delete。
- Raw / Normalized / Public Snapshot 与模型、Prompt、Schema revision trace。
- Member Lounge 无 Thread 的 Public Card 白名单。
- Discord send failure 保留归档并支持 persistent retry。
- 单 ticker 合并 AXIS Stock Analyst 文字结构数据；输入路线/点位转为“预测路径（文字）”。
  引擎失败时只保留 LLM 对 input 的忠实整理，不阻塞草稿。当前不生成或发布 Analysis 图片，
  后续 Massive API 从 provider/renderer 接点扩展。
- Manager-facing 草稿编号改为 Signal `S-00001` / Analysis `A-00001` 独立顺序号。
- `why_now`、输入/引擎点位来源与引擎观察单独归档，供未来 Model A 训练。
- AXIS GEX Explorer 纯计算引擎已内置，默认不建频道、不自动发布。
- Automated Gate B：PASS。

Live activation: Owner 已单独授权 `analysis-input` 文字和图片发送到 OpenAI；
`FEATURE_ANALYSIS_ENABLED=true`、`FEATURE_AXIS_STOCK_ANALYST_ENABLED=true`。Source 原图仅作为
内部解析证据；审核和发布只发文字卡。最终 Discord dry-run 为
`REUSE=27 / CREATE=0 / UPDATE=0 / BLOCK=0`，服务器修改为 0。

## Stage 5 — Stabilization: PARTIAL

Implemented: LaunchAgent、错误信息脱敏、基础重试、测试、Secret scan、只读 DB health check、
verified custom-format backup、双确认 restore 工具、Dockerfile / Compose 基础部署、Moomoo
OpenD 只读期权快照，以及三个会员频道 `16:15 ET` 的 Active / 当日 Closed 幂等总结。

Live activation: `FEATURE_MOOMOO_ENABLED=true`、`FEATURE_DAILY_SUMMARY_ENABLED=true`；
0008 已部署。周末/假日由 SPY session anchor 验证后跳过；当前 2026-08-29 为周六，所以没有
制造 Discord 测试总结。

Missing: off-host backup target、生产监控告警、
非生产环境完整 restore / rollback rehearsal。

## AXIS LAB — DEFERRED

频道已创建且 Owner-only。以下功能保持关闭且未实现：

- Model A / B
- Moomoo 模型扫描、账户/持仓/订单与交易接口
- Generate / Shadow / Champion / Challenger
- 自动交易
