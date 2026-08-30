# AXIS Implemented Features

## Discord / Runtime

- Guild ID 锁定和 Owner / Application 校验。
- 幂等 Role、Category、Channel、权限 reconciliation。
- 保存 Snowflake ID 后优先按 ID 复用。
- AXIS Role/Category/Channel 受控 rename；未知资源不修改。
- macOS LaunchAgent `com.axis.bot`。
- Manager-only `🤫・quiet-profits`。

## Database

- Alembic revisions `0001` 到 `0004`。
- Signal、Trade、Mentor、Membership、Audit、Scheduled Job 基础表。
- `trade_publications` 命名迁移保留原表数据。
- `llm_invocations` 和 Trade Draft invocation 关联。

## Signal

- Text / image / multiple-image intake。
- MIME、扩展名、大小、checksum 和安全路径验证。
- Source / Draft 幂等。
- Workload Router：Signal / Repair / Analysis Parse / Rewrite。
- OpenAI Responses Structured Output。
- 默认八分之一仓位阶梯。
- 成功/失败 invocation trace。

## Card Review

- Internal Embed 与 Public DTO Preview。
- Mentor / Trade 选择。
- Modal 编辑。
- 乐观并发版本控制。
- Soft delete、审核 Ready、审计日志。
- Review Message ID 持久化与 Footer 恢复。

## Security

- Secret 不进入 Git 或日志。
- Public DTO 排除 Mentor、Source、原图、提交人和 Parser 信息。
- Manager 无 Discord Administrator / Manage Roles。
- AXIS LAB 功能关闭。
