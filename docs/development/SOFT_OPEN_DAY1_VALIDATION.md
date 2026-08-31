# AXIS Soft Open Day 1 Validation — 2026-08-31

## Execution Lock

白天只验证和稳定现有 Signal System，不开发新功能。真实 Production 输入产生的 ST / SW / LP、
Trade Event、Tracking、Results、Summary 和历史从本日开始永久保存；禁止 Reset、重新编号或用
Fake 数据污染 Production 频道。

Synthetic Signal、Fake Card 和事件模拟只允许在 `🧪・card-testing`，并保持 TEST DTO / no
production writes。Massive Live E2E 尚未具备条件时，不临时修改 Short-Term policy。

当前基线：200 tests PASS；Ruff / compileall PASS；Discord runtime PASS；Database revision
`20260830_0022`。这些是代码就绪证据，不等同于 2026-08-31 的 Live E2E 验收。

## Daytime Scope

只允许处理：

1. Signal Input
2. Signal Review / Category Switch
3. Signal Publish
4. Mentor Flow
5. Results Review / Include / Exclude
6. Daily Results
7. Swing / LEAPS Daily Summary
8. Short-Term Tracking
9. Historical Persistence / Public Privacy

白天明确禁止：Stripe、Payment、Free Trial、Day Pass、Monthly、Customer Portal、Price
Grandfathering、Payment Webhook、AXIS LAB、Prediction Chart、新 Analysis 功能和新 Short-Term
策略。

## Start-of-Day Readiness

- [ ] `scripts/verify_database.py` PASS，revision / flags 符合当前文档。
- [ ] `scripts/verify_discord_runtime.py` PASS，权限、Persistent Panel 和命令无漂移。
- [ ] AXIS BOT LaunchAgent running，启动日志没有新的 traceback。
- [ ] `DEPLOYMENT_STAGE=SOFT_OPEN`；Production start date / timezone 正确。
- [ ] 数据库正式 Trade / Analysis 初始状态已记录；不执行任何清理。

## Signal Input Matrix

只使用当天真实 Mentor / Owner 输入验证 Production；格式至少覆盖实际出现的以下组合，不为了
凑测试而伪造 Production Signal：

- [ ] Text
- [ ] Image
- [ ] Text + Image
- [ ] Flexible option format，例如 `SPY 775C .48`
- [ ] 带 expiry，例如 `RIVN 10/16 18C 1.07`
- [ ] Month/year expiry，例如 `ACHR 1/2027 7C .9`

每笔保留证据：Source Message ID、Draft Code、解析后的 ticker / expiry / strike / side / entry、
Review Message ID、最终 Public Trade ID。不得在证据中记录 Secret 或完整 Raw private payload。

## Review / Category / Publish Matrix

### Short-Term

- [ ] 自动进入 simplified review，只显示 Category / Edit / LOTTO / Publish / Delete。
- [ ] 不要求 Mentor，不出现 Position 或 Swing / LEAPS 无关字段。
- [ ] Entry Price 与 Expiry Resolution 正确。
- [ ] Publish 后分配 ST-XXXX，Publication / Message ID 幂等保存。

### Swing / LEAPS

- [ ] Publish 前必须选择 Active Mentor。
- [ ] Mentor assignment 正确写入 Draft、Trade 与 Audit。
- [ ] Public Card 不显示 Mentor、Source 或内部信息。
- [ ] Publish 后分别分配 SW-XXXX / LP-XXXX。

### Category Switch

- [ ] SHORT_TERM → SWING
- [ ] SHORT_TERM → LEAPS
- [ ] SWING → SHORT_TERM
- [ ] LEAPS → SHORT_TERM
- [ ] 每次切换后 UI、Required Fields 和 Mentor Requirement 立即符合目标 Category。

## Mentor Flow

- [ ] Registry 可读，Mentor Select 正常。
- [ ] 详情 Edit 正常；安全 Delete 只允许无关联历史的 Mentor。
- [ ] Trade assignment / reassignment 正确。
- [ ] Manager 可查看 Current / Historical Trade。
- [ ] Public Signal / Results 不显示 Mentor。

## Trade Update / History

- [ ] Swing / LEAPS 的 ADD、TP1、TP2、SL、Runner / Close 按当前正式逻辑 Link Existing Trade。
- [ ] 每次更新保存 Trade Event、Position delta / after、Current State 与 Audit。
- [ ] Current Orders 和 History 与数据库一致。
- [ ] 关闭后的 Trade 进入当天 Results eligibility，但 Active Trade 不进入。

## Short-Term Tracking

Massive Live 可用时验证：

- [ ] Entry publish 后自动注册 Tracker。
- [ ] Quote symbol、price source 和 timestamp 正确。
- [ ] TP1 / TP2 / TP3 事件幂等，LOTTO 标记保持。
- [ ] High / Low Watermark 正确。
- [ ] Protection、Tracking Stop、Overnight 和历史正确。

Massive Live 不可用时：只运行既有自动化和 `/test-short-*` card-testing preview；不修改 TP、
Protection、Momentum、Overnight 或 price-source policy，不在 Production 频道模拟 milestone。

## Market Close / Results

- [ ] 实际 XNYS close + configured delay 后生成唯一 Daily Results Draft。
- [ ] Draft 包含当天 STOPPED Short-Term、CLOSED Swing、CLOSED LEAPS。
- [ ] Active Trade 排除，Loss Trade 不自动隐藏。
- [ ] Include / Exclude / Re-Include / Edit Display / Preview 正常。
- [ ] Exclude 只改变 Public Daily Results；Trade、Event、Mentor、Tracking、Audit 全部保留。
- [ ] Publish Now 与 `16:15 ET` Scheduled Publish 不重复。
- [ ] Final Snapshot 与 Discord Message ID 保存。
- [ ] Short-Term 使用 highest-if-TP / tracking-end-if-no-TP。
- [ ] Swing / LEAPS 显示 TP / SL 与最高收益，不显示 Daily Totals。

## Category Daily Summary

- [ ] `〽️・swing` 发布今日关闭 + 当前 Active。
- [ ] `♾️・leaps` 发布今日关闭 + 当前 Active。
- [ ] `⚡・short-term` 不发布 Daily Summary。
- [ ] Results Exclude 不影响 Swing / LEAPS Summary 或内部历史。

## Historical Persistence / Public Privacy

- [ ] Short-Term / Swing / LEAPS、Mentor Assignment、Trade / TP Event、Tracking End、Results
  Review、Final Results 与 Daily Summary 均可从数据库查询。
- [ ] Bot restart 后 Draft、Event、Tracker、Review、Publication 不重复。
- [ ] Public Signal / Results 不出现 Mentor、Source、Manager、Owner identity、Cosmo、Internal
  UUID、Raw Input、Parser Confidence 或 Private Notes。

## Daytime Exit Gate

只有以下全部有证据时，白天 Signal System 验证才标记 PASS：

- [ ] Signal Input / Review / Category Switch / Publish
- [ ] Short-Term / Swing / LEAPS Review
- [ ] Mentor Flow / Trade History
- [ ] Results Review / Include / Exclude / Daily Results
- [ ] Swing / LEAPS Daily Summary
- [ ] Public Privacy
- [ ] Full Regression PASS

达到 Gate 后停止白天开发，不顺手增加功能。

## Evening Payment Gate

Stripe、Free Trial、Day Pass、Monthly、Member Role、Grandfather Pricing、Customer Portal、Manager
Membership Controls 和 Payment E2E 只能在白天 Gate 完成后，作为独立工作流开始。白天证据不
完整时不提前混入 Payment；晚上开始前仍需读取当时实际状态，不把历史 Test payment 当成新的
Live acceptance。

