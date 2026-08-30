# AXIS v2.1 — Stage 0 Inventory / Diff / Implementation Plan

**日期：** 2026-08-29  
**目标 Guild：** `AXIS (1543309921066684567)`  
**状态：** Stage 0 只读盘点完成；Discord 服务器修改数为 **0**。  
**Source of Truth：** `docs/spec/current/`

## 1. 安全结论

- Guild ID、Owner ID、Bot User ID 与本地配置一致。
- dry-run 没有 `BLOCK`。
- 本次命令没有 `--apply`，没有创建、改名、移动或删除任何 Discord 资源。
- 计划只匹配 `config/discord_ids.json` 已登记的 AXIS Snowflake ID；未知资源不进入
  UPDATE。
- Bootstrap 不包含删除或自动移动逻辑。
- Secret 继续只从本地 `.env` 读取；盘点、报告与日志均未输出 Secret 值。

## 2. Repository Inventory

当前代码结构：

```text
app/
├─ bot/                    Discord client、Bootstrap、Signal 与 Card Review
├─ db/                     SQLAlchemy models、session 与初始化
├─ domain/                 enum / 领域常量
├─ integrations/           当前 OpenAI trade parser
└─ services/               attachment、signal、draft、review service

config/
├─ discord_blueprint.yaml
├─ llm_trade_schema.json
├─ llm_analysis_schema.json
├─ llm_trade_prompt.txt
├─ model_routing.yaml
└─ .env.example

docs/
├─ spec/current/           v2.1 唯一正式规格
├─ development/            阶段盘点与实施记录
├─ operations/             运维手册
└─ AXIS_MVP_SPEC.md        已标记为历史文档

migrations/versions/
├─ 20260829_0001_initial_axis_schema.py
├─ 20260829_0002_trade_draft_source_unique.py
└─ 20260829_0003_admin_review.py

assets/
├─ axis-logo.png           当前正式路径
└─ axis-brand-lockup.png   同一用户提供资产的原始文件名
```

已实现并部署：

- PostgreSQL 基础 Schema 与 Alembic。
- Discord 幂等 Bootstrap、安全附件收件和 Signal Input。
- OpenAI Responses API 结构化 Trade Draft。
- Manager Card Review：Mentor/Trade 选择、编辑、公开预览、并发版本控制、软删除与审计。
- Review message 崩溃窗口恢复和 persistent component registration。

当前未实现：

- workload router 的运行时代码和 `llm_invocations` 持久化。
- Trade 的正式会员发布、`查看当前订单` 数据查询。
- Mentor Control、Member Control、Results。
- Analysis 业务 Domain（按 Gate 要求暂不开始）。
- AXIS LAB 业务（明确禁止开始）。

## 3. Database Inventory

当前 Alembic revision：

```text
20260829_0003
```

当前 public tables（不含业务外 Schema）：

```text
alembic_version
audit_logs
guild_config
membership_events
memberships
mentor_aliases
mentors
public_messages
scheduled_jobs
source_attachments
source_messages
subscriptions
trade_drafts
trade_events
trades
```

只读记录统计：

- `source_messages`：1
- `trade_drafts`：1
- 已登记 Review Message：1
- 公开会员 Message：0
- 已登记 Mentor / Member 长期控制面板：0

与 v2.1 的主要 Schema 差异：

- 缺少 `llm_invocations`。
- 当前表名为 `public_messages`，规范名称为 `trade_publications`；迁移前需决定兼容改名
  或保留表并建立清晰领域映射，不能直接破坏已部署数据。
- Analysis 独立表尚未创建；必须等 Gate A 通过。

## 4. Runtime Inventory

- macOS LaunchAgent：`com.axis.bot`
- 状态：`running`
- 当前运行实例已能处理 Signal Draft 与 Manager Review。
- 已部署 Parser 仍读取旧的 `LLM_API_KEY / LLM_MODEL`。这是 Stage 1 的已知兼容差异；
  目标接口是 `OPENAI_API_KEY + workload router`。

## 5. Discord Guild Inventory

当前 Role：

```text
AXIS BOT
管理员
会员
@everyone
```

当前结构：

```text
⬛・AXIS
├─ 👋・welcome
├─ 💳・membership
├─ 📊・results
├─ 💬・lounge
└─ 🏆・member-wins

🟢・SIGNALS
├─ ⚡・short-term
├─ 〽️・swing
├─ ♾️・long-term
└─ 💬・member-lounge

⚙️・OPERATIONS
├─ 📥・signal-input
├─ ✅・review-desk
├─ 🧭・mentor-control
└─ 👤・member-control

🧪・AXIS LAB
├─ 🟢・model-signals
└─ 🗂️・trade-history
```

## 6. v2.1 Discord Dry-run Diff

汇总：

```text
REUSE  10
CREATE  3
UPDATE 12
BLOCK   0
```

计划改名（只针对已登记 AXIS ID）：

| 类型 | 当前 | 目标 |
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

计划创建：

- `💭・analysis-input`（Manager-only；业务功能关闭到 Gate A 通过）
- `📝・analysis-review`（Manager-only；业务功能关闭到 Gate A 通过）
- `🧬・mentor-status`（Owner/Bot-only；AXIS LAB 功能关闭）

明确不做：

- 不删除任何 Role、Category、Channel 或 Bot Message。
- 不移动任何频道。
- 不改名任何未登记的资源。
- 不启动 Analysis 业务。
- 不启动 AXIS LAB 业务。

## 7. Implementation Plan

### Stage 1A — Apply Discord Core（等待 Owner 确认）

1. 临时打开 Discord 三重写入 Gate。
2. 使用 `--allow-axis-renames --apply --confirm-guild-id 1543309921066684567`。
3. 写回新建频道 ID。
4. 立即恢复只读 Gate。
5. 再运行普通 dry-run；验收目标为 `CREATE=0 / UPDATE=0 / BLOCK=0`。
6. 验证 Role hierarchy、Manager/Member/Owner/Bot 可见性和现有 Review Message。

### Stage 1B — Model Router / Invocation Trace

1. 实现 `SIGNAL_PARSE / SIGNAL_REPAIR / ANALYSIS_PARSE / ANALYSIS_REWRITE` workload 配置解析。
2. 支持环境变量按 workload 覆盖，不在 Parser Service 硬编码 model。
3. 新增 `llm_invocations` migration 与 model。
4. 保存 provider、实际 model、workload、Prompt/Schema 版本、latency、success/failure。
5. 为旧本地 Key 名提供一次性兼容读取，但不输出、复制或提交 Secret。
6. 迁移现有 Signal Parser 到 router，并执行回归测试。

### Stage 2 — Finish Signal Pipeline

1. 完成 Trade publication 和幂等确认发布。
2. 实现 Public DTO 白名单和 Signal Card。
3. 实现 persistent `查看当前订单` 与 Active View。
4. 覆盖仓位事件、SL/TP/Runner/Close、重复点击与 multi-manager 并发测试。

### Stage 3 — Manager / Member / Results

依次实现 Mentor Control、Member Control / Role sync、到期任务、加权 Results 与完整审计。

### Gate A

Core、Signal、Manager、Member、Results 的 unit / integration / security / restart /
concurrency / idempotency / secret scan 全部通过后，才允许开始 Analysis。

### Stage 4 / Gate B / Stabilization

按独立 Domain 实现 Analysis 的 Parse、Review、Archive Only、Archive + Publish；不更新已有
观点，不创建 Thread。Gate B 通过后再做生产稳定性。

`AXIS LAB` 保持 deferred；没有 Owner 后续明确指令时永远不进入实现阶段。

## 8. Apply Gate

Stage 0 已完成，但 Discord Apply 尚未授权于本轮执行。下一步必须由 Owner 确认上述
`12 UPDATE + 3 CREATE` 计划后，才可修改 Guild。
