# AXIS Current Development Status

**Updated:** 2026-08-30

**Current stage:** Core feature-complete / Production live validation

**Database revision:** 20260830_0019

**AXIS LAB:** DEFERRED

状态定义：

- COMPLETE — 规格范围内的实现和自动化测试完成；Production status 仍会单独说明外部验收。
- PARTIAL — 已有可用实现，但仍缺真实端到端、运营准备或重要稳定性验收。
- NOT STARTED — 尚未实现。
- DEFERRED — 明确不在当前开发范围。

## Executive summary

Core Gate A 和 Analysis Gate B 已通过。Discord Core、Signal、Analysis、会员、结果与管理工具
均已实现；Stripe Test Mode 已完成 Day Pass / Monthly 付款验收。当前最高优先级是
Short-Term / Massive 真实端到端：数据库已有已发布 ST-0001 和有效 Entry Price，但
short_term_tracking 仍无注册记录，所以不能宣称自动跟踪已经投入生产。

## Discord Core — COMPLETE

Implemented: Guild 锁定、幂等 Bootstrap、Role / Category / Channel / Permission reconciliation、
持久化 View、控制面板 Message ID 恢复、Owner-only 测试与告警频道。

Remaining: 生产故障演练与长期运行观测。

Tests: Blueprint、权限矩阵、unknown-resource safety、重启恢复和只读 runtime verifier。

Production status: Bot 正在目标 Guild 运行；最近盘点未发现结构漂移。

## Signal Pipeline — COMPLETE

Implemented: signal-input 文字、图片、多图和转发输入；Structured Output；S-00001 编号；
Category / Mentor / Trade 下拉；编辑、预览、发布、删除；Public DTO 与幂等 Publication。

Remaining: 持续真实使用观察，不需要架构重做。

Tests: 解析、附件安全、幂等、并发、审核、发布重试、Public leakage 与 persistent Active View。

Production status: 已投入使用，数据库有 Published Signal。

## Swing Pipeline — COMPLETE

Implemented: 独立 SW 编号、订单事件、Active View、加仓阶梯、TP / SL / Runner / Close；
ENTRY 已升级为真实日 K 结构图 + 中文交易计划卡，并使用 Mentor-first / AXIS-fill-missing 点位。

Remaining: 完成真实 Discord Desktop / Mobile ENTRY UX 验收；后续再统一 ADD / TP /
RUNNER / CLOSE 的视觉样式。

Tests: 状态流转、仓位、发布幂等、关闭订单排除、Results、Mentor 点位优先、0.618、
确定性图片和 Discord attachment。

Production status: 可用；当前盘点没有新的 Swing live tracking 结论。

## LEAPS Pipeline — COMPLETE

Implemented: 独立 LP 编号、与 Swing 一致的审核、事件、Active View 和公开发布边界；
ENTRY 使用同一套真实日 K 结构图和中文计划卡。

Remaining: 完成真实 LEAPS Desktop / Mobile ENTRY UX；后续统一 ADD / TP / RUNNER / CLOSE。

Tests: 与 Signal / Trade 公共状态机和 Public DTO 测试共同覆盖。

Production status: 可用；没有宣称已完成新的真实 LEAPS 运营验收。

## Short-Term Automated Tracking — CODE COMPLETE / LIVE E2E PENDING

Implemented:

- SHORT_TERM simplified review，使用独立于 Swing / LEAPS Mentor Trade Flow 的精简审核。
- no Mentor required，不选择 Mentor、不关联 Mentor Trade。
- 独立 ST-XXXX 公开编号。
- Massive MarketTrackingService 与可替换的 market-data provider 边界。
- 固定 TP1–TP10：20% / 50% / 100% / 150% / 200% / 300% / 400% / 500% / 750% /
  1000%，每一级只触发一次。
- Short-Term Runner 已删除；Fast Momentum Reversal 只发送不推进固定编号的 Momentum TP。
- High / Low Watermark。
- Tracking Protection：初始 -50%；TP1 后锁成本；之后锁前一级 TP。
- Overnight Tracking。
- Tracking Stop。
- LOTTO display flag，适用于 SHORT_TERM / SWING / LEAPS 且不改变业务逻辑。
- Short-Term Active View 与 Daily Summary 已删除；Swing / LEAPS 使用「查看当前持仓订单」。
- Results。

Remaining: 修复或确认已发布订单自动注册 tracking 的运行路径；完成真实 Massive quote、
TP、reversal/protection、Discord 事件、重启恢复和 Daily Results E2E。

Tests: simplified review、LOTTO、MarketTrackingService、TP idempotency、watermark、momentum
reversal、tracking protection、overnight、tracking stop、restart recovery、无 Short-Term Daily
Summary、Swing/LEAPS Summary 和极简 Results 均有自动化覆盖。

Production status: **真实 Massive E2E 尚未验收。** ST-0001 已 Published 且 Entry Price 有效，
但 short_term_tracking=0、short_term_events=0，因此不能标记 Live Complete。

## Mentor Management — COMPLETE

Implemented: create、rename、alias、activate/deactivate、Trade reassign 与持久化控制面板。

Remaining: 仅长期运营观察。

Tests: Registry、审计、面板恢复与重分配。

Production status: 已部署。

## Member Management — COMPLETE

Implemented: lookup、gift、extend、cancel-at-expiry、revoke、Role reconciliation 和审计。

Remaining: Live Stripe 场景下继续观察多 Entitlement 合并。

Tests: Role sync、到期任务、撤权与多 Entitlement 决策。

Production status: 已部署。

## Free Trial — COMPLETE

Implemented: 终身一次、版本化风险确认、XNYS 三个交易日和 Member Role 同步。

Remaining: Test Guild 的真实到期时钟演练。

Tests: 周末、休市日、重复申请、到期和多 Entitlement。

Production status: 代码已部署；数据库存在 ACTIVE FREE_TRIAL entitlement。

## Day Pass — PARTIAL

Implemented: XNYS 一个交易日、动态 Checkout、payment event dedup 和 Role 同步。

Remaining: Stripe Live Product / Price / webhook 与真实付款验收。

Tests: 自动化及 Stripe Test Mode checkout.session.completed E2E。

Production status: Test Mode 已通过；Live 未启用。

## Monthly — PARTIAL

Implemented: 自动续费订阅、invoice lifecycle、cancel-at-period-end、PAST_DUE 和 Portal。

Remaining: Live renewal、payment failure、payment-method update、cancel 和重复 webhook 验收。

Tests: 自动化及 Test Mode signup / invoice replay。

Production status: Test Mode 已通过；Live 未启用。

## Stripe Integration — PARTIAL

Implemented: 动态 Checkout / Portal、签名 Webhook、最小 payment event 存储、幂等、价格快照。

Remaining: 公开 TLS webhook、Live keys / products / prices、Live events、法律商家资料和隐私检查。

Tests: 单元/集成测试和 Test Mode 外部 verifier。

Production status: STRIPE_ENABLED=true 指向 Test Mode；不得解释为 Live billing。

## Price Grandfathering — PARTIAL

Implemented: entitlement 保存不可变 Price snapshot，既有订阅不因 catalog 更新被覆盖。

Remaining: 在 Stripe Test/Live 创建新 Price 后完成真实 grandfathering 演练。

Tests: 自动化覆盖。

Production status: 机制已部署，外部价格变更验收待办。

## Manager Extend Access — PARTIAL

Implemented: MANUAL_EXTENSION 独立 entitlement，不覆盖付款来源。

Remaining: 真实 Manager 流程和到期组合验收。

Tests: 自动化覆盖 extend / expiry / Role merge。

Production status: 已部署，运营验收仍需记录。

## GENERAL UI — COMPLETE

Implemented: Welcome、Membership、Results、Member Wins、Lobby Topic 与数据库 Message ID 幂等同步。

Remaining: 仅文案和移动端体验的持续观察。

Tests: Public identity、Guide 数量、权限和 runtime verifier。

Production status: 已部署。

## Analysis Pipeline — COMPLETE

Implemented: analysis-input、A-00001 编号、Mentor 下拉、编辑、重写、归档、发布、删除、
Raw / Normalized / Public Snapshot 与模型 Trace。

Remaining: 用真实 Mentor 内容继续做质量与移动端 UX 复核。

Tests: 文字/图片/多图、四类 Analysis、无臆造、失败重试、独立观点和 Public leakage。

Production status: FEATURE_ANALYSIS_ENABLED=true；已有 4 个 Published Analysis。

## Analysis Fusion — COMPLETE

Implemented: Mentor-first / AXIS-fill-missing、字段 provenance、冲突记录、2–3 scenarios、
Top Scenario confidence gate 与归档层次。

Remaining: 真实 Mentor 卡片逐项复核点位、warnings 和公开文案。

Tests: 来源优先级、冲突、阈值、fallback 和 card/chart 同源。

Production status: FEATURE_AXIS_STOCK_ANALYST_ENABLED=true；真实输出已有发布记录。

## Prediction Chart — PARTIAL

Implemented: 确定性 renderer、单一路径、无未来 K 线、失败不阻塞文字归档。

Remaining: 真实 Mentor 输入和移动端 Discord 的视觉验收；当前策略不新增 AI 生图。

Tests: renderer、fallback、路径同源和 source image 不转发。

Production status: 可生成并发布，但尚未形成完整 UX 验收记录。

## Results — COMPLETE

Implemented: position-event 加权收益、关闭订单幂等官方发布与 Public DTO。

Remaining: 用更多真实已关闭订单观察统计。

Tests: 加权计算、防泄漏、幂等 Message ID。

Production status: 已部署。

## Card Testing — COMPLETE

Implemented: Owner-only test commands 使用内存 DTO，不写正式订单或 Results。

Remaining: 新卡片类型出现时补 preview。

Tests: 权限、命令同步和无数据库副作用。

Production status: Owner-only 频道已部署。

## System Alerts — PARTIAL

Implemented: ERROR / WARNING / RECOVERY、fingerprint 去重、occurrence count 和持久化状态。

Remaining: 数据库、OpenAI、Discord、Jobs、Membership 与行情依赖的真实故障/恢复演练。

Tests: dedup、恢复、再次告警。

Production status: 数据库有 active/resolved 告警记录；完整演练尚未完成。

## Backup — PARTIAL

Implemented: PostgreSQL custom-format dump、pg_restore list 验证、SHA-256 和本地备份目录。

Remaining: 加密 off-host target、保留策略和自动监控。

Tests: Secret 不进入 argv、文件校验脚本。

Production status: 本地最新备份存在；没有 off-host 副本证明。

## Restore — PARTIAL

Implemented: 双确认 restore 工具和操作文档。

Remaining: 在非生产环境完整 restore、数据核对与 rollback rehearsal。

Tests: 工具安全边界有自动化覆盖。

Production status: 未完成正式 restore rehearsal。

## Production Monitoring — PARTIAL

Implemented: 结构化日志、后台 job、System Alerts 与若干只读 verifier。

Remaining: 集中监控、值班/响应流程、外部健康检查和故障演练。

Tests: monitor service 与 alert policy 自动化覆盖。

Production status: 本机 LaunchAgent 运行；尚不是完整托管生产体系。

## AXIS LAB — DEFERRED

未开始：Model A / Model B、Generate / Shadow / Champion / Challenger、模型扫描、账户读取、
自动交易和会员自动化交易。频道可以预留，功能开关必须保持关闭。
