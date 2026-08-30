# AXIS v1 → v2 Implementation Plan

**状态：** COMPLETE — 2026-08-29

**原则：** 增量迁移、保留数据、保留 Discord ID、每阶段可验证。

## Phase 1 — Documentation Reconciliation

1. 将唯一规格移动到 `docs/current/`。
2. 将旧规格归档到 `docs/archive/v1/`。
3. 建立 `docs/config-reference/` 镜像与同步测试。
4. 创建 Audit、Plan、Current Status、Implemented Features、Known Issues、Test Status。
5. 根 README 只保留入口信息。

验收：旧文档仍可访问；所有当前入口只指向 `docs/current/`。

## Phase 2 — Config / Model Router

1. 新增严格解析的 workload router。
2. Model 解析顺序：workload env override → YAML workload → YAML default。
3. Service 只提交 workload，不提交 model name。
4. 正式 Secret 名使用 `OPENAI_API_KEY`；迁移窗口兼容 `LLM_API_KEY`。
5. 删除运行路径对单一 `LLM_MODEL` 的依赖。

验收：单元测试覆盖每个 workload、override、无效配置与 fallback。

## Phase 3 — Database Migration

1. Alembic 新建 `llm_invocations`。
2. 保存 provider、model、workload、Prompt/Schema version、latency、success、
   error_type、provider response ID 和 entity references。
3. 安全 rename `public_messages` → `trade_publications`，同步 ORM、索引与约束。
4. 不 backfill 无法证明的 latency / result；旧 Draft JSON 原样保留。

验收：upgrade / downgrade 测试、现有记录数量不变、应用 metadata 与数据库一致。

## Phase 4 — Signal Integration

1. `OpenAITradeParser` 接收 Router 决策，不硬编码具体模型。
2. 成功和失败调用都写 `llm_invocations`。
3. Draft 保存 invocation 关联，并保留公开安全边界。
4. 重新部署 Bot，用现有 Draft 验证无重复处理。

## Phase 5 — Discord Reconciliation

1. 只读 inventory + dry-run。
2. 只 rename 已登记 AXIS Role / Category / Channel。
3. 创建缺失 Analysis / LAB 预留频道。
4. 保留 `🤫・quiet-profits`。
5. 恢复 `APPLY_CHANGES=false` / `DRY_RUN=true`。
6. 重跑 dry-run，目标为 `CREATE=0 / UPDATE=0 / BLOCK=0`。

## Phase 6 — Regression / Status

1. Ruff、unit/integration/security tests。
2. Secret scan。
3. live DB revision / row-count 验证。
4. Discord 权限与 persistent Review Message 验证。
5. 更新四份 development 状态文档。
6. 清理 `manually input/` 中已吸收的临时文件。

## Rollback

- 文档：Git revert。
- Model Router：保留 v1 env fallback 一个迁移窗口。
- Database：Alembic downgrade，不删除业务记录。
- Discord：保留相同 Resource ID；如需回滚只恢复已登记 AXIS 名称，不删除频道。

## Migration 完成后的继续位置

返回 Stage 2，完成会员发布、Trade Event、Public Card 和 persistent
`查看当前订单`。Gate A 前不开始 Analysis；任何时候都不开始 AXIS LAB。

## Completion Record

- Phase 1：完成。当前规格位于 `docs/current/`，v1 已归档。
- Phase 2：完成。业务运行路径不再依赖单一 model；旧 Env Key 只作 fallback。
- Phase 3：完成。PostgreSQL revision `20260829_0004`，原有 Source / Draft 保留。
- Phase 4：完成。Signal Parse 成功/失败路径均写 invocation；42 项测试通过。
- Phase 5：完成。Discord `REUSE=26 / CREATE=0 / UPDATE=0 / BLOCK=0`。
- Phase 6：完成。Bot 正常运行，Review Message 与 6 个 persistent component 保留，
  Secret scan 通过。

Migration 到此停止，不会借此开始 Analysis 或 AXIS LAB。下一开发位置是 Stage 2 的会员
发布与 `查看当前订单`。

## Stage 2 Continuation Record

- 会员发布、Trade Event、Public Card 与 persistent `查看当前订单` 已完成。
- PostgreSQL revision `20260829_0005` 增加 publication lifecycle 与幂等约束。
- 下一开发位置为 Stage 3：Mentor Control、Member Control、Results。

## Stage 3 Continuation Record

- Mentor Control、Member Control、Member Role sync 和 Scheduled expiry 已完成。
- Weighted official Results 与幂等频道发布已完成。
- PostgreSQL revision `20260829_0006` 增加 Results publication fields。
- 下一位置为 Core Gate A；Gate A PASS 前不启用 Analysis。

## Stage 4 Continuation Record

- Core Gate A 已通过，Analysis 独立 Domain 与 automated Gate B 已完成。
- PostgreSQL revision `20260829_0007` 增加 Analysis Draft / Revision / Archive / Publication。
- 69 项自动化测试通过，0007 代码已以 Analysis disabled 状态部署。
- Live enable 等待 Owner 对 `analysis-input` → OpenAI 的独立数据出口授权。
- AXIS LAB 未开始，三个相关 feature flag 继续为 false。
