# AXIS

AXIS 是以 Discord 为入口的交易信号、观点分析、会员权限与官方战绩系统。

## 当前阶段

**Core feature-complete / Production live validation**

- Core Gate A：PASS
- Analysis Gate B：PASS
- 最新自动化回归：151 tests passed；Ruff / compileall PASS
- Stripe：Test Mode E2E 已通过，Live Mode 尚未启用
- Short-Term Automated Tracking：实现已完成，但真实 Massive quote / tracking / trigger E2E 尚未通过
- AXIS LAB：DEFERRED，未开始开发

## 文档入口

- 当前唯一规格入口：docs/current/README_FOR_CODEX.md
- 当前开发状态：docs/development/CURRENT_STATUS.md
- 已实现功能：docs/development/IMPLEMENTED_FEATURES.md
- 已知问题：docs/development/KNOWN_ISSUES.md
- 测试状态：docs/development/TEST_STATUS.md
- 下一步：docs/development/NEXT_STEPS.md
- Live 上线清单：docs/development/LIVE_MODE_CHECKLIST.md
- 运维手册：docs/operations/

## 下一优先级

完成 Short-Term / Massive 的真实端到端验证，确认已发布订单能够注册 tracking、取得真实行情、
触发 milestone / reversal / protection 事件，并在 Bot 重启后正确恢复。

Secret 只允许存放在本地 .env 或部署 Secret Store，不得进入源码、日志或 Git。
