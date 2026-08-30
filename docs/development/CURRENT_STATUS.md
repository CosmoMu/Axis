# AXIS Current Development Status

**更新：** 2026-08-29

**Database:** `20260829_0005`

**Discord Bootstrap:** `REUSE=26 / CREATE=0 / UPDATE=0 / BLOCK=0`

**AXIS LAB:** DEFERRED

## Stage 1 — Infrastructure: PARTIAL

Implemented:

- Python 3.12 / discord.py / SQLAlchemy / Alembic / PostgreSQL。
- Secret-only configuration、safe LaunchAgent deployment。
- Discord inventory、dry-run、三重 Apply Gate、saved-ID reconciliation。
- 19 个 v2 Channel、Manager / Member Role 与权限。
- Workload Model Router 和 LLM invocation trace schema。
- Persistent Card Review Views。

Missing:

- Mentor / Member 长期控制面板。
- Docker / production deployment target。
- 完整 backup / restore 自动化。

Tests: Router、Bootstrap、DB metadata 和安全约束已覆盖。

## Stage 2 — Signal Pipeline: COMPLETE

Implemented:

- Text / PNG / JPEG / WEBP / multi-image intake。
- 安全附件落盘、checksum 与幂等 Source Message。
- OpenAI Responses API、Structured Output、`SIGNAL_PARSE` routing。
- Draft、默认仓位阶梯、missing fields、failure Draft。
- Card Review、Mentor/Trade 选择、编辑、Public Preview、并发版本与审计。
- LLM provider/model/workload/Prompt/Schema/latency/result trace。
- 确认后创建或更新 Trade，并写入不可重复的 Trade Event。
- 数据库预约、Discord marker 恢复和事务 finalize 组成的幂等会员卡片发布。
- Public DTO 白名单边界与固定 `axis:active:*:v1` persistent button。
- `查看当前订单` ephemeral Active View；关闭、清仓和 Cancel 订单自动排除。

Needs migration: none after `0005`。

## Stage 3 — Mentor / Member / Results: NOT STARTED

Implemented: 基础表和 Discord 预留频道。

Missing:

- Mentor Control。
- Member gift / extend / expire / revoke 与 Role sync。
- 加权 Results 和 scheduled jobs。

## Stage 4 — Analysis Pipeline: NOT STARTED

Implemented: 独立规格、Schema、Router workload 和 disabled Discord channels。

Missing: 所有 Analysis 数据表与业务逻辑。

Gate: Gate A 通过前不得开始。

## Stage 5 — Stabilization: PARTIAL

Implemented: LaunchAgent、错误信息脱敏、基础重试、测试和 Secret scan。

Missing: production observability、backup / restore、Docker、完整 rollback rehearsal。

## AXIS LAB — DEFERRED

频道已创建且 Owner-only。以下功能保持关闭且未实现：

- Model A / B
- Moomoo
- Generate / Shadow / Champion / Challenger
- 自动交易
