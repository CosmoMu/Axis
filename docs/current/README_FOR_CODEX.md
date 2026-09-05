# AXIS — Codex Current Source of Truth

**版本：** 2026-08-30 Current Spec

**状态：** 当前唯一开发基准

**品牌：** AXIS

**标语：** Signals without the noise.

本目录只保存当前有效的产品与技术规格。后续开发、测试、Discord Bootstrap 与验收必须以这里
的十二份文档为准；历史补充规格已经归档，不得与当前规格并列解释。

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
7. 06_STRIPE_LIVE_PAYMENT_SPEC.md — Test / Live 隔离、kill switch、价格版本和 Stripe Live Gate。
8. 07_NEW_MEMBER_FREE_TRIAL_ONBOARDING_SPEC.md — Final Newcomer security isolation、Application、
   permanent Approval、automatic 3 U.S. Trading Day Trial 与 Day Pass 交易日边界。
9. 08_SIMPLE_TRACKED_SWING_SPEC.md — Swing V2、Legacy compatibility、固定 TP 追踪、手动关闭、
   Active View、EOD 与 Results 的最终规则。
10. 09_OWNER_PERSONAL_MOOMOO_EXECUTION_SPEC.md — Owner-only Moomoo 执行、DRY_RUN / LIVE
    Gate、对账、风险和控制面板的最新规则。
11. 10_GEX_EXPLORER_PHASE1_SPEC.md — `/gex` Owner-only card-testing、Massive 正式 option
    surface / 现价 / 5 分钟 K 线、当日期权成交量 GEX、Moomoo 后台影子比较、中文复合图及 Test Gate。
12. README_FOR_CODEX.md — 本入口和文档使用规则。

运行时配置仍以 config/ 为准：

- config/discord_blueprint.yaml
- config/model_routing.yaml
- config/gex_explorer.yaml
- config/llm_trade_schema.json
- config/llm_analysis_schema.json
- .env.example

正式品牌资产是 assets/axis-logo.png 和 assets/axis-brand-lockup.png。Discord Server Avatar
与 Bot Avatar 使用图标版；完整品牌展示使用 axis-brand-lockup。

## 当前执行状态

当前处于 **Core feature-complete / Production live validation**：

- Stage 1–4 的核心代码和自动化测试已经完成。
- Core Gate A 与 Analysis Gate B 已通过。
- Stripe Test Mode 历史 Day Pass / Monthly 链路已通过；Test / Live 隔离、价格版本、对账和
  kill switch 已完成。账户激活/KYC 与 Live 外部资源仍受上线清单阻止，`PAYMENTS_ENABLED=false`。
- Pre-Soft-Open backup、测试数据清理和公开编号复位已完成；2026-08-31 起真实输入均为
  Production Data，禁止再次全量 Reset 或重新编号。
- Daily Results Review / Exclude Workflow 已部署：收盘后生成 Draft，Manager 可审核公开展示，
  `16:15 ET` 幂等发布；Exclude 绝不删除或改写真实 Trade 历史。
- Short-Term Automated Tracking 的代码和测试已完成，但真实 Massive quote、tracking 注册、
  trigger、Discord 事件和重启恢复尚未完成端到端验收。
- Swing V2 Simple Tracked Swing 已完成代码、自动化测试、生产 schema migration 与 Bot runtime
  部署；四笔既有 Active Swing 已安全标记为 `LEGACY_SWING` 并继续旧流程。新 Simple Swing 的
  真实 Discord / Massive 端到端验收仍待完成。
- 当前优先级是 Live 验证、真实 Discord UX 和生产稳定性，不是新增产品模块。
- Owner-only Personal Moomoo Execution 已按最终规格实现，当前只允许 DRY_RUN；真实 OpenD
  只读对账与 SIMULATE E2E 尚未验收，LIVE broker writes 被安全门阻止。
- GEX Explorer Phase 1 已实现为 Owner-only `/gex`，只允许在 `🧪・card-testing`。当前正式
  数据全部来自 Massive；Moomoo 只在后台运行 5 分钟 K 线黑盒比较，不参与发布选择。
  系统生成中文压力/支撑/加速区复合图。
  状态仍为 TEST ONLY；未获准进入 Member Lounge。

最新事实、已知问题、测试结果和下一步分别记录在 docs/development/。状态文档可以描述部署
事实，但不得取代本目录的产品规格。

## 当前范围

当前继续维护：

- Discord Core、权限、持久化控制面板与幂等 Bootstrap
- Signal / Simple Tracked Swing / Legacy Swing / LEAPS / Short-Term Pipeline
- Short-Term Automated Tracking、LOTTO、Daily Results Review；Swing / LEAPS Active Position View
- Mentor、Newcomer、Application、Member、Free Trial、Day Pass、Monthly 与 Stripe
- Analysis Fusion、Stock Analyst、Prediction Chart 与 Analysis Archive
- Results、Card Testing、System Alerts、Backup / Restore 与生产监控
- GEX Explorer Phase 1 Owner-only card-testing 验证

当前明确不做：

- Model A / Model B 正式训练
- AXIS LAB Generate / Shadow / Champion / Challenger
- 会员自动交易或任何会员券商连接
- 除 `09_OWNER_PERSONAL_MOOMOO_EXECUTION_SPEC.md` 明确授权的 Owner-only layer 外的 Moomoo
  自动下单、模型扫描或账户能力
- 未经新规格确认的频道或产品架构扩张
- 未经 `APPROVE GEX LOUNGE LAUNCH` 的 GEX Member Lounge 开放

AXIS LAB 频道可以保留，FEATURE_LAB_ENABLED 与 FEATURE_MODEL_AB_ENABLED 必须保持 false。
`💹・moomoo-trading` 是这条 Deferred 边界中的明确 Owner-only 例外，不代表启动 Model A/B。
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
