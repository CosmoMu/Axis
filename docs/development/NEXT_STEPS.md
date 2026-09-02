# AXIS Next Steps

**Updated:** 2026-08-31

当前只做 Production live validation 和 Core 稳定化。优先级固定如下，不插入 AXIS LAB 或
新的产品功能。

## Production Data Lock

Soft Open Day 1 清单仍用于核心回归证据，但 Stripe 双环境基础工作已在独立边界内完成，未修改
Signal System。当前不新增功能；只执行下面固定 Priority 的真实验收、外部配置和稳定化。

Soft Open Reset 已完成。`2026-08-31` 起真实输入均为永久 Production Data；后续验证不得
wipe、truncate、重新编号或用 Production 频道生成 Fake 数据。Synthetic Preview 只走
`🧪・card-testing`。

## Priority 0 — Newcomer Gate Live E2E

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
