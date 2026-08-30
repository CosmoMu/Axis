# AXIS — Codex Current Source of Truth

**版本：** 2026-08-30 Current Spec

**状态：** 当前唯一开发基准

**品牌：** AXIS

**标语：** Signals without the noise.

本目录只保存当前有效的产品与技术规格。后续开发、测试、Discord Bootstrap 与验收必须以这里
的七份文档为准；历史补充规格已经归档，不得与当前规格并列解释。

## 必读顺序

1. 00_AXIS_BRAND_LOCK.md — 品牌、公开身份和视觉命名锁。
2. 01_AXIS_CORE_MVP_SPEC.md — Discord Core、Signal、Short-Term Tracking、Membership、
   Stripe、Results 与运营边界。
3. 02_AXIS_ANALYSIS_PIPELINE_SPEC.md — Analysis Fusion、Stock Analyst、Prediction Chart 与
   GEX 计算边界。
4. 03_AXIS_LAB_DEFERRED_SPEC.md — 未来设计，仅供边界参考，当前不得实施。
5. 04_IMPLEMENTATION_ORDER_AND_GATES.md — 实施顺序、发布 Gate 与生产验证要求。
6. 05_SIGNAL_SYSTEM_TP_LOTTO_RESULTS_SPEC.md — 最新 Short-Term TP、LOTTO、Active View、
   Daily Results 与 Daily Summary 覆盖规则。
7. README_FOR_CODEX.md — 本入口和文档使用规则。

运行时配置仍以 config/ 为准：

- config/discord_blueprint.yaml
- config/model_routing.yaml
- config/llm_trade_schema.json
- config/llm_analysis_schema.json
- .env.example

正式品牌资产是 assets/axis-logo.png 和 assets/axis-brand-lockup.png。Discord Server Avatar
与 Bot Avatar 使用图标版；完整品牌展示使用 axis-brand-lockup。

## 当前执行状态

当前处于 **Core feature-complete / Production live validation**：

- Stage 1–4 的核心代码和自动化测试已经完成。
- Core Gate A 与 Analysis Gate B 已通过。
- Stripe Test Mode 的 Day Pass / Monthly 付款链路已通过；Live Mode 仍受上线清单阻止。
- Short-Term Automated Tracking 的代码和测试已完成，但真实 Massive quote、tracking 注册、
  trigger、Discord 事件和重启恢复尚未完成端到端验收。
- 当前优先级是 Live 验证、真实 Discord UX 和生产稳定性，不是新增产品模块。

最新事实、已知问题、测试结果和下一步分别记录在 docs/development/。状态文档可以描述部署
事实，但不得取代本目录的产品规格。

## 当前范围

当前继续维护：

- Discord Core、权限、持久化控制面板与幂等 Bootstrap
- Signal / Swing / LEAPS / Short-Term Pipeline
- Short-Term Automated Tracking、LOTTO 与 Daily Results；Swing / LEAPS Active Position View
- Mentor、Member、Free Trial、Day Pass、Monthly 与 Stripe
- Analysis Fusion、Stock Analyst、Prediction Chart 与 Analysis Archive
- Results、Card Testing、System Alerts、Backup / Restore 与生产监控

当前明确不做：

- Model A / Model B 正式训练
- AXIS LAB Generate / Shadow / Champion / Challenger
- 会员自动交易或任何自动下单
- Moomoo 账户、持仓、订单和交易接口
- 未经新规格确认的频道或产品架构扩张

AXIS LAB 频道可以保留，FEATURE_LAB_ENABLED 与 FEATURE_MODEL_AB_ENABLED 必须保持 false。
只有 Owner 明确说 START AXIS LAB 后，才允许重新评估该模块。

## LLM 与数据出口

Signal 和 Analysis 当前均通过 workload router 选择模型；模型名不得硬编码在 Parser Service。
Owner 已授权 signal-input 和 analysis-input 的文字及图片发送到 OpenAI API 进行结构化解析。

每次 LLM 调用必须记录 provider、model、workload、prompt_version、schema_version、
latency_ms 和成功/失败状态。公开 DTO 不得泄露 Mentor、Source、Parser、Prompt、模型或内部
confidence。

## Secret 与文档规则

- 所有 Secret 只从 .env 或部署 Secret Store 读取。
- 不得将 Token、API Key、Webhook Secret、数据库密码或带签名 URL 写入源码、日志、文档或 Git。
- 新想法和附件先放 manually input/；吸收后移动到合适文档或资源目录，并清理已处理副本。
- 被替代规格移动到 docs/archive/ 并写明替代关系，不直接删除历史。
- 产品状态变化必须同步 docs/development/；正式需求变化必须先更新本目录。
