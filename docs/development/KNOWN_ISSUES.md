# AXIS Known Issues

## Blocking for Gate A

- 无。Core Gate A 已通过。

## Live Analysis Gate

- Automated Gate B 已通过；live activation 仍等待 Owner 单独授权 `analysis-input` 的文字与
  图片发送给 OpenAI。当前 `FEATURE_ANALYSIS_ENABLED=false`。

## Migration Compatibility

- 本地部署仍允许 `LLM_API_KEY` / `LLM_MODEL` fallback。完成环境迁移后应移除。
- 根目录 `README_FOR_CODEX.md` 和 `assets/axis-brand-lockup.png` 是有意保留的兼容项。
- 迁移前创建的那条 Draft 没有 `llm_invocation_id`；不会伪造历史 latency。

## Non-blocking

- Python 3.12 下 discord.py 依赖会产生 `audioop` Python 3.13 removal warning。
- 当前生产形态仍是 macOS 本地 LaunchAgent；Dockerfile / Compose 是部署基础，不含集中
  监控、托管 Secret 或 off-host backup。
- Analysis 代码已完成但 live feature gate 关闭；AXIS LAB 频道只预留且业务未开始。
- Active View 当前单次最多展示 25 个进行中订单，符合 Discord Embed field 上限。
- Mentor / Trade 动态 Select 当前单次最多展示 25 项；超出后需要后续分页。
