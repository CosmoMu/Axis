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
- `STRIPE_ENABLED=false`：只有 Test Mode E2E 与人工隐私检查完成后才可启用。
- `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET`：只放 `.env` / Secret Store。
- `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL` / `STRIPE_PORTAL_RETURN_URL`。
- `STRIPE_DAY_PASS_PRODUCT_ID` / `STRIPE_DAY_PASS_PRICE_ID`。
- `STRIPE_MONTHLY_PRODUCT_ID` / `STRIPE_MONTHLY_PRICE_ID`。
- `STRIPE_DAY_PASS_PRICING_VERSION` / `STRIPE_MONTHLY_PRICING_VERSION`：必须对应
  `membership_prices` 中的不可变版本。
- `PAYMENT_WEBHOOK_HOST` / `PAYMENT_WEBHOOK_PORT`：Webhook listener 绑定地址。
- `MEMBERSHIP_SESSION_TTL_MINUTES`：Discord User ID 绑定 session 的有效期。

Checkout 为动态 Stripe Session，metadata 包含 `discord_user_id + membership_type +
pricing_version + membership_session_id`。Monthly 同步写入 Subscription metadata。Webhook
验证 `Stripe-Signature`，不使用 email、username 或显示名推断身份。

## Production Alerts

- `SYSTEM_ALERT_CHECK_SECONDS`：Owner-only 健康检查周期；正常状态不发送消息。

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
- `FEATURE_MOOMOO_ENABLED=false`：本轮按最新范围关闭；不启动 Moomoo Model Scanning。
- `FEATURE_DAILY_SUMMARY_ENABLED=true`：启用收盘总结与 Daily Results；Moomoo 关闭时
  Swing / LEAPS 只使用已保存的 Mentor 结果，Short-Term 使用独立 Tracking 数据。
- `FEATURE_SHORT_TERM_TRACKING_ENABLED=false`：安全默认。只有 Massive Secret 配置完成后
  才启用实时 Short-Term 轮询；Review、发布与 Tracking 注册本身仍可工作。
- `FEATURE_AXIS_STOCK_ANALYST_ENABLED=false`：新环境安全默认；启用后单 ticker Analysis
  会调用 AXIS 自有 Stock Analyst，通过本机 Moomoo OpenD 读取日 K 并生成文字结构观察。
  当前不会生成或发布 Analysis 图片；未来 Massive API 接入另行启用。

## AXIS Market Intelligence

- `AXIS Stock Analyst`：当前已接 Analysis Pipeline。
- `AXIS GEX Explorer`：当前只提供可复用纯计算引擎，未建频道、未自动发布。

两个模块都在 AXIS 仓库的 `app/market_intelligence/` 内运行，不 import、启动或读取 Cosmos
仓库。旧 `FEATURE_COSMOS_STOCK_ANALYST_ENABLED` 仅保留一版配置兼容，新环境不得继续使用。

## Moomoo Core Read-only Market Data

- `MOOMOO_OPEND_HOST=127.0.0.1`
- `MOOMOO_OPEND_PORT=11111`
- `DAILY_SUMMARY_TIME_ET=16:15`

以上配置不包含 Moomoo 账户 Secret。OpenD 必须保持行情登录；Stock Analyst 只读日 K，
Core 只读期权行情；AXIS 不调用账户、持仓、订单、交易解锁或下单接口。

## Short-Term / Massive Market Data

- `MASSIVE_API_KEY`：Massive Secret，只放 `.env` / Secret Store。
- `MASSIVE_BASE_URL=https://api.massive.com`
- `SHORT_TERM_TRACKING_CONFIG=config/short_term_tracking.yaml`

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
