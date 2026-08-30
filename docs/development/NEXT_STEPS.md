# AXIS Next Steps

**Updated:** 2026-08-30

当前只做 Production live validation 和 Core 稳定化。不要开始 AXIS LAB。

## 1. Short-Term / Massive real E2E — P0

Entry criteria:

- 使用当前已发布 ST-0001 或一笔明确的测试订单。
- Massive key 可用且不输出 Secret。
- 先保存数据库、日志和 Discord 当前基线。

Work:

- 找出已发布订单未进入 short_term_tracking 的原因。
- 验证 register_missing、真实 quote、watermark 和 policy snapshot。
- 触发并核对 TP milestone、Fast Momentum Reversal、Reference Protection / Stop。
- 核对 Discord 事件、Active View、当日 Active/Closed 总结和 Results。
- 重启 Bot，确认同一 tracking/event 不重复且状态恢复。

Exit criteria:

- 数据库存在对应 tracking、quote timestamp 和幂等 event。
- Discord 实际消息与数据库事件一致。
- 重启前后无重复 milestone；失败时有可操作 System Alert。
- 将证据和结论同步 TEST_STATUS.md 与 LIVE_MODE_CHECKLIST.md。

## 2. Short-Term Discord UX validation — P0

Entry criteria: 第 1 项的真实 tracking 已工作。

Work:

- 在移动端和桌面端检查 review、Active View、milestone、protection、close 和 daily summary。
- 验证只能 Bot 说话的频道权限、Manager 操作入口和公开字段白名单。
- 验证发布后 Review 保留最终状态，不误删正常 Bot 卡片。

Exit criteria: Manager 能在不滚动查找旧控件的情况下完成审核；会员卡片没有 Mentor、Source、
Market、Bid、Ask 或内部 ID 泄漏。

## 3. Stripe Live readiness — P1

Entry criteria: Stripe Test Mode 保持隔离，完整备份可用。

Work:

- 部署受限的公开 TLS webhook。
- 创建 Live Product / Prices，Secret 只进 Secret Store。
- 验证 Day Pass、Monthly signup、renewal、failure、payment-method update、cancel 和重复事件。
- 验证 Customer Portal、Price Grandfathering、退款/取消文案和人工隐私清单。

Exit criteria: LIVE_MODE_CHECKLIST.md 的 Stripe 项全部完成并由 Owner 明确批准；未批准前保持
Test Mode。

## 4. Real Mentor Analysis UX — P1

Entry criteria: 选择 2–3 个具有不同内容完整度的真实 Mentor input。

Work:

- 对比 Raw、Mentor、Stock Analyst、Final Fused 和 Public Snapshot。
- 核对 why-now、关键点位、conflict、warnings、Top Scenario 和 Prediction Chart。
- 在桌面与移动端检查下拉、编辑、重写、重新生成图片、归档和发布。

Exit criteria: 公开卡片忠于 Mentor input；AXIS 只补缺、不覆盖；所有新增点位均可追溯；
renderer 失败时文字流程仍可完成。

## 5. Production stabilization — P1

Work:

- 配置加密 off-host backup 和保留策略。
- 在非生产环境做完整 restore / rollback rehearsal。
- 对 Database、OpenAI、Discord、Jobs、Membership、Massive 和 Stripe 做故障/恢复演练。
- 建立外部健康检查、告警响应和最小值班说明。

Exit criteria: 备份可恢复、故障有告警、恢复有 RECOVERY、日志不含 Secret，运维手册和
TEST_STATUS.md 有可复现证据。

## 6. Core freeze — P2

Entry criteria: 上述 P0/P1 均完成。

Work:

- 冻结 Core schema、Public DTO、Discord structure 和 policy version。
- 完成最终回归、Secret scan、文档审计和 release tag 计划。

Exit criteria: 没有 P0/P1 已知问题，Live Checklist 完成，Core 可以进入只做缺陷修复的稳定期。

## Explicitly excluded

本路线图不包含 AXIS LAB、Model A / B、自动交易或新频道扩张。只有新规格明确授权后才重新规划。
