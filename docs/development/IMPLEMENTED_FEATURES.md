# AXIS Implemented Features

## Discord / Runtime

- Guild ID 锁定和 Owner / Application 校验。
- 幂等 Role、Category、Channel、权限 reconciliation。
- 保存 Snowflake ID 后优先按 ID 复用。
- AXIS Role/Category/Channel 受控 rename；未知资源不修改。
- macOS LaunchAgent `com.axis.bot`。
- Manager-only `🤫・quiet-profits`。
- Owner-only `🚨・system-alerts` 与 `🧪・card-testing`；使用
  `DISCORD_OWNER_USER_ID` 的 user-specific overwrite，不新增 Staff Role。
- GENERAL 五条长期 Guide / Membership 消息按数据库 Message ID 幂等同步。

## Database

- Alembic revisions `0001` 到 `0014`。
- Signal、Trade、Mentor、Membership、Audit、Scheduled Job 基础表。
- `trade_publications` 命名迁移保留原表数据。
- `llm_invocations` 和 Trade Draft invocation 关联。
- Publication claim / retry / finalize 状态和 Draft/Event 唯一约束。
- Analysis Draft / Revision / immutable Archive / children / Publication 独立表。
- Trade Moomoo option code cache、只读 quote snapshot 与 daily summary publication 表。
- Analysis Market Intelligence context、Source evidence 与历史 media 兼容字段。
- Model A 训练字段：`why_now_json`、Analysis Point / Key Level source provenance。
- `input_code_counters` 事务分配 Signal / Analysis 独立的短顺序号。
- Discord-user-bound `membership_sessions`、幂等 `payment_webhook_events` 与持久化
  `system_alerts`。
- Membership 保留 ORM `user_id` API，但物理列明确命名为 `discord_user_id`；另存 provider、
  customer 与 subscription ID。

## Signal

- Text / image / multiple-image intake。
- Discord forwarded message snapshot text / image intake。
- MIME、扩展名、大小、checksum 和安全路径验证。
- Discord 图片元数据冲突时按真实签名归一化，明确伪装继续拒绝。
- Source / Draft 幂等。
- Workload Router：Signal / Repair / Analysis Parse / Rewrite。
- OpenAI Responses Structured Output。
- 默认八分之一仓位阶梯。
- 成功/失败 invocation trace。

## Signal Review

- Internal Embed 与 Public DTO Preview。
- LLM 默认 Category；低置信或解析失败时安全回退为 Swing，Manager 可在卡片顶部下拉修正。
- 紧凑审核布局，Category 与常用操作集中在同一张 persistent message。
- Mentor / Trade 选择。
- Modal 编辑。
- 乐观并发版本控制。
- Soft delete、审核 Ready、审计日志。
- Review Message ID 持久化与 Footer 恢复。

## Member Signal Publication

- 审核确认后自动创建或更新 Trade 与 Trade Event。
- `ST / SW / LP` Public Trade ID 在 Guild 锁内分配。
- 重复确认、并发确认和 Bot 重启恢复不会重复发卡。
- Entry / Add / Update / TP / SL / Runner / Close 状态流转。
- 每张会员卡片附带固定 persistent `查看当前订单`。
- Active View 使用 ephemeral response，只返回公开订单字段。

## Mentor / Membership / Results

- Persistent Mentor Control 与 Member Control 面板。
- Mentor Registry、Aliases、启停、订单查看和 Trade Mentor 修改。
- 单一 Membership、赠送、延期、到期取消、立即移除和手工 Role 同步。
- Scheduled Job 到期处理和持续 Member Role reconciliation。
- Trade Event 加权收益、关闭订单自动 Results 发布和 Message marker 恢复。
- PaymentProvider 抽象、External Checkout URL metadata、HMAC webhook 与 provider event 去重。
- ACTIVE / PAST_DUE / CANCEL_AT_PERIOD_END / EXPIRED / CANCELLED / REMOVED lifecycle；
  period-end 之前保留 Role，到期 Job 自动移除。

## GENERAL / Owner Operations

- 中文极简 Welcome 与单一 `AXIS Membership` 卡片；价格和支付/Portal URL 来自环境配置。
- Results 只保留官方统计；Lobby 为公开聊天；Member Wins 公开可见、仅会员上传，并与官方
  Results 明确隔离。
- 7 个 Owner-only Card Preview 命令使用内存 DTO，不创建假 Trade、不写 Results、不发会员频道。
- ERROR / WARNING / RECOVERY System Alert；fingerprint、first/last seen、occurrence count、
  resolved time 与通知状态持久化。

## Analysis（complete / live enabled）

- Signal / Analysis Source queue 隔离。
- Text / image / multi-image `ANALYSIS_PARSE` 与 `ANALYSIS_REWRITE`。
- Strict Schema 字段名安全清洗、PostgreSQL Invocation → Draft 顺序写入和失败草稿保留审计重试。
- Mentor select、edit、rewrite revision、archive-only、archive + publish、delete。
- MARKET / TICKER / SECTOR / MACRO 与禁止臆造事实/价格。
- 第一人称 AXIS 编辑口吻；新输入在归一化阶段处理，既有归档在审核卡/会员卡展示时兼容。
- Raw / Normalized / Public Snapshot、模型、Prompt、Schema 完整 trace。
- 无 Thread 的 Member Lounge Public Card 和失败重试。
- 单 ticker 观点合并 AXIS Stock Analyst 当前文字结构数据；输入已有预测路线/有序点位时转换为
  “预测路径（文字）”。Stock Analyst 失败时使用 LLM input 卡片继续审核。
- Analysis 审核卡与会员卡当前只发布文字；Source 原图只作内部解析证据。
- `AXIS GEX Explorer` 纯计算引擎已内置，保留未来 Moomoo option chain / Discord 频道接点。

## Operations

- 只读数据库 revision / row count / feature health check。
- PostgreSQL custom backup、list verification、SHA-256 与双确认 restore 工具。
- Dockerfile / Compose 基础部署与 Secret-safe build context。
- 后台 worker 只记录事件名与异常类型的脱敏结构化日志。
- `verify_discord_runtime.py` 只读验收 Public / Member / Manager / Owner / Bot 权限、GENERAL
  控制消息数量和 Owner 测试命令同步。
- Moomoo SDK / OpenD 版本锁定、只读行情健康检查与登录启动 LaunchAgent。
- `16:15 ET` 的 Short-term / Swing / Leaps Active + 当日 Closed 总结。
- 交易日验证、Discord marker 恢复、数据库唯一键与失败重试。

## Security

- Secret 不进入 Git 或日志。
- Public DTO 排除 Mentor、Source 元数据、提交人和 Parser 信息；当前 Analysis 不发布图片。
- Manager 无 Discord Administrator / Manage Roles。
- 外部 Checkout URL 或 webhook secret 任一缺失时，JOIN 入口安全禁用。
- AXIS LAB 功能关闭；Moomoo 仅用于 Core 只读行情，不访问账户或交易接口。
