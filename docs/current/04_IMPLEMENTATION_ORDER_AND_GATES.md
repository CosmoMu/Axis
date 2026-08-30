# AXIS — Codex Implementation Order & Release Gates

## 0. 先读文档

按顺序：

```text
README_FOR_CODEX.md
00_AXIS_BRAND_LOCK.md
01_AXIS_CORE_MVP_SPEC.md
02_AXIS_ANALYSIS_PIPELINE_SPEC.md
03_AXIS_LAB_DEFERRED_SPEC.md
config/discord_blueprint.yaml
config/model_routing.yaml
config/llm_trade_schema.json
config/llm_analysis_schema.json
.env.example
```

仅以本包中的 AXIS 文档、配置和 Schema 作为当前 Source of Truth。

---

# Stage 0 — Repository / Guild Inventory

先只读检查：

```text
existing repo structure
existing migrations
database state
Discord Guild
Roles
Categories
Channels
existing Bot messages
```

输出 dry-run plan。

**没有确认 / APPLY_CHANGES=false 时，不修改 Guild。**

不得：

- 删除现有非 AXIS 频道；
- 自动重命名不确定资源；
- 输出 Token / API Key；
- 把 `.env` 加入 Git。

---

# Stage 1 — Infrastructure + Discord Core

实现：

```text
project skeleton
database
migrations
config loader
secret handling
model router
Discord bootstrap
roles
categories
channels
permissions
persistent views
control panels
```

创建全部当前频道，包括 Analysis 与 LAB 频道；但 Analysis 业务逻辑下一阶段，LAB 功能保持 disabled。

验证 Bootstrap 幂等后再继续。

---

# Stage 2 — Signal Pipeline

实现：

```text
📥・signal-input
OpenAI SIGNAL_PARSE
trade draft
✅・signal-review
Mentor selection
trade matching
edit / preview / publish
public card builder
trade event history
position eighths
SL / TP / Runner / Close
persistent 查看当前订单
```

当前 Signal Model：

```text
gpt-5.6-terra
```

不得硬编码；必须由 model router 解析。

---

# Stage 3 — Manager / Member / Results

实现：

```text
🧭・mentor-control
👤・member-control
Member role sync
Gift / extend / expire / revoke
📊・results
weighted trade performance
audit logs
scheduled jobs
```

---

# Gate A — Core / Signal Full Test

全部通过才允许开发 Analysis：

```text
unit tests
integration tests
security / public DTO leakage tests
Discord restart persistent button test
multi-manager concurrency test
idempotent publish test
membership expiry test
results calculation test
secret scan
```

有任何 blocking failure -> 修复后重新 Gate A。

---

# Stage 4 — Analysis Pipeline

只在 Gate A PASS 后开始：

```text
💭・analysis-input
ANALYSIS_PARSE
structured analysis
📝・analysis-review
Mentor selection
edit
rewrite
archive only
archive + publish
🛋️・member-lounge card
Analysis database
```

当前 Analysis Model：

```text
gpt-5.6-terra
```

以后可以单独改为：

```text
gpt-5.6-sol
```

不改变 Signal 模型，也不改变业务代码。

强制：

```text
no update-existing-analysis
no analysis thread
no invented facts
new viewpoint = new analysis_id
```

---

# Gate B — Analysis Full Test

全部通过：

```text
text / image / multi-image
market / ticker / sector / macro
missing data
hallucination safeguards
archive only
archive + publish
publication failure / retry
same symbol repeated viewpoints remain independent
raw / normalized / public snapshot traceability
LLM model + prompt + schema traceability
```

---

# Stage 5 — Production Stabilization

Core + Signal + Analysis 全部：

```text
error handling
retry policy
observability
structured logs
backup / restore
migration rollback
docker / deploy docs
final acceptance test
Moomoo OpenD read-only Core quote health
16:15 ET category summaries + holiday/idempotency safety
```

完成后停止。

---

# Stage 6 — AXIS LAB (DO NOT START NOW)

当前任务明确不开发。

必须满足两个条件：

```text
1. Gate A + Gate B + Production Stabilization 全部 PASS
2. Owner 以后明确要求“开始开发 AXIS LAB”
```

否则：

```text
FEATURE_LAB_ENABLED=false
FEATURE_MODEL_AB_ENABLED=false
```

当前部署必须同时保持：

```text
FEATURE_LAB_ENABLED=false
FEATURE_MODEL_AB_ENABLED=false
FEATURE_MOOMOO_ENABLED=false
```

旧 Core 每日总结实现保留但不启动。AXIS LAB 仍只保留频道与未来 Spec。
