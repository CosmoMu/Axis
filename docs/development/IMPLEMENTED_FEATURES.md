# AXIS Implemented Features

**Updated:** 2026-08-31

本清单记录代码仓库中已经存在的能力。是否完成真实上线验收以 CURRENT_STATUS.md 和
LIVE_MODE_CHECKLIST.md 为准。

## Discord / Runtime

- Guild ID、Application ID 与 Owner ID 校验。
- Role、Category、Channel、Topic、Position 和 Permission 幂等 reconciliation。
- 保存 Snowflake ID 后优先按 ID 复用；只对 AXIS-owned 资源执行受控更新。
- Persistent View、Review Card 和 Manager 控制面板重启恢复。
- Manager-only Operations、Owner-only System Alerts 与 Card Testing。
- GENERAL Guide 依据数据库 Message ID 幂等同步。
- Manager-only `📋・results-review`、每日 Review View 与公开 Results 幂等恢复。
- macOS LaunchAgent、Dockerfile 与 Compose 基础部署。

## Database

- Alembic revisions 0001–0024；0020 清除旧 Short-Term 数据中违反 no-Mentor 边界的关联，
  0021 增加期权到期日解析 trace，0022 增加 Daily Results Review，0023 隔离 Stripe Test / Live
  Price、Entitlement、Session 与 Payment Event namespace，0024 规范新 Stripe check constraint 名称。
- Signal、Trade、Event、Publication、Mentor、Membership、Audit 和 Scheduled Job。
- Analysis Draft、Revision、Archive、Scenario、Evidence、Publication 和 provenance。
- LLM invocation provider/model/workload/prompt/schema/latency/result trace。
- Input code counters：Signal S-00001、Analysis A-00001、Public Trade ST/SW/LP。
- Membership Price Catalog、Acknowledgement、Entitlement、Payment Event 和 System Alert。
- Short-Term Tracking、Event、Daily Snapshot 与 Results 数据结构。
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
  Active View，并显示最近持仓成本；Short-Term 不提供按钮或 Active View。
- 发布后保留最终 Review 状态；交互产生的 ephemeral 回执不作为待清理频道消息。

## SWING / LEAPS Entry Plan Visual

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
- 新公开引用使用 P-0001 短编号；旧长内部 public_ref 不再显示在卡片。
- Short-Term builder、tracking 和 policy 未修改。

## Short-Term Automated Tracking

- SHORT_TERM automatic detection 和独立 simplified review。
- no Mentor required；不使用 Swing / LEAPS 的 Mentor Trade Flow。
- ST-XXXX 独立编号。
- Massive MarketTrackingService、market-data provider 接口、受控 fallback 和错误分类。
- entry_price、current_price、high/low watermark 与 policy version。
- 新订单固定 TP1–TP41：10% / 20%，然后从 50% 起每 25 个百分点提示一次直至 1000%；
  `tp_levels_hit` 保证每一级只发送一次。
- Tracking policy 按订单冻结；历史 ST_TRACKING_V2 / V3 订单继续使用各自原有点位。
- Short-Term Runner 已删除；Fast Momentum Reversal 只发送 plain TP，不推进固定 TP 编号。
- Tracking Protection（+10% / +20% 后保本，+50% 起保护前一级 TP）、High / Low Watermark、
  Overnight 和 Tracking Stop。
- LOTTO 持久化 display flag，不影响 tracking、TP、protection、仓位或结果计算。
- Short-Term 不发送 Daily Summary；停止订单只进入极简 official Daily Results。
- 重启恢复、节假日/交易日和定时任务安全逻辑。

说明：Soft Open Reset 后正式 Short-Term 与 tracking 均为 0，下一笔为 ST-0001；真实 Massive
quote / TP / Protection 触发尚未验收，Live Gate 仍未通过。

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

- 版本化风险确认与 Trial 终身一次。
- XNYS 正式交易日历：Free Trial 三个交易日、Day Pass 一个交易日。
- Monthly 自动续费、PAST_DUE、cancel-at-period-end 和 EXPIRED/CANCELLED/REVOKED lifecycle。
- 多个有效 entitlement 任一有效即保留 Member Role。
- Manager extension 创建独立 MANUAL_EXTENSION，不覆盖原 entitlement。

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

- Welcome、Membership、Results、Member Wins 和 Lobby Topic。
- Member Wins 向所有人开放发言和截图上传，并与官方 AXIS Results 严格隔离。
- AXIS / AXIS BOT / VALE 的 Public Identity Policy。
- 公开 Membership 卡片使用数据库 Price Catalog。
- Member Wins 与官方 Results 隔离。

## Analysis intake and review

- 与 Signal 完全隔离的 Source queue。
- Text / image / multi-image ANALYSIS_PARSE 和 ANALYSIS_REWRITE。
- MARKET / TICKER / SECTOR / MACRO、stance、horizon 和 missing-data safeguards。
- Mentor 下拉、编辑、重写文本、重新生成图片、仅归档、归档并发布、删除。
- A-00001 独立编号、Revision、Archive 和失败重试。
- 公开层使用中性 AXIS 口吻，不暴露第一人称、作者、Mentor、Source 或模型信息。

## Analysis Fusion / Market Intelligence

- Mentor-first / AXIS-fill-missing 字段融合。
- Raw、Mentor、Stock Analyst、Final Fused 与 Public Snapshot 分层归档。
- Key Level、Indicator、why-now 和 conflict provenance。
- 2–3 个内部 Scenario；公开只显示通过 confidence / advantage gate 的 Top Scenario。
- Stock Analyst provider injection、有限历史模式和安全 fallback。
- GEX Explorer 的 Gamma / IV fallback、Walls、Zero Gamma 与 regime 纯计算引擎。
- GEX 当前不连接 Discord 频道、账户或交易接口。

## Prediction Chart

- 确定性单一路径 renderer。
- 输入明确点位优先；缺失时只使用融合层可追溯点位。
- 不生成未来 K 线，不使用图片生成模型。
- Source 图片不转发到 Review 或会员频道。
- renderer 失败不阻塞文字 Analysis 归档，支持独立重试。

## Daily Results Review

- 实际 XNYS Close + 可配置延迟后生成每日唯一 Draft，Early Close 使用真实收盘时间。
- 当天 STOPPED 与仍在追踪的全部 Short-Term，以及 CLOSED Swing / LEAPS 默认 Included；
  亏损交易不会被自动隐藏。
- Manager / Owner 可 Manage Trades、Exclude with Reason、Re-Include、Edit Display、Correct
  Result、Preview、Publish Now；普通 Edit 不修改 Trade History。
- Exclude 保存 actor / time / reason / before / after，不删除 Trade、Event、Tracking、Mentor
  Dataset 或内部 Performance。
- `16:15 ET` scheduled publish 与 Publish Now 共用幂等 claim；发布后普通操作锁定，Final
  Snapshot 不可变，Public Correction 另记 Audit。
- 全部 Short-Term Results 统一使用当天 highest return；公开行只显示合约代码和收益率，
  不显示 ST 订单号。Swing / LEAPS 显示 TP / SL 与最高收益；Daily Results 不显示 totals。
- Results Review 不影响 Swing / LEAPS Daily Summary；Short-Term 继续不发 Daily Summary。

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
- 不实现自动下单，不读取 Moomoo 账户、持仓或订单。
