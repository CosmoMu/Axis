# AXIS Next Steps

**Updated:** 2026-08-30

当前只做 Production live validation 和 Core 稳定化。优先级固定如下，不插入 AXIS LAB 或
新的产品功能。

## Priority 1 — Short-Term + Massive Real E2E

Work:

- 找出 Published ST-0001 未进入 short_term_tracking 的原因。
- 验证 Massive MarketTrackingService 的真实 option quote、symbol、price source 和 timestamp。
- 验证 High / Low Watermark、TP 20% / 50% 和全部 Runner milestones。
- 验证 Fast Momentum Reversal、Reference Protection、Overnight Tracking 和 Tracking Stop。
- 核对 Discord event、Active View、Daily Summary、Results 和数据库状态。
- 重启 Bot，确认 tracking 恢复且 event / publication 不重复。

Exit criteria:

- 数据库存在对应 tracking、真实 quote timestamp 和幂等 event。
- Discord 消息与数据库一致，重启前后没有重复 milestone。
- Massive 故障和恢复产生可操作的去重告警。

## Priority 2 — Short-Term Discord Desktop / Mobile UX Validation

Work:

- 在 Desktop 和 Mobile 检查 simplified review、发布、Active View、milestone、protection、
  close、Daily Summary 与 Results。
- 确认 Short-Term 不出现 Mentor 或 Swing / LEAPS Mentor Trade Flow。
- 验证只允许 Bot 发言的会员频道权限和 Manager 操作入口。
- 验证发布后 Review 保留最终状态，不误删正常 Bot 卡片。

Exit criteria:

- Manager 不需要反复滚动即可完成审核。
- 会员内容不泄露 Mentor、Source、Market、Bid、Ask、Parser 或内部 ID。

## Priority 3 — Stripe Live Readiness

Work:

- 部署受限的公开 TLS webhook。
- 创建 Live Product / Prices，所有 Secret 只进入部署 Secret Store。
- 验证 Day Pass、Monthly signup、renewal、failure、payment-method update 和 cancellation。
- 验证 Customer Portal、Price Grandfathering、重复/乱序事件和公开隐私清单。

Exit criteria:

- LIVE_MODE_CHECKLIST.md 的 Stripe Live 项全部完成。
- Owner 明确批准后才从 Test Mode 切换到 Live。

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
