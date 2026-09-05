# AXIS Implemented Features

**Updated:** 2026-09-04

本清单记录代码仓库中已经存在的能力。是否完成真实上线验收以 CURRENT_STATUS.md 和
LIVE_MODE_CHECKLIST.md 为准。

## Discord / Runtime

- Guild ID、Application ID 与 Owner ID 校验。
- Role、Category、Channel、Topic、Position 和 Permission 幂等 reconciliation。
- 保存 Snowflake ID 后优先按 ID 复用；只对 AXIS-owned 资源执行受控更新。
- Persistent View、Review Card 和 Manager 控制面板重启恢复。
- Manager-only Operations、Owner-only System Alerts 与 Card Testing。
- Owner-only `💹・moomoo-trading`、持久 control card 与明确 persona permission isolation。

## GEX Explorer — Phase 1 Test Only

- `/gex ticker:TICKER` Slash Command；不会监听普通 Ticker 消息。
- Owner-only + `🧪・card-testing`；wrong-channel 与 unauthorized 请求使用 ephemeral feedback。
- Massive GEX option-surface / spot / 5 分钟 K 线正式 provider；10 个有效 expiration、0DTE /
  Near-Term、partial-expiry skip 和 minimum coverage gate；SPX 独立映射且绝不使用 SPY 替代。
- Moomoo OpenD 5 分钟 K 线仅作为后台 shadow candidate；比较 bar count、重合时间、共同收盘价
  和 source timestamp，永不选择或阻止 Massive 正式输出。
- 当日期权成交量 GEX / 1% move、vendor Gamma + IV fallback、Net/Positive/Negative GEX、五级 Regime、
  Zero Gamma、GEX-based major Walls、现价附近 deterministic minor pressure/support、Clusters、
  Bias 与 deterministic triggers。
- 1800x1125 中文复合图：左侧真实 5 分钟 K 线、压力/支撑/Gamma 分界、负 GEX
  波动加速区；右侧加宽的 strike x expiration GEX 热力图。K 线采用 candle-first 自适应
  纵轴；远端压力/支撑/Gamma 分界以横贯绘图区的图外结构轨显示，远端负 GEX 加速区
  以紫色全宽图外带显示实际点位或范围，既不压缩真实蜡烛波幅，也不会丢失结构。
- 图表与 Discord 卡片统一保留 `Call Wall · 大压力`、`小压力`、`Put Wall · 大支撑`、
  `小支撑`、`0 Gamma · Gamma 分界` 标准名称与中文解释。
- 中文 Discord 卡片、market-closed/stale 标签、Massive 正式数据时间和
  source/coverage/cache/policy metadata。
- Moomoo 分钟数据不可用时 fail-closed，不生成或插值任何假 K 线。
- Cache、single-flight、per-user cooldown、guild limit、AuditLog 和 System Alert / Recovery。
- 独立 `GEX_EXPLORER_ENABLED` / `GEX_EXPLORER_MODE=TEST` fail-closed gate。
- 严格 read-only，不触发 Signal、Trade、Result、Analysis、Membership、Tracking 或 Moomoo。
- Member Lounge mode 尚未实现/启用；等待 `APPROVE GEX LOUNGE LAUNCH`。

## Owner-only Personal Moomoo Execution

- 独立 `FEATURE_PERSONAL_EXECUTION_ENABLED`；不解除 Model A/B / LAB deferred gate。
- DRY_RUN / LIVE 与 SIMULATE / REAL 双层模式；LIVE 还需要 auto-trading、已验收标志、明确账户和
  security firm，任一缺失都拒绝启动。
- Moomoo adapter 只用正确 app-aligned account/position fields；账户 ID one-way mask；从不调用
  `unlock_trade`。
- 只跟随 production Short-Term / Swing approved Entry；Owner scope 同时校验 source submitter 和
  publisher；Review 提供 Owner-only AUTO / FOLLOW / SKIP override。
- Public Signal 与个人 execution failure isolation；LIVE broker ACK 在 Discord member card 之前，
  rejected personal order 不影响公共发布。
- Equity/buying-power budget、max-chase、fresh quote、spread、optional volume/OI、LIMIT-only、TTL、
  duplicate contract 和 broker-source-of-truth safeguards。
- Manual option sync、add risk epoch、partial/full close、AXIS-owned order/fill mapping、restart
  idempotency；不导入普通股票持仓。
- Initial / Breakeven / Trailing / Runner risk stages、TP50/TP100 allocation、opening guard、Swing
  linked close、kill switches、private events、daily summary 和 System Alert recovery。
- DRY_RUN 全决策路径写审计 decision，但不会创建 broker order、fill 或 fake position。
- GENERAL Guide 依据数据库 Message ID 幂等同步。
- Manager-only `📋・results-review`、每日 Review View 与公开 Results 幂等恢复。
- macOS LaunchAgent、Dockerfile 与 Compose 基础部署。

## Database

- Alembic revisions 0001–0031；0020 清除旧 Short-Term 数据中违反 no-Mentor 边界的关联，
  0021 增加期权到期日解析 trace，0022 增加 Daily Results Review，0023 隔离 Stripe Test / Live
  Price、Entitlement、Session 与 Payment Event namespace，0024 规范新 Stripe check constraint 名称，
  0025 将 Free Trial duration 明确拆分为 Calendar Day / Trading Day 并保留历史 claim 到期时间；
  0026 增加永久 Approval、Application、Newcomer risk、Role sync 与 Trial 审批溯源；0027–0028
  增加当前支付/迎新状态；0029 增加 Swing tracking mode 及独立 tracking/event/snapshot 表，并将
  既有 Swing 安全回填为 `LEGACY_SWING`；0030 增加 Owner-only personal execution settings、
  broker positions / risk epochs、orders、fills、events、account snapshots 与 daily summaries；0031
  扩展 Analysis chart-source provenance 字段宽度。
- Signal、Trade、Event、Publication、Mentor、Membership、Audit 和 Scheduled Job。
- Analysis Draft、Revision、Archive、Scenario、Evidence、Publication 和 provenance。
- LLM invocation provider/model/workload/prompt/schema/latency/result trace。
- Input code counters：Signal S-00001、Analysis A-00001、Public Trade ST/SW/LP。
- Membership Price Catalog、Acknowledgement、Entitlement、Payment Event 和 System Alert。
- Short-Term Tracking、Event、Daily Snapshot 与 Results 数据结构。
- Simple Swing Tracking、Event、Daily Snapshot、High/Low Watermark 与冻结 policy version。
- `daily_results_reviews` / `daily_results_items`、不可变 Final Snapshot、Exclude / Correction
  Audit 与 `guild + trading_date` 唯一约束。
- Publication claim / retry / finalize 和必要的唯一约束。

## Signal intake and parsing

- Discord 原文、转发 snapshot、图片、多图和附件说明合并。
- PNG / JPEG / WEBP 检测、真实文件签名归一化、大小和安全路径验证。
- Source message checksum 与幂等。
- OpenAI Responses Structured Output 与 SIGNAL_PARSE / SIGNAL_REPAIR 路由。
- 失败草稿、missing fields 和安全错误信息。
- 过去日期或不可能年份的 expiry 会在进入 review 前清空并要求人工确认，不允许直接发布。
- 默认仓位阶梯：1/8、1/4、1/2、3/4。

## Signal review and publication

- AI Category 默认识别，Manager 可通过下拉修改。
- Mentor 和关联订单下拉。
- Review 直接显示完整会员卡片与预测图；完整编辑覆盖期权、正股点位和公开交易逻辑。
- 「重新生成图片」按当前已编辑内容重建预测图；LOTTO YES/NO、删除和发布保持幂等。
- 乐观并发版本、审核状态和审计记录。
- Public DTO 白名单，不显示 Mentor、来源、Market、Bid、Ask 或 Parser 信息。
- Entry / Add / Update / TP / SL / Runner / Close。
- SWING / LEAPS 使用固定 persistent「查看当前持仓订单」按钮和 category-scoped ephemeral
  Active View；Swing 将 Simple / Legacy 合并在同一张卡并统一显示成本、最高 TP、当前价格与收益，
  不显示仓位；LEAPS 保留仓位与最近持仓成本；Short-Term 不提供按钮或 Active View。
- 发布后保留最终 Review 状态；交互产生的 ephemeral 回执不作为待清理频道消息。

## Legacy Swing / LEAPS Entry Plan Visual

- ENTRY / STARTER ENTRY 使用新的中文结构化交易卡。
- 期权 Premium 与正股计划点位严格分开。
- Mentor 点位优先，AXIS Stock Analyst 只补 Current、Starter、Add Zone、SL、PT 和 Fib 缺项。
- 每张有效的 SWING / LEAPS ENTRY 卡至少显示 PT1、PT2 两个目标：优先使用真实技术位；仅有
  一个可靠目标时用首段空间的 1.272 延展补第二目标；完全没有目标时只允许基于真实日 K 的
  ATR 生成两档目标。
- 自动补 PT 必须沿交易方向严格递进；不得把低于 PT1 的 CALL 目标补成 PT2/PT3，PUT 反之。
- 基于真实日 K 的确定性 PNG，不使用图片生成模型，不生成假 K 线。
- 黑色背景、K 线、EMA20、白色预测路径、蓝色 Starter、橙色 Add Zone、红色 SL、
  绿色 PT1/PT2/PT3 和灰色 Fib 0.618。
- 图和文字卡作为同一条 Discord 消息的 attachment + embed 发布。
- 缺失 Add Zone、PT3 或 0.618 时相应字段和图层自动隐藏。
- `P-*` publication reference 全部保持内部使用，会员卡不显示长短格式；公开只显示
  `ST-XXXX` / `SW-XXXX` / `LP-XXXX` 订单号。
- 新 Simple Swing、Short-Term builder/tracker 和 LEAPS 逻辑不使用本节 Legacy Swing 视觉规则。

## Simple Tracked Swing

- 新 Swing 自动标记为 `SIMPLE_TRACKED_SWING`；旧 Swing 永久标记为 `LEGACY_SWING`。
- Mentor-free、Position-free；不包含 ADD、SL、Runner、Momentum、Prediction Chart、Fib 或交易计划。
- signal-input → minimal review → publish；Category、完整合约、Entry Price 与 LOTTO 可审核。
- 独立 `SW-XXXX`，公开 Entry 使用 Short-Term 同类紧凑布局且不泄露内部 publication/event ID。
- 直接复用当前 Short-Term `ShortTermTrackingPolicy.tp_levels`；没有 Swing TP 数组副本。每笔订单
  冻结 `tracking_policy_version` 与 `price_source`，每个固定 TP 幂等发布一次。
- 独立 `SwingTrackingService`、表与 Discord loop；跨 EOD 持续追踪，保存 current/high/low、
  timestamp、error state、TP history 和每日 snapshot。
- `close SW-XXXX [@price]` 或 `close TICKER MM/DD STRIKEC/P [@price]` 进入同一 Signal Review；
  零匹配阻止、多匹配下拉选择，Manager 发布后才停止追踪。
- 当前报价失败不阻止 Close；公开 Close 以 `成本 → lifetime High 收益 → 平仓收益` 显示，
  close-reference price 与 lifetime-high price 不公开。Results 仍只使用追踪窗口内 lifetime
  verified highest return，并在终止时冻结。
- Active View 将 Simple 与 Legacy Swing 按 SW 编号合并，统一显示成本、最高 TP、Current
  price/return 与 stale fallback；不显示 lifetime High、quote timestamp、仓位或 Legacy 标签，并
  支持统一分页。
- EOD 只发布 Active Swing Summary，不关闭订单；Active Simple Swing 不进 Results。Close/Expiry
  当日进入独立 Swing review candidate，最终仍合并为单条 AXIS DAILY RESULTS。
- 重启时幂等补注册、恢复 Active tracking、修复 Trade 已关闭但 tracker 尚未结束的窗口。
- Legacy Swing 保留原 Mentor / Position / Event 业务逻辑，四笔迁移时 Active 订单不被新 tracker
  接管；只有会员 Active View 改用与 Simple Swing 相同的统一展示。

## Short-Term Automated Tracking

- SHORT_TERM automatic detection 和独立 simplified review。
- no Mentor required；不使用 Swing / LEAPS 的 Mentor Trade Flow。
- ST-XXXX 独立编号。
- Massive MarketTrackingService、market-data provider 接口、受控 fallback 和错误分类。
- 单合约 stale / unavailable / outlier / not-found 数据状态不会再升级为 Massive 服务整体 ERROR；
  订单保存连续错误次数与精确错误码，有效报价自动恢复。认证、限流和请求/响应故障继续进入
  system-alerts。
- entry_price、current_price、high/low watermark 与 policy version。
- 新订单固定 TP1–TP41：10% / 20%，然后从 50% 起每 25 个百分点提示一次直至 1000%；
  `tp_levels_hit` 保证每一级只发送一次。
- Tracking policy 按订单冻结；历史 ST_TRACKING_V2 / V3 订单继续使用各自原有点位。
- Short-Term Runner 已删除；Fast Momentum Reversal 只发送 plain TP，不推进固定 TP 编号。
- Expiry-only Tracking：Short-Term 不发送 SL、保本、trailing protection 或任何价格触发的
  tracking-stop 卡；无论回撤或隔夜跳空都持续追踪至到期。到期只在后台结束 Tracking 并进入
  Results / Audit，不向 Short-Term 频道发卡。旧 SL / Expiry 事件仅保留为内部审计历史，尚未
  发布的旧事件会在出队前自动抑制。High / Low Watermark 与 Overnight Tracking 保留。
- Massive tracking 直接使用 Review 验证并持久化的完整期权代码，兼容 `SPX` underlying /
  `SPXW` OCC root；批量中单合约失败独立写入该订单。
- 仍未到期但曾被旧价格保护停止的订单会在轮询时幂等恢复；旧公开历史保留、未公开的旧停止
  通知取消。
- LOTTO 持久化 display flag，不影响 tracking、TP、仓位或结果计算。
- Short-Term 不发送 Daily Summary；盘中报价按交易日持续更新独立 Daily High / Low 供内部
  分析，极简 official Daily Results 使用从入场到到期/停止追踪期间的全生命周期最高利润点。
  Swing / LEAPS
  Active Summary 使用 Massive 期权 Daily OHLC 正式收盘价计算，不使用盘后实时 snapshot。
- 重启恢复、节假日/交易日和定时任务安全逻辑。

说明：Production 已有 Short-Term tracking 与 Massive quote；真实 TP / Expiry / Discord /
restart 完整 E2E 仍待验收，Live Gate 仍未通过。

## Mentor / Member

- Mentor create、rename、alias、deactivate/reactivate、Trade reassign；顶层面板移除重复 Edit，
  选择 Mentor 后的详情页提供 Edit 与二次确认 Delete。只有完全没有 Draft / Trade / Analysis
  关联的 Mentor 可物理删除，已有历史时 fail closed 并写明原因；成功删除写 Audit。
- Member Control 使用 Discord 原生 searchable User Select；选择服务器成员后显示 Discord 加入
  时间、会员开始时间、状态、来源、Entitlements、Role 和到期日，并提供查看、赠送、移除。
- 底层 gift、manual extension、cancel-at-expiry、immediate revoke 能力继续保留。
- 单一 Member Role 与多 Entitlement 合并访问。
- Scheduled expiry 和持续 Role reconciliation。
- 完整 Membership Event 与 Audit。

## Free Trial / Day Pass / Monthly

- Free Trial 只由 Manager APPROVE 自动创建；用户没有 Claim / Start / Confirm Trial 操作。
- Trial 从批准后覆盖 3 个 XNYS 交易日，周末和美国市场休市日不计入；首末交易日与 expiry
  在创建时通过 `TradingCalendarService` 固化，不使用 Stripe、信用卡或自动续费。
- `membership_trial_lifetime_once(discord_user_id, trial_type)` 在数据库层保证每个 Discord User ID
  终身最多一次 `NEW_MEMBER_FREE_TRIAL`；application、approver、起止时间和状态永久保留。
- Day Pass 继续使用 XNYS 正式交易日历的一个交易日，逻辑未变。
- Trial 到期后按全部 Entitlement 决定 Member Role；没有其他访问则只移除 Member，不重新添加
  Newcomer，永久 Approval 保留。
- Monthly 自动续费、PAST_DUE、cancel-at-period-end 和 EXPIRED/CANCELLED/REVOKED lifecycle。
- 多个有效 entitlement 任一有效即保留 Member Role。
- Day Pass、Monthly、Gift 与手动 Member Role 首次激活都会在 Member Lounge @mention 欢迎；
  续费或重复 Role reconciliation 不重复发送。
- Manager extension 创建独立 MANUAL_EXTENSION，不覆盖原 entitlement。

## Newcomer Approval / Security Gate

- 首次、从未获批的用户获得唯一 `Newcomer` Role；实际 Discord overwrite 只允许只读
  `welcome`、`results`、`member-wins`，其余频道对 Newcomer 显式 DENY。
- Welcome 与后续申请流程使用纯中文，唯一 onboarding CTA 是 `申请加入 AXIS`，并明确说明
  欢迎页本身不代表已加入；来源与兴趣选择、推荐人弹窗、风险确认、社区安全协议、提交结果和
  Manager join-review 均使用中文展示，内部状态码保持不变。
- Application 保存 discovery source、optional referrer、multi-select interests、Risk / Community
  agreements 和永久 PENDING / FLAGGED / APPROVED / REJECTED 审计。
- `🛂・join-review` 只允许 Owner / Manager / AXIS BOT；APPROVE / REJECT / FLAG 幂等。
- Approval 与 Entitlement 分离并永久存在；Approved rejoin 不再申请、不再得到 Trial，按当前
  Entitlement 成为 Member 或普通 `@everyone` visitor。
- Approval 完成且 Member Role 同步成功后，Bot 在 Lobby 与 Member Lounge 分别 @mention 欢迎；
  两个 Discord message ID 独立持久化，重启只恢复缺失的一边。
- Bot 管理的 Approval Role 变更会预先标记为 expected，不再被 Discord member-update 监听器
  错误导入为永久 MANUAL Entitlement。
- `NewcomerRiskScanner` 覆盖 VERY_NEW_ACCOUNT、NEW_ACCOUNT、PREVIOUS_REJECTION、
  PREVIOUS_FLAG、TRIAL_ALREADY_USED、REJOIN_WITHOUT_APPROVAL、POSSIBLE_IMPERSONATION；protected
  identity 由 YAML 配置，风险只用于 Flag / Alert / Review，不自动 Kick / Ban / Reject。
- 风险记录按 user + risk code 持久去重，High-risk 接入 system-alerts；`NEWCOMER SECURITY`
  aggregate health、5 分钟 Role reconciliation 与 1 小时 risk scan 已实现。
- Checkout 后端同时要求永久 Approval 和已完成 Role sync，旧按钮或 URL 不能绕过 Newcomer gate。

## Stripe

- Test / Live 独立配置、Secret、URL、Product/Price binding 和数据库 namespace；Live 不回退 Test。
- `STRIPE_MODE` 环境选择和 `PAYMENTS_ENABLED` Checkout kill switch。
- 数据库驱动的 immutable Product / Price Catalog、V2 create/switch/rollback 和 signup snapshot。
- 动态 Checkout Session 和 Customer Portal。
- Stripe 签名 Webhook、严格 `event.livemode` / metadata environment 检查和环境级 provider event 幂等。
- 最小事件存储，不保留完整支付 payload。
- Checkout metadata 绑定 Discord User ID。
- Price Grandfathering：切换 current 不自动迁移既有 Monthly subscription。
- `MembershipAccessService` 统一访问决策；Discord Member Role 只是投影。
- 15 分钟 Stripe/Entitlement reconciliation、受控 repair 与 Owner-only mismatch/failure alert。
- 受保护的 Live resource setup/readiness verifier、secret-safe dual env migration 和完整 Payment runbook。
- Day Pass 与 Monthly Stripe Test Mode E2E 工具。
- Stripe Live account/KYC/payout、V1 Product/Prices、Customer Portal 和 0-blocker readiness。
- `axisdesk.fyi` 签名 webhook、最小 D1 relay queue、Bot 私密 poll / ACK / retry 与回跳页面。

## GENERAL

- Welcome、Membership、Results、Member Wins 和 Lobby Topic；Welcome 是第一个公共 AXIS
  Category 的第一个频道，Persistent Card 是默认 onboarding 入口。
- Welcome 使用 Minimal / Clean / Premium 中文内容；Persistent View 对 Newcomer 只提供
  `申请加入 AXIS`，不显示 Membership、Day Pass、Monthly 或 Stripe Checkout。
- Welcome 明确说明必须先提交加入申请；Approval 后自动提供 3 个美国股票市场交易日完整会员
  权限、无需信用卡、不会自动续费，并保留中文风险与防诈骗提示。
- Member Wins 向所有人开放发言和截图上传，并与官方 AXIS Results 严格隔离。
- AXIS / AXIS BOT / VALE 的 Public Identity Policy。
- 公开 Membership 卡片使用数据库 Price Catalog。
- Member Wins 与官方 Results 隔离。

## Analysis intake and review

- 与 Signal 完全隔离的 Source queue。
- Text / image / multi-image ANALYSIS_PARSE 和 ANALYSIS_REWRITE。
- MARKET / TICKER / SECTOR / MACRO、stance、horizon 和 missing-data safeguards。
- Mentor 下拉、关键点位逐项下拉编辑/新增/删除、编辑文字、重写文本、重新生成图片、仅归档、
  归档并发布、删除。
- A-00001 独立编号、Revision、Archive 和失败重试。
- 公开层使用中性 AXIS 口吻，不暴露第一人称、作者、Mentor、Source 或模型信息。

## Analysis Fusion / Market Intelligence

- Mentor-first / AXIS-fill-missing 字段融合。
- Raw、Mentor、Stock Analyst、Final Fused 与 Public Snapshot 分层归档。
- Key Level、Indicator、why-now 和 conflict provenance。
- 2–3 个内部 Scenario；公开只显示通过 confidence / advantage gate 的 Top Scenario。
- Stock Analyst provider injection、有限历史模式和安全 fallback。
- Analysis 不调用 GEX；独立 GEX Phase 1 仅连接 Owner-only card-testing，不连接任何交易接口。

## Prediction Chart

- Pilot-style 确定性日 K + 单一路径 renderer：使用 Stock Analyst 取得的真实 Daily OHLC、
  HLX 25 / 90 High-Low EMA 通道，在整张图上画出蓝色起点、黄色关注区、红色失效位、绿色
  突破/目标位，并在最后一根真实 K 线右侧画白色预测路径。
- Mentor 点位是数值 Source of Truth；Manager 在 Review 逐项编辑后，卡片路径与 PNG 使用同一
  份最终点位立即重建。Pilot 绘图方法属于 AXIS 自有代码，运行时不依赖 Cosmos repo。
- 输入图片仅作内部证据；明确点位与方向由 AXIS renderer 重新绘制，原图不进入 Review 或
  会员频道；缺失时只使用融合层可追溯点位。
- 不生成未来 K 线，不使用图片生成模型；真实日 K 不足时不合成蜡烛，文字归档继续可用。
- Source 图片不转发到 Review 或会员频道。
- renderer 失败不阻塞文字 Analysis 归档，支持独立重试。
- `analysis_drafts.chart_source` 可完整保存 AXIS renderer provenance，不再被旧 16 字符列宽截断。
- 重绘文件键包含草稿版本；同一 Revision 可按最新内容安全重复生成，不覆盖历史图片。

## Daily Results Review

- 实际 XNYS Close + 可配置延迟后生成每日唯一 Draft，Early Close 使用真实收盘时间。
- 当天 STOPPED 与仍在追踪的全部 Short-Term、当天终止的 Simple Swing，以及 CLOSED Legacy
  Swing / LEAPS 默认 Included；Active Simple Swing 不进入 Results。
  亏损交易不会被自动隐藏。
- Manager / Owner 可 Manage Trades、Exclude with Reason、Re-Include、Edit Display、Correct
  Result、Preview、Publish Now；普通 Edit 不修改 Trade History。
- Exclude 保存 actor / time / reason / before / after，不删除 Trade、Event、Tracking、Mentor
  Dataset 或内部 Performance。
- `16:15 ET` scheduled publish 与 Publish Now 共用幂等 claim；发布后普通操作锁定，Final
  Snapshot 不可变，Public Correction 另记 Audit。
- 全部 Short-Term Results 统一使用完整追踪周期内的期权最高价相对入场价计算收益；不使用
  当前价、停止价或单日快照。公开行显示 ST 订单号、Ticker、到期日、合约代码和收益率，
  前置 `✅` / `❌` / `➖` 状态并按订单号数字升序排列。Simple Swing 使用冻结的 lifetime
  verified highest return；Legacy Swing / LEAPS 显示原有 TP / SL 与最高收益；Daily Results
  不显示 totals。
- Short-Term 跨日 Results 启用 New-High Suppression：只有本次全生命周期最高收益严格超过
  同订单此前已发布最佳值才再次进入 Review；相同或更低收益不重复发送，新订单首次正常显示。
- Results Review 不影响 Swing / LEAPS Daily Summary；Simple Swing 的 Summary 只含 Active，
  Short-Term 继续不发 Daily Summary。

## Soft Open Reset / Production Boundary

- 受保护 reset 工具要求目标 Guild、Dry Run / Apply 环境锁、Production cutoff guard 和单次
  Audit marker。
- Reset 前生成 PostgreSQL custom dump、配置归档、SHA-256 并验证可读；备份、`.env` 与 Secret
  均不进入 Git。
- 只清除开发测试数据和 Discord Test Message，保留 Mentor、Guild Config、资源 ID、权限、
  Channel / Role 与 Persistent Message identity。
- `2026-08-31` 起真实数据永久保存，禁止第二次全量 Reset 或重新编号；所有 Synthetic Test
  只允许在 `🧪・card-testing` 使用内存 DTO。

## Testing / Operations

- Owner-only preview commands（包括 `/test-results-review`）不创建假 Trade、不写 Results。
- ERROR / WARNING / RECOVERY 持久化告警和 fingerprint 去重。
- Stripe Webhook Relay / Subscription Reconciliation 成功轮询会关闭对应失败 fingerprint 并
  发送单次恢复卡；不依赖 Relay 队列中必须存在 event。
- 数据库只读 verifier、Discord runtime verifier、Analysis Fusion verifier 和 Stripe Test verifier。
- PostgreSQL custom backup、pg_restore list、SHA-256 与双确认 restore 工具。
- Secret-safe build context、错误信息脱敏和结构化日志。

## Security boundaries

- Secret 仅从 .env 或部署 Secret Store 读取。
- .env、运行附件、备份和本地日志被 Git 忽略。
- Manager 无 Administrator / Manage Roles。
- 所有 Public DTO 使用白名单。
- Stripe 外部配置不完整时，Live activation 保持阻止。
- FEATURE_LAB_ENABLED=false、FEATURE_MODEL_AB_ENABLED=false。
- 不为会员实现自动下单，也不连接任何会员券商账户。Owner-only Moomoo layer 只在独立安全门内
  读取 Owner 账户/持仓/订单；当前 DRY_RUN 且所有 broker writes 禁用。
