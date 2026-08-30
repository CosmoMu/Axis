# AXIS Current Development Status

**更新：** 2026-08-30

**Database:** `20260830_0018`

**Discord Bootstrap:** `REUSE=28 / CREATE=0 / UPDATE=0 / BLOCK=0`

**AXIS LAB:** DEFERRED

**Core Gate A:** PASS

## Stage 1 — Infrastructure: COMPLETE FOR CURRENT LOCAL DEPLOYMENT

Implemented:

- Python 3.12 / discord.py / SQLAlchemy / Alembic / PostgreSQL。
- Secret-only configuration、safe LaunchAgent deployment。
- Discord inventory、dry-run、三重 Apply Gate、saved-ID reconciliation。
- 21 个 v2 Channel、Manager / Member Role 与权限。
- `🚨・system-alerts` 与 `🧪・card-testing` 使用 Owner user-specific overwrite；Manager 不可见。
- Workload Model Router 和 LLM invocation trace schema。
- Persistent Signal Review Views。

Deferred operations: 托管生产目标、off-host backup 与 restore rehearsal。

Tests: Router、Bootstrap、DB metadata 和安全约束已覆盖。

## Stage 2 — Signal Pipeline: COMPLETE

Implemented:

- Text / PNG / JPEG / WEBP / multi-image intake。
- 安全附件落盘、checksum 与幂等 Source Message。
- OpenAI Responses API、Structured Output、`SIGNAL_PARSE` routing。
- Draft、默认仓位阶梯、missing fields、failure Draft。
- Signal Review、AI Category 默认值/Manager 下拉修正、Mentor/Trade 选择、编辑、
  Public Preview、并发版本与审计。
- LLM provider/model/workload/Prompt/Schema/latency/result trace。
- 确认后创建或更新 Trade，并写入不可重复的 Trade Event。
- 数据库预约、Discord marker 恢复和事务 finalize 组成的幂等会员卡片发布。
- Public DTO 白名单边界与固定 `axis:active:*:v1` persistent button。
- `查看当前订单` ephemeral Active View；关闭、清仓和 Cancel 订单自动排除。

Needs migration: none after `20260830_0018`。

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
- Analysis 使用中性 AXIS 编辑口吻，公开层清理第一人称、作者归因与图片引用。
- 独立 Draft / Revision / Mentor Analysis / children / Publication 表。
- Mentor selection、edit、rewrite、archive-only、archive + publish、delete。
- Raw / Normalized / Public Snapshot 与模型、Prompt、Schema revision trace。
- Member Lounge 无 Thread 的 Public Card 白名单。
- Discord send failure 保留归档并支持 persistent retry。
- 单 ticker 使用 Mentor-first / AXIS-fill-missing 字段级融合；点位与指标保存来源和冲突。
  后台保留 2–3 个 Scenario，公开只显示通过 50% / 10% 优势门槛的 Top Scenario。
- 单一路径使用确定性 renderer 生成 PNG；不画未来 K 线，失败不阻塞归档并可重试。
- Manager-facing 草稿编号改为 Signal `S-00001` / Analysis `A-00001` 独立顺序号。
- Raw / Mentor / Stock Analyst / Final Fused / Public Snapshot 与字段级 provenance 单独归档，
  供未来 Model A 训练。
- AXIS GEX Explorer 纯计算引擎已内置，默认不建频道、不自动发布。
- Automated Gate B：PASS。

Live activation: Owner 已单独授权 `analysis-input` 文字和图片发送到 OpenAI；
`FEATURE_ANALYSIS_ENABLED=true`、`FEATURE_AXIS_STOCK_ANALYST_ENABLED=true`。Source 原图仅作为
内部解析证据；审核和发布只发文字卡。Analysis 既有频道和处理逻辑在本轮保持不变。

## Stage 5 — GENERAL / Membership / Monitoring: TEST ACTIVE, STRIPE LIVE GATED

Implemented:

- 极简 Welcome、三方案 Membership、Results 与 Member Wins；Lobby 只保留英文 Topic。
- Free Trial、Day Pass、Monthly、Gift、Manual 与 Manual Extension 独立 Entitlement。
- XNYS 正式交易日历、风险声明版本、Trial 终身一次和多 Entitlement Role Sync。
- Stripe 动态 Checkout、签名 Webhook、动态 Portal、event dedup 与价格快照/Grandfathering。
- 9 个 Owner-only Preview Command；新增 General 与 Payment UI Preview。
- Database / OpenAI / Jobs / Membership Expiry / Signal / Analysis / Discord / Moomoo 监控。
- System Alert 持久化去重，只发送首个 ERROR/WARNING 与一次 RECOVERY。

Activation boundary:

- Stripe Test Product、Day Pass/Monthly Price、Test Secret、Price IDs 与本地五事件 CLI webhook
  已配置；Test Checkout 已启用，Live Mode 仍关闭。
- Day Pass 与 Monthly Test 付款、乱序 invoice replay、Entitlement 和 Member Role E2E 已通过；
  `axis-brand-lockup.png` 已上传到 Test Product。
- 公开 TLS webhook、续费/失败/取消完整 E2E、商家法律资料和人工隐私检查尚未完成，不得进入
  Live Mode。
- 完成 `LIVE_MODE_CHECKLIST.md` 和 `STRIPE_PUBLIC_PRIVACY_CHECKLIST.md` 后才可启用。

## Stage 6 — Stabilization: PARTIAL

Implemented: LaunchAgent、错误信息脱敏、基础重试、测试、Secret scan、只读 DB health check、
verified custom-format backup、双确认 restore 工具、Dockerfile / Compose 基础部署、Moomoo
OpenD 只读期权快照，以及三个会员频道 `16:15 ET` 的 Active / 当日 Closed 幂等总结。

本轮最新范围要求 `FEATURE_MOOMOO_ENABLED=false`；旧每日总结代码保留但不启动，不属于
AXIS LAB 开发。

Missing: off-host backup target、非生产环境完整 restore / rollback rehearsal。

## AXIS LAB — DEFERRED

频道结构保持原状且功能关闭。以下功能保持未实现：

- Model A / B
- Moomoo 模型扫描、账户/持仓/订单与交易接口
- Generate / Shadow / Champion / Challenger
- 自动交易
