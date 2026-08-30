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
- `FEATURE_ANALYSIS_ENABLED=false`，Gate A 与自动 Gate B 已通过；在 Owner 单独授权
  `analysis-input` 内容发送给 OpenAI 前仍保持关闭。
- `FEATURE_LAB_ENABLED=false`
- `FEATURE_MODEL_AB_ENABLED=false`
- `FEATURE_MOOMOO_ENABLED=false`

## Local Storage / Runtime

- `ATTACHMENT_STORAGE_PATH`
- `MAX_ATTACHMENT_BYTES`
- `LOG_LEVEL`
- `TIMEZONE`
- `DISCORD_IDS_PATH`

任何示例、测试和文档都不得包含真实 Secret。
