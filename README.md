# AXIS

AXIS 是以 Discord 为入口的交易信号、观点分析、会员权限与官方战绩系统。

## Current Development Stage

- Core Signal / Mentor / Member / Results: COMPLETE
- Analysis Fusion: COMPLETE / LIVE
- Soft Open Reset: COMPLETE / PRODUCTION DATA STARTS 2026-08-31
- Daily Results Review / Exclude Workflow: COMPLETE / LIVE
- Short-Term TP1–TP10 / LOTTO / Automated Tracking: CODE COMPLETE / LIVE E2E PENDING
- Stripe: TEST MODE COMPLETE / LIVE PENDING
- Production Stabilization: PARTIAL
- AXIS LAB: DEFERRED
- Latest automated regression: 198 passed、0 failed、0 skipped；Ruff / compileall PASS

## 文档入口

- 当前唯一规格入口：docs/current/README_FOR_CODEX.md
- 当前开发状态：docs/development/CURRENT_STATUS.md
- 已实现功能：docs/development/IMPLEMENTED_FEATURES.md
- 已知问题：docs/development/KNOWN_ISSUES.md
- 测试状态：docs/development/TEST_STATUS.md
- 下一步：docs/development/NEXT_STEPS.md
- Live 上线清单：docs/development/LIVE_MODE_CHECKLIST.md
- Soft Open Reset 审计：docs/development/SOFT_OPEN_RESET_2026-08-30.md
- 运维手册：docs/operations/

## 下一优先级

完成 Short-Term / Massive 的真实端到端验证，确认已发布订单能够注册 tracking、取得真实行情、
触发 TP1–TP10 / Momentum TP / tracking protection 事件，并在 Bot 重启后正确恢复。

2026-08-31 起由真实输入产生的数据均为永久 Production Data，不再执行全量 Reset 或重新编号。

Secret 只允许存放在本地 .env 或部署 Secret Store，不得进入源码、日志或 Git。
