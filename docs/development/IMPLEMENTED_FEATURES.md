# AXIS Implemented Features

**Updated:** 2026-08-30

本清单记录代码仓库中已经存在的能力。是否完成真实上线验收以 CURRENT_STATUS.md 和
LIVE_MODE_CHECKLIST.md 为准。

## Discord / Runtime

- Guild ID、Application ID 与 Owner ID 校验。
- Role、Category、Channel、Topic、Position 和 Permission 幂等 reconciliation。
- 保存 Snowflake ID 后优先按 ID 复用；只对 AXIS-owned 资源执行受控更新。
- Persistent View、Review Card 和 Manager 控制面板重启恢复。
- Manager-only Operations、Owner-only System Alerts 与 Card Testing。
- GENERAL Guide 依据数据库 Message ID 幂等同步。
- macOS LaunchAgent、Dockerfile 与 Compose 基础部署。

## Database

- Alembic revisions 0001–0018。
- Signal、Trade、Event、Publication、Mentor、Membership、Audit 和 Scheduled Job。
- Analysis Draft、Revision、Archive、Scenario、Evidence、Publication 和 provenance。
- LLM invocation provider/model/workload/prompt/schema/latency/result trace。
- Input code counters：Signal S-00001、Analysis A-00001、Public Trade ST/SW/LP。
- Membership Price Catalog、Acknowledgement、Entitlement、Payment Event 和 System Alert。
- Short-Term Tracking、Event、Daily Snapshot 与 Results 数据结构。
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
- 「重新生成图片」按当前已编辑内容重建预测图；删除和发布保持幂等。
- 乐观并发版本、审核状态和审计记录。
- Public DTO 白名单，不显示 Mentor、来源、Market、Bid、Ask 或 Parser 信息。
- Entry / Add / Update / TP / SL / Runner / Close。
- 固定 persistent「查看当前订单」按钮和 ephemeral Active View；SWING / LEAPS 显示最近持仓成本。
- 发布后保留最终 Review 状态；交互产生的 ephemeral 回执不作为待清理频道消息。

## SWING / LEAPS Entry Plan Visual

- ENTRY / STARTER ENTRY 使用新的中文结构化交易卡。
- 期权 Premium 与正股计划点位严格分开。
- Mentor 点位优先，AXIS Stock Analyst 只补 Current、Starter、Add Zone、SL、PT 和 Fib 缺项。
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
- TP milestones：20% / 50%。
- Runner milestones：100% / 150% / 200% / 300% / 400% / 500% / 750% / 1000%。
- Reference Protection、Fast Momentum Reversal、Overnight、Tracking Stop。
- milestone 幂等、Active View、category close summary 和 official daily results。
- 重启恢复、节假日/交易日和定时任务安全逻辑。

说明：以上为实现清单；真实数据库当前未给 ST-0001 注册 tracking，Live 验收未通过。

## Mentor / Member

- Mentor create、rename、alias、deactivate/reactivate、Trade reassign。
- Member lookup、gift、manual extension、cancel-at-expiry、immediate revoke。
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

- 数据库驱动的 Product / Price Catalog。
- 动态 Checkout Session 和 Customer Portal。
- Stripe 签名 Webhook 和 provider event 幂等。
- 最小事件存储，不保留完整支付 payload。
- Checkout metadata 绑定 Discord User ID。
- 不可变价格快照和 Price Grandfathering。
- Day Pass 与 Monthly Stripe Test Mode E2E 工具。

## GENERAL

- Welcome、Membership、Results、Member Wins 和 Lobby Topic。
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

## Results / Testing / Operations

- Trade Event 加权收益和幂等官方 Results。
- Owner-only preview commands 不创建假 Trade、不写 Results。
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
