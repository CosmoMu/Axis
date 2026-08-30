# AXIS Known Issues

## Blocking for Gate A

- 无。Core Gate A 已通过。

## Live Analysis

- Owner 已单独授权 Analysis 数据出口，`FEATURE_ANALYSIS_ENABLED=true`。尚未为了验收制造
  虚假市场观点；第一条真实 Manager 输入需要观察 Discord → OpenAI → Review 的生产链路。

## Migration Compatibility

- 本地部署仍允许 `LLM_API_KEY` / `LLM_MODEL` fallback。完成环境迁移后应移除。
- 根目录 `README_FOR_CODEX.md` 和 `assets/axis-brand-lockup.png` 是有意保留的兼容项。
- 迁移前创建的那条 Draft 没有 `llm_invocation_id`；不会伪造历史 latency。

## Non-blocking

- Python 3.12 下 discord.py 依赖会产生 `audioop` Python 3.13 removal warning。
- 当前生产形态仍是 macOS 本地 LaunchAgent；Dockerfile / Compose 是部署基础，不含集中
  监控、托管 Secret 或 off-host backup。
- Analysis 已启用；AXIS LAB 频道只预留且业务未开始。
- Active View 当前单次最多展示 25 个进行中订单，符合 Discord Embed field 上限。
- Mentor / Trade 动态 Select 当前单次最多展示 25 项；超出后需要后续分页。
- OpenD 当前已运行，`com.axis.moomoo-opend` 会在下次登录加载。macOS quarantine 安全标记
  未被 AXIS 移除；若系统下次启动显示官方 OpenD 确认提示，需要由 Owner 确认一次。
- 每日总结在当天 `16:15 ET` 后持续重试到午夜；若整段时间 Bot/OpenD 均离线，当前版本
  不会用非当日快照补造历史总结。
