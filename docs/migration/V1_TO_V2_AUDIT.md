# AXIS v1 → v2 Migration Audit

**日期：** 2026-08-29  
**审计基线：** commit `8e6abce`  
**目标：** 在保留现有代码、数据和 Discord Resource ID 的前提下迁移到 AXIS v2。

## 1. 已经符合 v2

### Brand Rename

- 用户可见品牌、Python project、LaunchAgent 和日志前缀均为 `AXIS` / `AXIS BOT`。
- 全仓库没有有效代码使用 `AXIS DESK`、`AxisDesk`、`axis-desk`、
  `axis_desk` 或 `axis desk`。
- Python package 是 `app`，project name 是 `axis`，不需要破坏性 import rename。
- 正式 Logo 是用户提供的 `assets/axis-logo.png`；内容与原
  `axis-brand-lockup.png` 一致。

### Domain Logic

- Signal Input、Trade Draft 与 Card Review 已是独立 Signal Domain。
- Analysis 尚未实现，没有塞进 `trades` 或 `trade_drafts`。
- Public DTO 已使用白名单，测试覆盖 Mentor / Source 泄漏。
- 默认仓位阶梯为 Entry 1/8、First Add 1/4、Second Add 1/2、Third Add 3/4。
- LLM 只创建 Draft，不直接发布。

### Data / Runtime

- PostgreSQL 与 Alembic 已在使用；当前 revision 为 `20260829_0003`。
- Discord Role、Category、Channel 和 Review Message ID 均已持久化。
- Signal Source、Attachment、Draft、Audit 数据可以原样保留。
- AXIS LAB 功能没有实现，Feature Flags 保持关闭。

## 2. 需要 Rename

### Discord Migration

仅通过已登记 Snowflake ID 修改：

| 资源 | v1 当前名称 | v2 目标名称 |
|---|---|---|
| Role | 管理员 | Manager |
| Role | 会员 | Member |
| Category | ⬛・AXIS | ⬛・GENERAL |
| Category | 🟢・SIGNALS | 🟢・MEMBERS |
| Category | ⚙️・OPERATIONS | ⚙️・MANAGER |
| Channel | 💳・membership | 💳・subscriptions |
| Channel | 💬・lounge | 💬・lobby |
| Channel | ♾️・long-term | ♾️・leaps |
| Channel | 💬・member-lounge | 🛋️・member-lounge |
| Channel | ✅・review-desk | ✅・card-review |
| Channel | 🟢・model-signals | 🟢・lab-signals |
| Channel | 🗂️・trade-history | 🗂️・lab-history |

缺失频道：

- `💭・analysis-input`
- `📝・analysis-review`
- `🧬・mentor-status`

`🤫・quiet-profits` 已按 Owner 后续要求创建并纳入 v2 Blueprint。

### Documentation Migration

- `docs/spec/current/` → `docs/current/`
- `docs/AXIS_MVP_SPEC.md` → `docs/archive/v1/AXIS_MVP_SPEC.md`
- 根目录新增精简 `README.md`；`README_FOR_CODEX.md` 仅保留兼容入口。

## 3. 需要业务逻辑修改

### Config Migration

- 移除业务层对单一 `settings.llm_model` 的依赖。
- 新增 workload router：
  `SIGNAL_PARSE`、`SIGNAL_REPAIR`、`ANALYSIS_PARSE`、`ANALYSIS_REWRITE`。
- 当前所有 workload 使用 `gpt-5.6-terra`；Analysis 可通过配置单独切换。
- `OPENAI_API_KEY` 成为正式 Key 名；旧 `LLM_API_KEY` 仅临时 fallback。

### LLM Traceability

每次调用必须保存 provider、实际 model、workload、Prompt/Schema version、latency、
success 和 error_type。当前只在 Draft JSON 中保存部分 parser metadata，不满足 v2。

### Signal Completion

现有 Signal Input / Parse / Review 可保留；会员正式发布、Trade Event、Active View 与
`查看当前订单` 尚未实现，属于后续 Stage 2，不在 migration 中重写。

## 4. 需要 Database Migration

- 新建 `llm_invocations`，不修改或伪造旧调用历史。
- Trade Draft 需要关联对应 invocation，或通过 source / entity reference 可追溯。
- `public_messages` 与 v2 名称 `trade_publications` 不一致。
  使用 Alembic rename 保留数据；禁止 drop/recreate。
- Analysis Domain 表等 Gate A 通过后再创建。

## 5. 已废弃但暂时保留的兼容项

- `LLM_API_KEY` / `LLM_MODEL`：只在迁移窗口 fallback，并产生明确 deprecated 行为。
- 根目录 `README_FOR_CODEX.md`：只作为旧工具入口。
- `assets/axis-brand-lockup.png`：保留用户原始资产名；正式配置使用 `axis-logo.png`。
- v1 Discord 名称：只存在于 migration fixture / audit / archive，不得用于新资源。

## 6. 不应该修改

- 已有 UUID、Trade / Draft / Source / Audit / Membership 数据。
- Discord Guild ID、Resource ID、Review Message ID。
- `axis:active:*:v1`：`v1` 是 persistent component 协议版本，不是品牌版本。
- 已执行的 Alembic revision 名称 `0001/0002/0003`。
- Signal 与 Analysis 的 Domain 边界。
- AXIS LAB deferred 规则和关闭状态。

## 7. 风险

- Env Key 直接切换会导致正在运行的 Bot 失去 OpenAI 配置，必须先兼容读取再部署。
- 表改名必须与 ORM 同一 release 部署，且 migration 必须可回滚。
- Discord rename 只能作用于 `discord_ids.json` 精确登记的资源。
- 文档配置镜像可能漂移，必须有 byte-equality test。
- 新 Analysis / LAB 频道存在不代表业务可以启用。
