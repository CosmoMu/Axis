# LLM 结构化草稿

这一阶段把 `signal-input` 收到的文字和图片解析为 `trade_drafts`，但不会自动审核、
发布会员卡片或分配 Mentor。

## 配置目标与当前过渡状态

v2.1 的目标配置由 `config/model_routing.yaml` 和环境变量共同解析：

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=
LLM_ROUTING_CONFIG=config/model_routing.yaml
LLM_SIGNAL_MODEL=gpt-5.6-terra
LLM_SIGNAL_REPAIR_MODEL=gpt-5.6-terra
LLM_TIMEOUT_SECONDS=45
LLM_MAX_RETRIES=2
LLM_SCHEMA_PATH=config/llm_trade_schema.json
LLM_PROMPT_PATH=config/llm_trade_prompt.txt
```

Stage 0 盘点时，已部署的旧 Parser 仍读取本地 `LLM_API_KEY` / `LLM_MODEL`。这是
Stage 1 必须消除的兼容差异，不是后续业务代码可继续依赖的接口。路由迁移完成前不要
删除本地旧变量；迁移后只保留 `OPENAI_API_KEY` 与 workload overrides。

Secret 不得写入源码、文档、日志、测试快照或 Git。更换 Key 时只修改本地 `.env`。

## 处理流程

1. Bot 从 `source_messages` 取出最早的 `RECEIVED/PROCESSING` 记录。
2. 读取图片前再次检查路径、大小和 SHA-256。
3. 通过 workload router 解析 `SIGNAL_PARSE`，再调用 OpenAI Responses API 发送
   文字和图片，要求严格 JSON Schema 输出。
4. 返回结果再用本地 `config/llm_trade_schema.json` 完整校验。
5. 成功时写入一条 `PENDING_REVIEW` 草稿；失败时写入一条 `PARSE_FAILED` 草稿。
6. 每个 `source_message_id` 只允许一条草稿，重启和重复运行不会生成重复数据。
7. 每次调用写入 `llm_invocations`，保存 provider、实际 model、workload、
   Prompt/Schema 版本、延迟和成功/失败状态。

## 业务规则

- 不确定值使用 `null` 或 `UNKNOWN`，不猜测。
- 使用 `SL`，不使用 Stop，不生成 Market / Bid / Ask。
- 默认阶梯只自动填充入场、第一、第二、第三次加仓；第四次加仓仍需 Manager 明确选择。
- `mentor_hint` 仅作内部提示，`mentor_id` 保持为空。
- LLM 的输出和置信度只在内部草稿中使用，不是会员公开 DTO。

## 验收

1. 在 `.env` 直接填入有效 `OPENAI_API_KEY`，不要经由聊天或 shell 命令传递。
2. 重新运行 `scripts/install_axis_bot_service.py`。
3. 在 `signal-input` 发送一条测试文字，可选附加 PNG/JPEG/WEBP。
4. 确认 Bot 先回复“已接收”，随后回复草稿编号。
5. 确认数据库中的来源状态为 `PARSED`，草稿状态为 `PENDING_REVIEW`。
6. 重启 Bot，确认同一条来源没有第二条草稿。
