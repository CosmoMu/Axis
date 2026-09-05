# AXIS Next Steps

**Updated:** 2026-09-05

当前只做 Production live validation 和 Core 稳定化。优先级固定如下，不插入 AXIS LAB 或
新的产品功能。

## Production Data Lock

Soft Open Day 1 清单仍用于核心回归证据，但 Stripe 双环境基础工作已在独立边界内完成，未修改
Signal System。当前不新增功能；只执行下面固定 Priority 的真实验收、外部配置和稳定化。

Soft Open Reset 已完成。`2026-08-31` 起真实输入均为永久 Production Data；后续验证不得
wipe、truncate、重新编号或用 Production 频道生成 Fake 数据。Synthetic Preview 只走
`🧪・card-testing`。

## Current Gate — Stock Analyst Phase 1

- 保持 `STOCK_ANALYST_MODE=TEST`，只允许 Owner 在 `🧪・card-testing` 运行 `/stock`。
- 用真实 Discord Desktop / Mobile 对 SPY、QQQ、NVDA、TSLA、AAPL、META、PLTR、AMD 做最终
  图卡可读性抽检，并在开盘时验证 live/stale 标记。
- 当前 Test Gate PASS 后立即停止；没有新的明确 Owner 指令，不切换 Member Lounge、不增加普通
  文本触发、不自动扫描、不生成 Signal，也不连接 Moomoo。
- 如进入 Phase 2，必须单独设计/批准 Member role、exact channel、限流容量、运营 runbook 与
  rollback；不得仅改变 `.env` 绕过现有启动门。

## Current Gate — GEX Explorer Member Lounge Launch

- 当前保持 `GEX_EXPLORER_MODE=TEST`。新欢迎语与冷却规则代码已完成；收到精确批准
  `APPROVE GEX LOUNGE LAUNCH` 后才可部署为 `MEMBER_LOUNGE`。
- 上线后观察 SPY / QQQ / NVDA / TSLA / AAPL、普通会员 30 秒个人冷却、同 ticker 60 秒冷却、
  管理员豁免、provider limit、stale/closed label 与失败/恢复卡片。
- 当前 Massive entitlement 无法生成真实 SPX surface；不得映射 SPY，等待 Provider entitlement
  或原生 SPX data source。
- 记录真实会员请求的 latency、Massive entitlement 与移动端可读性；异常时使用独立 kill switch
  回退为 TEST，不影响 Signal / Tracking / Membership。

## Priority 0 — Owner Personal Moomoo Execution DRY_RUN E2E

Work:

- 启动并登录本机 OpenD，明确选择唯一 US securities account 和 security firm；先运行只读 verifier。
- 在 SIMULATE 完成 Owner-authored Short-Term / Swing Entry、broker ACK/fill reconciliation、TTL、
  duplicate/chase/liquidity blocks、manual add/partial/full close 与 linked Swing Close。
- 验证 +30 breakeven、+50 TP/trailing、runner、09:30–09:35 opening guard、restart idempotency、
  System Alert recovery、private daily summary 和 Desktop/Mobile control UX。
- 记录 blocker 清单。只有全部解除并由 Owner 单独决定后，才允许设置 DRY_RUN accepted gate；本轮
  不切 LIVE。

Exit criteria:

- verifier 对 account / positions / orders / fills 为 PASS，且输出只包含 masked account reference。
- DRY_RUN 没有任何 broker write 或 fake fill；SIMULATE lifecycle 与数据库/Discord 审计一致。
- kill switches、public-signal independence 与 member-account isolation 有实际证据。

## Priority 0A — Simple Tracked Swing Live E2E

Work:

- 用下一笔真实新 Swing 验证 minimal review 不出现 Mentor、Position、ADD、SL、Runner 或图表。
- 核对 `SIMPLE_TRACKED_SWING`、SW ID、真实 Massive quote、High/Low Watermark 和冻结 policy。
- 触发至少一个 shared fixed TP，确认编号来自 Short-Term policy 且重启不重复。
- 分别验证 `close SW-XXXX` 和完整合约 matching；确认 Manager Review 后才停止追踪，报价失败时
  仍能安全 Close，Close Reference 不替代 lifetime highest return。
- 检查 Active View forced refresh/stale fallback、EOD Active Summary、终止当日 Results、单条合并
  public results，以及 expiry/restart recovery。
- 确认四笔 Active `LEGACY_SWING` 继续原 Mentor/Position UI 和旧事件引擎，LEAPS/Short-Term 无变化。

Exit criteria:

- Discord message、trade/tracking/event/snapshot/result 数据一致且没有重复 TP 或公开 Results。
- Active Simple Swing 不进入 Results；Close/Expiry 当日结果等于冻结 lifetime verified high。
- Legacy Swing 没有被注册到 Simple tracker，生产历史未删除、重编号或改写。

## Priority 0B — Newcomer Gate Live E2E

Work:

- 用一个真实、从未获批的 Discord 测试账户完成 Join → Newcomer → Apply → Manager Review。
- 在 Desktop / Mobile 实测该账户只能看到 welcome、results、member-wins，且三处均不能发言。
- APPROVE 后核对 Newcomer 移除、Member 添加、Trial 为 3 个 XNYS Trading Days。
- 使用受控时钟/短期验收环境验证 Trial expiry 只移除 Member、不重新添加 Newcomer；随后 leave /
  rejoin 不重复 Application 或 Trial。
- 验证一个 never-approved / rejected 账户 rejoin 后仍是 Newcomer，并核对风险告警去重、Role
  reconciliation 和 NEWCOMER SECURITY health。

Exit criteria:

- 真实 Discord 权限、Application、Review、Trial、Expiry、Rejoin 和 checkout fail-closed 均有证据。
- `membership_trials` 永久历史和 database unique constraint 阻止第二次 Trial。

## Priority 1 — Short-Term + Massive Real E2E

Work:

- 从下一笔正式 ST-0001 开始验证发布后 tracking 注册与真实 Massive quote。
- 验证 Massive MarketTrackingService 的真实 option quote、symbol、price source 和 timestamp。
- 验证 High / Low Watermark 与新订单固定 TP1–TP41；确认 50% 起每 25 个百分点只发送
  一次且没有 Runner。
- 验证 ST_TRACKING_V2 / V3 在途订单与 ST_TRACKING_V4 新订单各自使用冻结策略，不混用点位。
- 验证 Fast Momentum Reversal、Overnight Tracking 和 Expiry-only Tracking。
- 核对 Discord Entry / TP、Daily Results 和数据库完整历史，并确认任何回撤都不发送 SL、
  到期也不向 Short-Term 频道发卡。
- 重启 Bot，确认 tracking 恢复且 event / publication 不重复。
- 在存在 Eligible stopped / active / closed trade 时，验证收盘后 `📋・results-review` Draft、默认
  Include、Manager Review 与 `16:15 ET` 单次公开发布；保留数据库与 Discord 证据。

Exit criteria:

- 数据库存在对应 tracking、真实 quote timestamp 和幂等 event。
- Discord 消息与数据库一致，重启前后没有重复 milestone。
- Massive 故障和恢复产生可操作的去重告警。
- Daily Results Review / Public Message 不重复，Exclude 不删除真实历史。

## Priority 2 — Short-Term Discord Desktop / Mobile UX Validation

Work:

- 在 Desktop 和 Mobile 检查 simplified review、LOTTO、发布、TP、protection、停止追踪与
  Daily Results；确认 Short-Term 没有 Active Button 或 Daily Summary。
- 检查 Swing / LEAPS「查看当前持仓订单」和 Daily Summary。
- 确认 Short-Term 不出现 Mentor 或 Swing / LEAPS Mentor Trade Flow。
- 验证只允许 Bot 发言的会员频道权限和 Manager 操作入口。
- 验证发布后 Review 保留最终状态，不误删正常 Bot 卡片。

Exit criteria:

- Manager 不需要反复滚动即可完成审核。
- 会员内容不泄露 Mentor、Source、Market、Bid、Ask、Parser 或内部 ID。

## Priority 3 — Stripe Live First Payment & Lifecycle Acceptance

Work:

- Live activation、KYC、payout、Product/Prices、Customer Portal、`axisdesk.fyi` webhook、顾客展示
  资料和 0-blocker readiness 已完成，`PAYMENTS_ENABLED=true`。
- Owner 从 Discord 完成第一笔真实 Day Pass 或 Monthly 付款，记录 Checkout、签名 webhook、
  Entitlement 与 Member Role 证据。
- 验证 Day Pass 到期以及 Monthly renewal、failure/recovery、payment-method update 和 cancellation。
- 验证 Customer Portal、Price Grandfathering、重复/乱序事件和公开隐私清单。
- 轮换 2026-08-31 审计中暴露的 Test secret key，再继续 Test 外部调用。

Exit criteria:

- Owner 自行完成第一笔真实付款与 lifecycle 验收；不得由自动化制造 Live 假付款。
- Stripe / AXIS / Discord 对账 clean，失败路径可恢复且不重复授权。

## Priority 4 — Real Mentor Analysis Fusion / Prediction Chart UX Validation

Work:

- 选择 2–3 个不同完整度的真实 Mentor input。
- 对比 Raw、Mentor、Stock Analyst、Final Fused 和 Public Snapshot。
- 核对 why-now、关键点位、indicator provenance、conflict、warnings 和 Top Scenario。
- 在 Desktop / Mobile 验证 Prediction Chart、下拉、编辑、重写、重新生成图片、归档和发布。

Exit criteria:

- Mentor-first / AXIS-fill-missing 行为可追溯，AXIS 不覆盖 Mentor 已给出的内容。
- 公开卡片和图表一致；renderer 失败时文字归档仍可完成。

## Priority 5 — Off-host Backup + Restore / Failure Rehearsal

Work:

- 配置加密 off-host backup、保留策略和失败告警。
- 在非生产环境完成完整 restore、数据核对与 rollback rehearsal。
- 演练 Database、OpenAI、Discord、Scheduled Jobs、Membership、Massive 和 Stripe 的故障/恢复。
- 验证 System Alerts 的 ERROR / WARNING 去重与 RECOVERY。

Exit criteria:

- 备份可恢复，故障有告警，恢复有 RECOVERY，日志不含 Secret。
- 运维手册、TEST_STATUS.md 和 LIVE_MODE_CHECKLIST.md 有可复现证据。

## CORE FREEZE

以上 Priority 1–5 完成后：

- 冻结 Core schema、Public DTO、Discord structure 和 tracking policy version。
- 完成最终回归、Secret scan、文档审计和 release tag 计划。
- Core 进入仅缺陷修复和生产维护阶段。

## AXIS LAB

**DEFERRED**

当前路线图不包含 AXIS LAB、Model A / B、Generate / Shadow / Champion / Challenger、
模型扫描、自动交易或新的产品频道。只有新的明确规格授权后才重新规划。
