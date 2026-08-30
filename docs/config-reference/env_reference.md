# AXIS Environment Reference

正式模板：`config/.env.example`。真实值只放本地 `.env` 或部署 Secret Store。

## Discord

- `DISCORD_BOT_TOKEN`：Discord Bot Secret。
- `DISCORD_APPLICATION_ID`：AXIS BOT Application ID。
- `DISCORD_GUILD_ID`：唯一目标 Guild。
- `DISCORD_OWNER_USER_ID`：Owner User ID。
- `APPLY_CHANGES` / `DRY_RUN`：Discord 三重写入 Gate 的环境锁。

## Database

- `DATABASE_URL`：必须使用 `postgresql+asyncpg://`。

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
- `FEATURE_MOOMOO_ENABLED=true`：当前本机仅启用 Core 只读期权快照。
- `FEATURE_DAILY_SUMMARY_ENABLED=true`：三个会员频道的每日收盘总结。
- `FEATURE_COSMOS_STOCK_ANALYST_ENABLED=false`：新环境安全默认；启用后单 ticker Analysis
  会调用同机 CosmosPilot runtime，合并当前分析并生成缺失的预测路径图。

## Cosmos Stock Analyst Bridge

- `COSMOS_RUNTIME_ROOT`：本机 CosmosPilot runtime 根目录。
- `COSMOS_PYTHON_PATH`：可选；默认使用 runtime 内 `.venv/bin/python`。
- `COSMOS_QUERY_TIMEOUT_SECONDS=180`：一次当前股票分析的最大等待时间。

AXIS 不读取、复制或记录 Cosmos Secret；bridge 子进程只从 Cosmos runtime 自己的 `.env`
加载配置，返回结构化分析与本次新生成图片。

## Moomoo Core Read-only Market Data

- `MOOMOO_OPEND_HOST=127.0.0.1`
- `MOOMOO_OPEND_PORT=11111`
- `DAILY_SUMMARY_TIME_ET=16:15`

以上配置不包含 Moomoo 账户 Secret。OpenD 必须保持行情登录；AXIS 不调用账户、持仓、
订单、交易解锁或下单接口。

## Local Storage / Runtime

- `ATTACHMENT_STORAGE_PATH`
- `MAX_ATTACHMENT_BYTES`
- `LOG_LEVEL`
- `TIMEZONE`
- `DISCORD_IDS_PATH`

任何示例、测试和文档都不得包含真实 Secret。
