# AXIS Current Development Status

**Updated:** 2026-09-05

**Current stage:** GEX Explorer Phase 1 TEST ONLY / Production stabilization

**Database revision:** 20260904_0031

**AXIS LAB:** DEFERRED

状态定义：

- COMPLETE — 规格范围内的实现和自动化测试完成；Production status 仍会单独说明外部验收。
- PARTIAL — 已有可用实现，但仍缺真实端到端、运营准备或重要稳定性验收。
- NOT STARTED — 尚未实现。
- DEFERRED — 明确不在当前开发范围。

## Executive summary

Core Gate A 和 Analysis Gate B 已通过。Pre-Soft-Open backup、测试数据清理、公开编号复位与
Discord 消息清理已完成；`2026-08-31` 起真实输入是永久 Production Data。Daily Results Review
已部署并通过自动化及 runtime 验证。Stripe Test Mode 已完成历史 Day Pass / Monthly 付款验收；
Test / Live 配置与数据库 namespace、不可变价格版本、严格 `livemode` 验证、reconciliation 和
kill switch 已完成并迁移。Stripe 账户 activation/KYC/payout、Live Product/Prices、稳定 HTTPS
webhook、D1 relay、Customer Portal、顾客展示资料与政策页面已完成；当前
`STRIPE_MODE=live`、`STRIPE_ENABLED=true`、`PAYMENTS_ENABLED=true`，readiness 为 PASS / 0
blockers。第一笔真实 Live 付款及完整 lifecycle 尚未验收。
Newcomer Approval / Free Trial Security Gate 已完成代码、迁移、权限矩阵和自动化回归；生产环境
已执行 existing-user baseline 与 Discord structure 安全部署，但真实新账户的完整时钟 E2E 仍待验收。
Swing V2 已实现为独立 Simple Tracked Swing；生产 migration 已把四笔 Active 既有订单明确标记为
Legacy Swing，未删除或改写历史。新 Simple Swing 代码、迁移与自动化通过，真实 Discord / Massive
端到端尚未验收。Short-Term 已有 Production tracking 与 Massive quote，但 TP/Expiry 触发和正式
交易日 Discord 完整证据链仍未验收。

Next execution boundary: 不新增产品功能。先完成 Simple Tracked Swing 真实 Entry → TP → Close →
Results 与 Legacy isolation 验收，再完成 Newcomer 和 Short-Term / Massive 真实 E2E；Stripe 由 Owner
从 Discord 完成第一笔真实付款并验收 webhook → Entitlement → Member Role，再继续 renewal、
failure、payment-method update、cancel 与重复/乱序事件。AXIS LAB 继续 Deferred，Signal /
Analysis / Tracking 业务逻辑保持冻结。

Owner-only Personal Moomoo Execution 已吸收最终规格并复用现有 publication / Trade / Discord /
database / system-alert architecture。代码、forward-only migration、Owner-only channel/control card、
配置 fail-closed 和 synthetic DRY_RUN 测试已完成；当前没有启用 LIVE broker writes。OpenD 尚未监听，
真实账户只读对账与 SIMULATE E2E 仍是发布阻塞项。

GEX Explorer Phase 1 已复用现有 provider-independent GEX engine、Massive option-surface
provider、Moomoo OpenD 1 分钟 K 线 provider、AuditLog、System Alerts 和 Owner-only
card-testing 权限。`/gex ticker:TICKER`、10 个有效到期日、五级 Gamma Regime、
Gamma 分界、上方压力、下方支撑、负 GEX 加速区、真实 1 分钟 K 线和中文复合
热力图已完成。当前严格 **TEST ONLY**，Member Lounge 未开放。

## GEX Explorer — PHASE 1 CODE COMPLETE / TEST ONLY

Implemented:

- Slash command only；普通 Ticker 消息不触发。输入兼容大小写与 `$` 前缀。
- Owner + `🧪・card-testing` 双重 runtime gate；Manager、Member、Newcomer 和 `@everyone` 不可用。
- Massive 只读期权表面 + Moomoo OpenD 只读 1 分钟 K 线；两路数据分工明确，任一失败
  即 fail-closed，不合成假 K 线。SPX 独立处理，绝不 fallback 到 SPY。
- 最新 10 个完整有效 expiry、0DTE 或 nearest-valid Near-Term、minimum coverage fail-closed。
- Net / Positive / Negative GEX、五级 Regime、Zero Gamma、Call/Put Wall、positive/negative zone、
  deterministic bias / triggers；无 LLM 点位。
- 确定性 1800x1125 中文复合图：16:10 风格布局，左侧真实 1 分钟 K 线绘图区约 1.44:1，
  右侧 strike x expiration GEX 热力图加宽；纵轴优先保持蜡烛可读，远端压力/支撑/Gamma
  分界使用图顶/图底标签保留，不再强行压扁 K 线。
- ticker+policy+provider cache、single-flight、per-user cooldown、guild fresh-request limit。
- GEX_REQUESTED / CACHE_HIT / CACHE_MISS / GENERATED / FAILED / RATE_LIMITED AuditLog；现有
  System Alert dedup / Recovery。
- GEX read-only：不创建或修改 Signal、Trade、Result、Mentor、Analysis、Membership、Tracking 或
  Moomoo order。

Live evidence:

- RDDT Massive + Moomoo 双源只读验收 PASS：240 根当日 1 分钟 K 线、10 个有效 expiry、
  338 张期权合约；K 线实际范围 $154.12–$155.93，优化后不再被 $150 / $160 远端结构位压缩，
  1800x1125 复合 PNG 已完成视觉复核。
- Massive closed-market read-only checks PASS：SPY、QQQ、NVDA、TSLA、AAPL 均取得 10 个有效
  expiry；Net、Call Wall、Put Wall 与 normalized raw surface 重算一致；PNG valid。
- Invalid ticker PASS。
- SPX 未映射为 SPY；当前 Massive entitlement 无法提供可用 SPX spot/options surface，明确返回
  `GEX_SPX_UNSUPPORTED`。这是 Provider blocker，不使用代理标的伪造。

Production status: **GEX Explorer = TEST ONLY.** 只有 Owner 可在 card-testing 使用。必须等待
Owner 明确发送 `APPROVE GEX LOUNGE LAUNCH` 后，才能开始 Phase 2 权限、回归和上线；本阶段不得
标记 Member Lounge Live。

## Owner-only Personal Moomoo Execution — CODE COMPLETE / DRY_RUN E2E BLOCKED

Implemented:

- `💹・moomoo-trading` Owner + Bot only；Manager、Member、Newcomer 与 `@everyone` 显式不可见。
- 复用 TradeDraft / TradePublication / Trade；在 member card 发送前执行个人 entry 决策，LIVE 时要求
  broker ACK 优先，但个人执行失败不阻止公共信号。
- Owner-only source + publisher eligibility、production boundary、Short-Term / Swing ENTRY、Swing Close、
  AUTO / FOLLOW / SKIP per-signal override、duplicate-contract block 与完整 idempotency。
- Equity 10% 且 clamp `$200–$500`、buying-power cap、1.05 max chase、LIMIT-only、quote age / spread /
  optional volume / OI、Short-Term 5m 与 Swing 30m TTL。
- Broker source of truth；orders / fills / positions / account snapshots 对账；manual option import、manual
  add / partial / full close、risk epoch 与 lifetime high；非期权持仓安全忽略。
- `<+30% => -30%`、`+30% => breakeven`、`>=+50% => 30% high-watermark trailing`；多合约
  TP50 / TP100 / runner allocation；trailing priority；09:30–09:35 ET 禁止自动退出和 risk-high 更新。
- 持久 control card、kill switches、positions / orders / history、事件通知、System Alert + Recovery 与
  私人 Daily Summary。
- migration `20260903_0030`；所有 broker/account 标识只保存 one-way masked reference。
- `DRY_RUN` 不调用 place/cancel，不生成 production fill 或虚假 broker position；AXIS 不调用
  `unlock_trade`。

Remaining / blockers:

- 本机 `127.0.0.1:11111` 尚无 OpenD 监听，因此账户、持仓、订单、成交的真实只读验证未完成。
- Owner 仍需启动并登录 OpenD，明确选择唯一 US securities account / security firm，完成
  SIMULATE Entry → Fill → TP / trailing → manual add/close → restart 与 Discord Desktop/Mobile 验收。
- DRY_RUN 验收前 `PERSONAL_DRY_RUN_VALIDATED`、LIVE mode、REAL broker environment 和 broker write
  toggle 必须保持关闭。LIVE 切换需要单独 Owner 决策。

Production status: **LIVE broker writes DISABLED.** 当前代码和迁移可部署，但 feature 默认关闭；
OpenD 外部 E2E 完成前不得标记 LIVE READY。

## Soft Open Boundary — COMPLETE

Implemented: Reset 前 PostgreSQL 与配置归档、SHA-256 和可读性验证；事务化测试数据清理；
Discord 原资源原 ID 消息清理；ST/SW/LP 与 Signal/Analysis counter 复位；永久 Reset marker；
正式 Persistent Message 幂等重建；Bot restart 与 runtime verifier。

Production status: `DEPLOYMENT_STAGE=SOFT_OPEN`。生产数据起点为
`2026-08-31 00:00 America/New_York`；该日期后禁止第二次全量 Reset、重新编号或删除正式历史。
完整证据见 `SOFT_OPEN_RESET_2026-08-30.md`。

## Discord Core — COMPLETE

Implemented: Guild 锁定、幂等 Bootstrap、Role / Category / Channel / Permission reconciliation、
AXIS Category / Channel 顺序 reconciliation、持久化 View、控制面板 Message ID 恢复、
Owner-only 测试与告警频道。`👋・welcome` 是第一个公共 AXIS Category 的第一个频道；未取得
Member Role 的用户看不到会员区。

Remaining: 生产故障演练与长期运行观测。

Tests: Blueprint、权限矩阵、unknown-resource safety、重启恢复和只读 runtime verifier。

Production status: Bot 正在目标 Guild 运行。`member-wins` 按 Owner 最新规则向所有人开放发言
和截图上传；服务器现状已符合 Blueprint，不需要 Discord 写入。

## Signal Pipeline — COMPLETE

Implemented: signal-input 文字、图片、多图和转发输入；Structured Output；S-00001 编号；
Category / Mentor / Trade 下拉；编辑、预览、发布、删除；Public DTO 与幂等 Publication；新建
ENTRY 完全缺失入场价时，在已验证期权合约上使用 Massive 当前参考价补入 Review，且不覆盖
已识别价格。行情失败时保留手工审核，不影响草稿生成。Legacy Swing / LEAPS 编辑使用分区向导：
订单类型、Call / Put、仓位等固定值使用下拉菜单，每个输入框只填写一个数据，发布阻塞项使用
中文逐项显示。

Remaining: 持续真实使用观察，不需要架构重做。

Tests: 解析、附件安全、幂等、并发、审核、发布重试、Public leakage 与 persistent Active View。

Production status: 已投入使用；Soft Open Reset 后正式 Trade 为 0，2026-08-31 起第一笔真实
发布将分配新的正式编号并永久保存。

## Simple Tracked Swing — CODE COMPLETE / DB MIGRATED / LIVE E2E PENDING

Implemented: 新 Swing 默认 `SIMPLE_TRACKED_SWING`，不需要 Mentor、Position、ADD、SL、Runner、
Prediction Chart、Fib 或交易计划；使用精简 Review、独立 `SW-XXXX`、紧凑公开 Entry。Swing
Tracker 独立于 Short-Term 命名域，但直接读取 Short-Term 当前固定 TP policy，因此没有第二份 TP
hardcode；每笔订单冻结 policy version 与 price source。支持跨日 High / Low Watermark、幂等 TP、
Active View 强制刷新与 stale fallback、EOD Active Summary、Expiry、restart recovery。

Manager 可在 `signal-input` 使用 `close SW-XXXX` 或完整合约并可选 `@price`，经过 Review 后停止
追踪。报价失败不阻止已审核 Close；公开 Close 依次显示 Entry 成本、lifetime verified highest
return 与明确标注的平仓收益，Results 仍只使用从 Entry 到 Close/Expiry 的 lifetime verified
highest return。Active View 把 Simple 与 Legacy Swing 合并在同一张「当前 Swing 订单」卡，统一
显示成本、最高 TP、当前价格/收益和必要 stale 状态，不再使用 Legacy 独立标题或旧格式。Active
Simple Swing 不进入 Results，终止当日才进入 Swing candidate；最终仍与 Short-Term / LEAPS
合并为一条 AXIS DAILY RESULTS。

Migration: `20260903_0029` 新增 `tracking_mode` 与独立 Swing tracking/event/snapshot 表。迁移前
五笔 Swing（其中四笔 Active）全部回填为 `LEGACY_SWING`，继续旧 Mentor / Position / event
流程直至关闭；会员 Active View 与 Simple Swing 使用统一展示；无删除、无重编号、无历史重写。

Remaining: 完成真实 Discord Desktop / Mobile Entry、真实 Massive quote/TP、Close matching、
EOD、Results 与重启 E2E。

Tests: Simple Entry、共享 TP 来源、无 protection/momentum、跨日 watermark、TP 幂等、Close ID/
contract parser、Close publication、quote-failure safe stop、最高收益冻结、Active View、snapshot、
Legacy isolation 与端到端 publication/tracking 均有自动化覆盖。

Production status: schema 与 Bot runtime 已部署，重启后 Database / Discord verifier 均 PASS；
尚无新 Simple Swing，真实行情和业务链路仍待验收，不能标记 Live Complete。

## Legacy Swing — COMPATIBILITY MODE / LIVE

Implemented: 所有迁移前 Swing 由持久化 `LEGACY_SWING` 明确识别，并保留原 Mentor、Position、
ADD、TP、SL、Runner、Close、结构图和 Daily Summary；Active View 则与 Simple Swing 合并为同一
卡片、同一字段格式。新订单不会进入该模式。

Production status: 四笔 Active Legacy Swing 继续旧引擎直到自然关闭。

## LEAPS Pipeline — COMPLETE

Implemented: 独立 LP 编号、与 Swing 一致的审核、事件、Active View 和公开发布边界；
ENTRY 使用同一套真实日 K 结构图和中文计划卡。

Remaining: 完成真实 LEAPS Desktop / Mobile ENTRY UX；后续统一 ADD / TP / RUNNER / CLOSE。

Tests: 与 Signal / Trade 公共状态机和 Public DTO 测试共同覆盖。

Production status: 可用；Soft Open Reset 后正式 LEAPS 数据为 0，下一笔为 LP-0001。

## Short-Term Automated Tracking — CODE COMPLETE / LIVE E2E PENDING

Implemented:

- SHORT_TERM simplified review，使用独立于 Swing / LEAPS Mentor Trade Flow 的精简审核。
- no Mentor required，不选择 Mentor、不关联 Mentor Trade。
- 独立 ST-XXXX 公开编号。
- Massive MarketTrackingService 与可替换的 market-data provider 边界。
- 单合约 `MASSIVE_QUOTE_STALE`、`MASSIVE_PRICE_UNAVAILABLE`、`LAST_TRADE_OUTLIER` 和
  `OPTION_CONTRACT_NOT_FOUND` 作为可恢复数据质量状态写入订单，不再误报 Massive 服务整体
  ERROR；下一次有效报价自动清零。认证、限流、网络/响应故障仍触发 system-alerts，并显示精确
  provider error code。
- 新发布订单使用 ST_TRACKING_V4 固定 TP1–TP41：10% / 20%，然后从 50% 起每 25 个百分点
  提示一次，直至 1000%；每一级只触发一次。
- 已在追踪的旧订单继续使用冻结的 ST_TRACKING_V2 或 ST_TRACKING_V3，不会在同一订单中
  混用策略。
- Short-Term Runner 已删除；Fast Momentum Reversal 只发送不推进固定编号的 Momentum TP。
- High / Low Watermark。
- Expiry-only Tracking：Short-Term 不发送 SL、保本、trailing protection 或任何价格触发的
  tracking-stop 卡；V2 / V3 / V4 在途订单均持续追踪至合约到期。旧 SL 事件保留为内部审计
  历史，未发布事件会在出队前自动抑制。
- Review 验证的完整期权代码持久化到 Trade 并直接用于 Massive tracking；SPX 合约保留真实
  `SPXW` OCC root。批量报价中的单合约失败独立计数，不再被其他成功合约掩盖。
- 启动轮询会幂等恢复仍未到期、但曾被旧 Protection 规则停止的订单；已发布历史事件保留，
  未发布的旧停止通知取消。
- Overnight Tracking；到期后在后台幂等结束追踪并进入 Results / Audit，不向 Short-Term
  频道发送到期卡。
- LOTTO display flag，适用于 SHORT_TERM / SWING / LEAPS 且不改变业务逻辑。
- Short-Term Active View 与 Daily Summary 已删除；Swing / LEAPS 使用「查看当前持仓订单」，
  每日 Active Summary 使用 Massive 当日 Options Daily OHLC 正式收盘价计算收益。
- Results：当天到期与收盘时仍在追踪的 Short-Term 先进入候选集；盘中 Massive 报价继续按
  交易日写入独立 High / Low Snapshot，但公开收益统一使用从入场到到期/停止追踪期间的
  全生命周期最高期权价相对入场价计算。只有该值严格超过同订单此前已发布 Results 的最佳值
  才进入新一轮 Review，相同或更低不重复发送；新订单首次正常显示。公开行只保留
  类似 `✅ ST-0001 · MU 08/31 970C +52.94%` 的状态、
  订单号、Ticker、到期日、合约代码与收益率；盈利用 `✅`、亏损用 `❌`、持平或不可用用
  `➖`，并按订单号数字升序排列。

Remaining: 完成真实 Massive quote、TP、reversal/expiry、Discord 事件、重启恢复和
Daily Results E2E。

Tests: simplified review、LOTTO、MarketTrackingService、TP idempotency、watermark、momentum
reversal、expiry-only、overnight、expiry stop、restart recovery、无 Short-Term Daily
Summary、Swing/LEAPS Summary 和极简 Results 均有自动化覆盖。

Production status: **真实 Massive E2E 尚未验收。** 当前已有 Production tracking、event 与报价
记录，但仍缺 TP / Expiry / Discord / restart 的完整逐项验收，因此不能标记 Live Complete。

## Mentor Management — COMPLETE

Implemented: create、rename、alias、activate/deactivate、Trade reassign、安全删除与持久化
控制面板。顶层只保留选择和新增；详情页提供编辑、停用/恢复、修改订单 Mentor 和删除。
物理删除需要二次确认，且任何关联 Draft、Trade 或 Analysis 都会阻止删除并保留历史。

Remaining: 仅长期运营观察。

Tests: Registry、审计、面板恢复、重分配、未使用 Mentor 删除与历史关联阻止。

Production status: 已部署。

## Member Management — COMPLETE

Implemented: Discord 原生 searchable User Select；选择服务器成员后查看 Discord 加入时间、
会员开始时间、状态、来源、Entitlements、Member Role、到期日和 cancel-at-period-end；详情页
提供查看信息、赠送会员和移除会员。底层 extend、cancel-at-expiry、revoke、Stripe lifecycle、
Role reconciliation 和审计继续保留。

Remaining: Live Stripe 场景下继续观察多 Entitlement 合并。

Tests: searchable control / detail UI、会员时间字段、Role sync、到期任务、撤权与多 Entitlement
决策。

Production status: 已部署。

## Newcomer Approval / Free Trial Security Gate — CODE COMPLETE / LIVE E2E PENDING

Implemented: 永久 Approval 与当前 Entitlement 分离；首次加入使用 `Newcomer` Role，仅允许只读
welcome/results/member-wins；其他频道显式 DENY，不能通过继承 `@everyone` 绕过。Welcome 唯一
CTA 为 `申请加入 AXIS`；Welcome 卡片为纯中文并重点说明看到欢迎页不等于已加入，必须点击按钮
提交申请。来源与兴趣选择、推荐人弹窗、风险确认、社区安全协议、提交结果以及 join-review
卡片和操作按钮均已中文化；数据库状态码与审核幂等逻辑保持不变。

Application 保存 source、optional referrer、multi-select interests、两项 agreement、PENDING /
FLAGGED / APPROVED / REJECTED、reviewer/time/note。`🛂・join-review` 提供幂等 APPROVE / REJECT /
FLAG。APPROVE 自动创建 3 U.S. Trading Day $0 Trial、移除 Newcomer、添加 Member；无用户 Claim、
无卡、无 Stripe、无续费。

Member Role 同步成功后，AXIS BOT 会分别在 `💬・lobby` 与 `🛋️・member-lounge` 真实 @mention
并欢迎新会员。两个频道各自持久化消息 ID；重启 reconciliation 只补发缺失的一边。生产环境已
完成首位获批用户的双频道发送与 Discord mention 验证。Member Lounge 使用独立的 premium
文案；Day Pass、Monthly、Gift 与手动开通导致 Member Role 首次激活时也会发送，续费和重复
同步不会重复发送。Approval 的 Bot-managed Role 事件已与 manual-role import 隔离；上线核验中
发现的一条误建永久 MANUAL Entitlement 已审计撤销，原 3 个交易日 Free Trial 与 Member Role
保持有效。

Trial 终身一次继续由 `membership_trial_lifetime_once(discord_user_id, trial_type)` 保护，并新增
application/reviewer 溯源。到期保留 Trial 与 Approval 历史，只按 aggregate entitlement 移除
Member，永不重新添加 Newcomer；Approved rejoin 直接恢复 entitlement 投影，Never-approved /
Rejected rejoin 保持 Newcomer。

NewcomerRiskScanner 已实现 VERY_NEW_ACCOUNT、NEW_ACCOUNT、PREVIOUS_REJECTION、PREVIOUS_FLAG、
TRIAL_ALREADY_USED、REJOIN_WITHOUT_APPROVAL、POSSIBLE_IMPERSONATION，使用配置化 protected names、
持久去重 flag、system-alerts fingerprint 去重和 NEWCOMER SECURITY aggregate health。Scanner
只辅助 Review，不自动 Ban / Kick / Reject。

Production safety: migrations `20260831_0026` / `20260902_0028` / `20260903_0029` 与 pre-gate user baseline/cutover
工具已完成；必须先 dry-run 再应用。Existing Production users 只 baseline 为 Approved，不获得
Trial。

Remaining: 真实新 Discord 账户完成 Join → Apply → Approve → Trial → Expiry 的 Live 时钟验收。

## Day Pass — LIVE ENABLED / REAL PAYMENT E2E PENDING

Implemented: XNYS 一个交易日、动态 Checkout、payment event dedup 和 Role 同步；
Free Trial 与 Day Pass 均使用 `TradingCalendarService` 的 XNYS 交易日边界，但分别固化 3 个和
1 个交易日；Monthly 仍按 Stripe 账期。

Remaining: Owner 完成真实付款、交易日到期与 Discord Role reconciliation 验收。

Tests: 自动化及 Stripe Test Mode checkout.session.completed E2E。

Production status: Live Checkout 已启用；尚无真实 Live payment event。

## Monthly — LIVE ENABLED / REAL LIFECYCLE E2E PENDING

Implemented: 自动续费订阅、invoice lifecycle、cancel-at-period-end、PAST_DUE 和 Portal。

Remaining: 真实 signup、renewal、payment failure/recovery、payment-method update、cancel 和重复/
乱序 webhook 验收。

Tests: 自动化及 Test Mode signup / invoice replay。

Production status: Live Checkout 与 Portal 已启用；尚无真实 Live subscription。

## Stripe Payment — LIVE ENABLED / FIRST REAL PAYMENT E2E PENDING

Implemented: 动态 Checkout / Portal；Test / Live 独立 Secret、URL、Product、Price 与 database
namespace；`STRIPE_MODE`；`PAYMENTS_ENABLED` kill switch；签名 Webhook；严格 `event.livemode` +
metadata environment 验证；environment-scoped dedup；最小 payment event；不可变价格版本与
signup snapshot；grandfathering；15 分钟对账、受控修复和 Owner-only mismatch alert；受保护的
Live resource setup/readiness verifier；完整 Payment 运维手册；`axisdesk.fyi` Sites Worker 原始
body 签名验证；最小化 D1 事件队列；Bot 私密 relay poll / ACK / retry；支付 success、cancel 和
Portal return 页面。

Remaining: Owner 自行完成真实首笔付款；验收 Day Pass 到期、Monthly renewal/failure/recovery、
payment-method update、cancel、重复/乱序 delivery 与真实 Price Grandfathering。Test key 在
2026-08-31 只读 Dashboard 审计时出现在受限工具输出中，下一次 Test 外部调用前必须轮换。

Tests: 单元/集成、Test 历史外部 verifier、dual-mode fallback rejection、kill switch、livemode
mismatch-before-reservation、environment dedup、价格版本/grandfathering 和 reconciliation repair。

Production status: `STRIPE_ENABLED=true`、`STRIPE_MODE=live`、`PAYMENTS_ENABLED=true`；Live
Day Pass V1 USD 9.99 与 Monthly V2 USD 149.99 catalog 均已绑定；已有 Monthly V1 订阅保持
USD 99.99 grandfathered 价格。Customer Portal 和公开 webhook 已启用，
最终 verifier 为 PASS / 0 blockers。Live billing 接口已上线，但没有执行或伪造真实付款，完整
Live E2E 仍以 Owner 第一笔真实付款为准。

## Price Grandfathering — CODE COMPLETE / LIVE E2E PENDING

Implemented: entitlement 保存不可变 Price snapshot；catalog 按 Test / Live 和版本隔离；管理工具
支持 create、switch current 与 rollback；既有订阅不因 catalog 更新被覆盖。

Remaining: Live 创建 V2 Price 后完成真实 grandfathering 演练。

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

Implemented: analysis-input、A-00001 编号、Mentor 下拉、关键点位逐项下拉编辑/新增/删除、
简短中文编辑与重写、归档、发布、删除、Raw / Normalized / Public Snapshot 与模型 Trace。

Remaining: 用真实 Mentor 内容继续做质量与移动端 UX 复核。

Tests: 文字/图片/多图、四类 Analysis、无臆造、失败重试、独立观点和 Public leakage。

Production status: FEATURE_ANALYSIS_ENABLED=true；Soft Open Reset 后正式 Analysis 为 0，
2026-08-31 起的新输入永久保存。

## Analysis Fusion — COMPLETE

Implemented: Mentor-first / AXIS-fill-missing、字段 provenance、冲突记录、2–3 scenarios、
Top Scenario confidence gate 与归档层次。

Remaining: 真实 Mentor 卡片逐项复核点位、warnings 和公开文案。

Tests: 来源优先级、冲突、阈值、fallback 和 card/chart 同源。

Production status: FEATURE_AXIS_STOCK_ANALYST_ENABLED=true；Reset 后等待第一份 Soft Open
Mentor input 做真实质量复核。

## Prediction Chart — CODE COMPLETE / LIVE MOBILE UX PENDING

Implemented: AXIS 自有 Pilot-style 确定性 renderer、真实日 K、HLX 25 / 90 High-Low EMA
通道、蓝色起点、黄色关注区、红色失效线、绿色突破/目标线、右侧白色预测路径及 Mentor-first
点位；输入图片仅作内部证据，Review / Public 只展示 AXIS 根据最终点位与方向重绘的图；真实
OHLC 缺失时拒绝合成蜡烛，图片失败不阻塞文字归档。

Remaining: 真实 Mentor 输入和移动端 Discord 的视觉验收；当前策略不新增 AI 生图。

Tests: renderer、fallback、路径同源、Manager 点位重建和 source image 不转发；已用数据库保存的
RDDT 82 根真实日 K 完成本机 1600×900 视觉复核。

Production status: 新 renderer 与关键点位 Review UI 已部署到 `com.axis.bot`，源码/运行时
SHA-256 一致，Discord runtime verifier PASS；尚未形成完整移动端 UX 验收记录。

## Results — COMPLETE

Implemented: position-event 加权收益、关闭订单 Public DTO，以及统一的 Daily Results Review。
实际收盘后生成唯一 Draft；Eligible Trade 默认 Included；Manager 可 Exclude / Re-Include、编辑
公开展示、纠错、预览或 Publish Now；`16:15 ET` 自动发布，Final Snapshot 不可变保存。

Safety: Exclude 只影响当天 Public Results，保存原因与完整 Audit；不会删除 Trade、Event、
Tracking、Mentor Dataset、内部绩效或 Swing / LEAPS Summary。Active Trade（包括 Simple Swing）
不进入 Review，
亏损订单不自动隐藏，不显示 Daily Totals。

Remaining: 在第一个有 Eligible Trade 的正式交易日完成 Manager Desktop / Mobile click-through
与 `16:15 ET` 真实 Discord 发布验收。

Tests: Draft 幂等、Active 排除、三类别格式、LOTTO、Exclude 不删除历史、Re-Include、Display
Edit、Correct Result Audit、Preview、Publish Now / Scheduled 去重、Early Close 与不可变快照。

Production status: 已部署；`📋・results-review` ID 已写入 Guild Config，scheduled job 正常，
Soft Open Reset 后尚无首日 Eligible Production Trade。

## Card Testing — COMPLETE

Implemented: Owner-only test commands 使用内存 DTO，不写正式订单或 Results。

Remaining: 新卡片类型出现时补 preview。

Tests: 权限、命令同步和无数据库副作用。

Production status: Owner-only 频道已部署；`/test-results-review` 已同步到目标 Guild，所有
Preview 使用内存 TEST DTO，不写 Production 数据或发布到 `📊・results`。

## System Alerts — PARTIAL

Implemented: ERROR / WARNING / RECOVERY、fingerprint 去重、occurrence count 和持久化状态；
Stripe Webhook Relay 与 Subscription Reconciliation 在下一次成功轮询时按原 fingerprint
关闭故障并发送单次恢复卡，空 Relay 队列同样可确认恢复。

Remaining: 数据库、OpenAI、Discord、Jobs、Membership 与行情依赖的真实故障/恢复演练。

Tests: dedup、恢复、再次告警。

Production status: Reset 已清除开发阶段 Fake Alert；当前没有 active system alert，完整真实
故障演练尚未完成。

## Backup — PARTIAL

Implemented: PostgreSQL custom-format dump、pg_restore list 验证、SHA-256 和本地备份目录。

Remaining: 加密 off-host target、保留策略和自动监控。

Tests: Secret 不进入 argv、文件校验脚本。

Production status: Pre-Soft-Open custom dump 与配置归档已验证可读并保存 SHA-256；均位于 Git
忽略的 `var/backups/`。没有 off-host 副本证明。

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
