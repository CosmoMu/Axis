# AXIS Known Issues

## Blocking for Gate A

- 无。Core Gate A 已通过。

## Migration Compatibility

- 本地部署仍允许 `LLM_API_KEY` / `LLM_MODEL` fallback。完成环境迁移后应移除。
- 根目录 `README_FOR_CODEX.md` 和 `assets/axis-brand-lockup.png` 是有意保留的兼容项。
- 迁移前创建的那条 Draft 没有 `llm_invocation_id`；不会伪造历史 latency。

## Non-blocking

- Python 3.12 下 discord.py 依赖会产生 `audioop` Python 3.13 removal warning。
- 当前为 macOS 本地 LaunchAgent 部署，尚无 Docker production target。
- Analysis / LAB 频道已存在，但功能关闭；频道存在不代表业务已完成。
- Active View 当前单次最多展示 25 个进行中订单，符合 Discord Embed field 上限。
- Mentor / Trade 动态 Select 当前单次最多展示 25 项；超出后需要后续分页。
