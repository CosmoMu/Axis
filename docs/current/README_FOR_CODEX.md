# AXIS — Codex Current Source of Truth

**版本：** 2026-08-30 AXIS Current Spec v2.2

**状态：** 当前开发基准

**品牌：** `AXIS`
**标语：** `Signals without the noise.`

> 本目录是 AXIS 项目的当前唯一 Source of Truth。Codex 后续开发、测试与 Discord Bootstrap 均以本目录为准。

## 文件顺序

1. `00_AXIS_BRAND_LOCK.md` — AXIS 品牌与命名锁定。
2. `01_AXIS_CORE_MVP_SPEC.md` — 当前必须先开发的 Discord Core + Signal 系统。
3. `02_AXIS_ANALYSIS_PIPELINE_SPEC.md` — Core 完成并通过测试后开发。
4. `03_AXIS_LAB_DEFERRED_SPEC.md` — **暂不开发**；只保留未来设计。
5. `04_IMPLEMENTATION_ORDER_AND_GATES.md` — 开发顺序、测试 Gate、Codex 执行要求。
6. `05_GENERAL_MEMBERSHIP_STRIPE_SPEC.md` — 本轮 General、Membership、Stripe 与隐私锁定。
7. `config/discord_blueprint.yaml` — Discord Category / Channel / Role Blueprint。
8. `config/model_routing.yaml` — LLM 按任务路由，不使用单一硬编码模型。
9. `config/llm_trade_schema.json` — Signal 解析 Structured Output Schema。
10. `config/llm_analysis_schema.json` — Analysis 解析 Structured Output Schema。
11. `.env.example` — Secret、Stripe 与模型路由的正式配置模板。
12. `assets/axis-logo.png` — 当前 AXIS Logo。

## 当前开发范围

当前只做：

- Discord Bootstrap / Role / Permission
- Signal Pipeline
- Mentor / Member 管理
- Active Orders
- Results
- Analysis Pipeline
- 完整测试与稳定性

当前**不做**：

- Model A / Model B 正式训练
- Moomoo 模型扫描、账户读取、交易或自动下单
- AXIS LAB Generate / Shadow / Champion / Challenger
- 用户自己的自动交易
- 任何会员自动交易

Owner 已在 2026-08-29 单独授权 Core 使用 Moomoo OpenD 只读期权快照，为
`short-term` / `swing` / `leaps` 生成每日收盘总结。这不代表启动 AXIS LAB。

2026-08-30 的最新补充范围要求当前部署将该能力保持关闭。代码与历史数据保留，只有
Owner 以后明确恢复 Core 行情总结或说 `START AXIS LAB` 后再调整相应开关。

`🧪・AXIS LAB` 的三个频道可以创建，但功能保持关闭。

## LLM 模型原则

不要在代码中只使用一个 `LLM_MODEL`。

AXIS 按 workload 选择模型：

- Signal 识别是强结构化、相对简单的任务，优先使用 Terra。
- Analysis 需要理解 Mentor 观点、重组逻辑和生成高质量中文卡片，未来可以独立切换 Sol。
- **当前初版为了减少变量，Signal 与 Analysis 都先使用 Terra。**
- 以后切换 Analysis 到 Sol 只修改配置，不改业务代码。

当前建议：

```text
Signal Parse       -> gpt-5.6-terra
Signal Repair      -> gpt-5.6-terra
Analysis Parse     -> gpt-5.6-terra   # MVP initially
Analysis Rewrite   -> gpt-5.6-terra   # MVP initially

Future option:
Analysis Parse     -> gpt-5.6-sol
Analysis Rewrite   -> gpt-5.6-sol
```

每次 LLM 调用必须记录：

```text
provider
model
workload
prompt_version
schema_version
latency_ms
success / failure
```

不要把模型名称写死在 Parser Service 中。
