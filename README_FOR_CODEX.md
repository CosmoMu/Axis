# AXIS — Codex 开发入口

**当前规范版本：** `2026-08-29 AXIS Current Spec v2.1`

本仓库唯一正式 Source of Truth 位于 `docs/spec/current/`。开始任何实现、测试或
Discord Bootstrap 前，必须依次阅读：

1. `docs/spec/current/README_FOR_CODEX.md`
2. `docs/spec/current/00_AXIS_BRAND_LOCK.md`
3. `docs/spec/current/01_AXIS_CORE_MVP_SPEC.md`
4. `docs/spec/current/02_AXIS_ANALYSIS_PIPELINE_SPEC.md`
5. `docs/spec/current/03_AXIS_LAB_DEFERRED_SPEC.md`
6. `docs/spec/current/04_IMPLEMENTATION_ORDER_AND_GATES.md`
7. `config/discord_blueprint.yaml`
8. `config/model_routing.yaml`
9. `config/llm_trade_schema.json`
10. `config/llm_analysis_schema.json`
11. `config/.env.example`

## 执行锁

- 品牌固定为 `AXIS`，Bot 为 `AXIS BOT`，研究模块为 `AXIS LAB`。
- Discord Category / Channel 使用 Emoji + English；卡片和用户交互以中文为主。
- 只保留 `Manager` 与 `Member` 两个人工业务 Role。
- Secret 只从 `.env` 或部署 Secret Store 读取，不进入源码、日志、测试快照或 Git。
- Discord 修改前必须先做只读 inventory 与 dry-run；写入必须通过
  `APPLY_CHANGES=true`、`DRY_RUN=false`、目标 Guild ID 三重 Gate。
- Bootstrap 必须幂等，不删除、不移动、不修改任何未登记的非 AXIS 资源。
- LLM 必须通过 workload router 选择模型，不得在业务 Service 中硬编码单一
  `LLM_MODEL`。
- LLM 调用必须保存 provider、实际 model、workload、prompt version、schema version、
  latency 和成功/失败状态。
- LLM 只能生成 Draft；所有公开会员卡片必须经 Manager 确认，并通过 Public DTO
  白名单隔离 Mentor、Source、提交人、附件与解析信息。
- `AXIS LAB` 只允许创建 Owner-only 预留频道，所有功能 Flag 保持关闭；Owner 明确要求
  开始 LAB 前不得实现其业务逻辑。

## 开发 Gate

严格按照 `docs/spec/current/04_IMPLEMENTATION_ORDER_AND_GATES.md`：

1. Stage 0：Repository / Guild inventory 与 dry-run。
2. Stage 1：Infrastructure、Discord Core、数据库、模型路由和持久组件。
3. Stage 2：Signal Pipeline。
4. Stage 3：Manager、Member、Results。
5. Gate A 全部通过后，才可开始 Analysis。
6. Gate B 通过后进行 Production Stabilization。
7. 当前停止在 AXIS LAB 之前。

## 新资料入口

新增想法、草稿、截图和参考资料先放到 `manually input/`。Codex 会按其中 README
分流到 `docs/`、`config/` 或 `assets/`；确认已完整吸收后再清理临时副本。
