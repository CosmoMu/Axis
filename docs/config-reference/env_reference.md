# AXIS Environment Reference

正式模板：`.env.example`。真实值只放本地 `.env` 或部署 Secret Store。

## Discord

- `DISCORD_BOT_TOKEN`：Discord Bot Secret。
- `DISCORD_APPLICATION_ID`：AXIS BOT Application ID。
- `DISCORD_GUILD_ID`：唯一目标 Guild。
- `DISCORD_OWNER_USER_ID`：Owner User ID。
- `APPLY_CHANGES` / `DRY_RUN`：Discord 三重写入 Gate 的环境锁。

## Database

- `DATABASE_URL`：必须使用 `postgresql+asyncpg://`。

## Public Identity / Membership / Stripe

- `PUBLIC_OPERATOR_NAME=VALE`：匿名 AXIS Brand Persona；不是专业履历。
- `PUBLIC_IDENTITY_FORBIDDEN_TERMS`：额外的私有身份阻止词，逗号分隔。
- `NEW_MEMBER_FREE_TRIAL_ENABLED=true`：控制新会员 Free Trial 领取入口。
- `NEW_MEMBER_FREE_TRIAL_TRADING_DAYS=3`：批准时通过 XNYS `TradingCalendarService` 固化三个
  交易日；周末与美股休市日不计入。
- `NEW_MEMBER_FREE_TRIAL_AUTO_OFFER=true`：成员加入时只检查领取资格；不会自动发 Role、
  自动领取或重置 Trial。
- `NEW_MEMBER_FREE_TRIAL_DM_ENABLED=false`：默认不发送新会员私信；持久 Welcome 卡片是
  默认入口。
- `NEW_MEMBER_FREE_TRIAL_CALENDAR_DAYS`：已废弃且运行时忽略，只允许在短期部署迁移中存在。
- `STRIPE_ENABLED=false`：控制 Stripe Gateway / Webhook 基础设施。
- `STRIPE_MODE=test|live`：选择当前运行时环境；不会让一套 Key 覆盖另一环境。
- `PAYMENTS_ENABLED=false`：只停止新 Checkout，不停止 Webhook、Portal、既有订阅同步或
  reconciliation。
- `STRIPE_TEST_*` 与 `STRIPE_LIVE_*`：Secret、Publishable Key、Webhook Secret、返回 URL、
  Product / Price ID 和 Pricing Version 全部分离。Secret 只放 `.env` / Secret Store。
- `STRIPE_LIVE_PRIVACY_REVIEWED=false`：只有公开 Privacy、Refund、Cancellation 页面完成
  人工复核后才改为 `true`。
- `*_DAY_PASS_PRICING_VERSION` / `*_MONTHLY_PRICING_VERSION`：必须对应当前环境
  `membership_prices` 中的不可变版本。
- `PAYMENT_WEBHOOK_HOST` / `PAYMENT_WEBHOOK_PORT`：Webhook listener 绑定地址。
- `MEMBERSHIP_SESSION_TTL_MINUTES`：Discord User ID 绑定 session 的有效期。

Checkout 为动态 Stripe Session，metadata 包含 `discord_user_id + membership_type +
pricing_version + membership_session_id + environment`。Monthly 同步写入 Subscription
metadata。Webhook 验证 `Stripe-Signature` 和 Event `livemode`，不使用 email、username 或
显示名推断身份。旧的单环境 `STRIPE_*` 变量仅作为 Test-only 部署迁移兼容，Live 永不读取。

## Production Alerts

- `SYSTEM_ALERT_CHECK_SECONDS`：Owner-only 健康检查周期；正常状态不发送消息。

## Soft Open / Production Boundary

- `PRODUCTION_DATA_START_DATE=2026-08-31`
- `PRODUCTION_DATA_START_TIMEZONE=America/New_York`
- `DEPLOYMENT_STAGE=SOFT_OPEN`：Soft Open 是 Production，不是 Test / Paper。
- `SOFT_OPEN_RESET_DRY_RUN=true` / `SOFT_OPEN_RESET_APPLY=false`：受保护 reset gate。正式
  Apply 已在 2026-08-30 完成，Audit marker 会拒绝第二次 Apply；不要把 Apply 永久打开。

## Daily Results Review

- `RESULTS_REVIEW_ENABLED=true`
- `RESULTS_REVIEW_DRAFT_DELAY_MINUTES=1`：从当天真实 XNYS close 起算，包含 Early Close。
- `RESULTS_FINAL_PUBLISH_TIME=16:15`
- `RESULTS_TIMEZONE=America/New_York`

Review 只影响当天 Public Results display；Exclude 不删除真实历史。配置时间不得在 Service
内部另行硬编码。

## OpenAI / Workload Router

- `OPENAI_API_KEY`：OpenAI Secret。
- `LLM_ROUTING_CONFIG`：默认 `config/model_routing.yaml`。
- `LLM_DEFAULT_MODEL`：未单独覆盖时的默认模型。
- `LLM_SIGNAL_MODEL`：`SIGNAL_PARSE` override。
- `LLM_SIGNAL_REPAIR_MODEL`：`SIGNAL_REPAIR` override。
- `LLM_ANALYSIS_MODEL`：`ANALYSIS_PARSE` override。
- `LLM_ANALYSIS_REWRITE_MODEL`：`ANALYSIS_REWRITE` override。
- `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES`：请求策略。
- `LLM_PROMPT_PATH`：Signal Parse Prompt。
- `LLM_ANALYSIS_PROMPT_PATH`：Analysis Parse / Rewrite no-invention Prompt。

`LLM_API_KEY` 与 `LLM_MODEL` 仅在 v1 → v2 迁移窗口作为 deprecated fallback，完成
部署迁移后移除。业务 Service 不得读取具体 model 环境变量。

## Features

- `FEATURE_SIGNAL_ENABLED=true`
- `FEATURE_ANALYSIS_ENABLED=false` 是新环境的安全模板默认值。当前本机已取得 Owner 对
  `analysis-input` → OpenAI 的单独授权，因此实际 Secret 环境中为 `true`；不要把真实
  `.env` 同步到文档或 Git。
- `FEATURE_LAB_ENABLED=false`
- `FEATURE_MODEL_AB_ENABLED=false`
- `FEATURE_MOOMOO_ENABLED=false`：旧 Moomoo 行情健康开关；不启动 Model Scanning。
- `FEATURE_PERSONAL_EXECUTION_ENABLED=false`：Owner-only Personal Execution 总开关，模板默认关。
- `GEX_EXPLORER_ENABLED=false`：`/gex` kill switch；Phase 1 生产 Secret 可显式开启。
- `GEX_EXPLORER_MODE=TEST`：Phase 1 只允许 Owner 在 card-testing 使用；当前 startup gate
  拒绝 `MEMBER_LOUNGE`。
- `GEX_EXPLORER_POLICY=config/gex_explorer.yaml`：expiry、regime、cache、limit、freshness、
  5 分钟 K 线数量、V7 分类权重和 renderer policy 单一来源。GEX 期权表面使用 Massive，
  盘中 K 线使用现有 `MOOMOO_OPEND_HOST` / `MOOMOO_OPEND_PORT`，不需要新 Secret。
- `FEATURE_DAILY_SUMMARY_ENABLED=true`：启用收盘总结与 Daily Results；Swing / LEAPS Active
  Summary 使用 Massive 当日正式期权收盘价，Short-Term 使用独立 Tracking 数据。
- `FEATURE_SHORT_TERM_TRACKING_ENABLED=false`：安全默认。只有 Massive Secret 配置完成后
  才启用实时 Short-Term 轮询；Review、发布与 Tracking 注册本身仍可工作。
- `FEATURE_AXIS_STOCK_ANALYST_ENABLED=false`：新环境安全默认；启用后单 ticker Analysis
  会调用 AXIS 自有 Stock Analyst，通过本机 Moomoo OpenD 读取日 K 并生成文字结构观察。
  当前不会生成或发布 Analysis 图片；未来 Massive API 接入另行启用。

## AXIS Market Intelligence

- `AXIS Stock Analyst`：当前已接 Analysis Pipeline。
- `AXIS GEX Explorer`：Phase 1 已接 Owner-only card-testing Slash Command；Massive 是 GEX
  surface、现价与 5 分钟 K 线正式 provider，Moomoo 仅运行后台影子比较。V7 使用专业
  Strike × Expiration Ladder 与 shared intraday classifier。仍是 TEST ONLY、
  read-only，未开放 Member Lounge，也不连接交易接口。

两个模块都在 AXIS 仓库的 `app/market_intelligence/` 内运行，不 import、启动或读取 Cosmos
仓库。旧 `FEATURE_COSMOS_STOCK_ANALYST_ENABLED` 仅保留一版配置兼容，新环境不得继续使用。

## Moomoo Market Data and Owner-only Personal Execution

- `MOOMOO_OPEND_HOST=127.0.0.1`
- `MOOMOO_OPEND_PORT=11111`
Stock Analyst 仍只读日 K。Owner-only Personal Execution 额外使用：

- `PERSONAL_EXECUTION_MODE=DRY_RUN|LIVE`
- `PERSONAL_BROKER_ENV=SIMULATE|REAL`
- `PERSONAL_AUTO_TRADING_ENABLED=false`
- `PERSONAL_DRY_RUN_VALIDATED=false`
- `MOOMOO_ACC_ID` / `MOOMOO_SECURITY_FIRM`（Secret Store only）
- `PERSONAL_RECONCILE_SECONDS=15`
- `PERSONAL_POSITION_EQUITY_PCT=0.10`、预算 `$200–$500`
- `PERSONAL_ENTRY_MAX_CHASE_PCT=0.05`
- quote age / spread / optional volume / OI guards
- Short-Term 5 分钟、Swing 30 分钟 entry TTL
- 30% trailing 与 09:30–09:35 ET opening guard

DRY_RUN 执行完整决策但不写券商、不伪造 fill。LIVE 必须通过独立安全门。AXIS 永不自动调用
`unlock_trade`，且只允许 Owner 的明确账户；会员账户始终不在范围内。

## Short-Term / Massive Market Data

- `MASSIVE_API_KEY`：Massive Secret，只放 `.env` / Secret Store。
- `MASSIVE_BASE_URL=https://api.massive.com`
- `DAILY_SUMMARY_TIME_ET=16:15`：Swing / LEAPS Active Summary 读取当日 Options Daily OHLC close。
- `SHORT_TERM_TRACKING_CONFIG=config/short_term_tracking.yaml`
- `GEX_EXPLORER_POLICY=config/gex_explorer.yaml`

价格来源、Milestones、Reference Protection、Momentum 条件、Cooldown 与 Policy Version
全部由该 YAML 管理。每笔订单创建时锁定 `price_source` 和 `tracking_policy_version`；不能在
同一笔订单中混用 BID / MID / LAST。

## Local Storage / Runtime

- `ATTACHMENT_STORAGE_PATH`
- `MAX_ATTACHMENT_BYTES`
- `LOG_LEVEL`
- `TIMEZONE`
- `DISCORD_IDS_PATH`

任何示例、测试和文档都不得包含真实 Secret。
