# AXIS

AXIS 是以 Discord 为入口的交易信号、观点分析、会员权限与官方战绩系统。

## Current Development Stage

- Core Signal / Mentor / Member / Results: COMPLETE
- Analysis Fusion: COMPLETE / LIVE
- Soft Open Reset: COMPLETE / PRODUCTION DATA STARTS 2026-08-31
- Daily Results Review / Exclude Workflow: COMPLETE / LIVE
- Newcomer Approval / Security Gate: CODE COMPLETE / LIVE E2E PENDING
- Short-Term TP1–TP41 / Expiry-only Tracking / LOTTO: CODE COMPLETE / LIVE E2E PENDING
- Simple Tracked Swing: CODE COMPLETE / DB MIGRATED / LIVE E2E PENDING
- Legacy Swing: COMPATIBILITY MODE / 4 ACTIVE AT MIGRATION
- Stripe Payment: LIVE ENABLED / FIRST REAL PAYMENT E2E PENDING
- Production Stabilization: PARTIAL
- Owner Personal Moomoo Execution: CODE COMPLETE / DRY_RUN EXTERNAL E2E BLOCKED / LIVE DISABLED
- GEX Explorer: PHASE 1 CODE COMPLETE / TEST ONLY / MEMBER LOUNGE NOT LAUNCHED
- AXIS LAB Model A/B: DEFERRED
- Latest automated regression: 303 passed；Ruff / compileall / database / Discord runtime PASS

## 文档入口

- 当前唯一规格入口：docs/current/README_FOR_CODEX.md
- 当前开发状态：docs/development/CURRENT_STATUS.md
- 已实现功能：docs/development/IMPLEMENTED_FEATURES.md
- 已知问题：docs/development/KNOWN_ISSUES.md
- 测试状态：docs/development/TEST_STATUS.md
- 下一步：docs/development/NEXT_STEPS.md
- Soft Open Day 1 验证：docs/development/SOFT_OPEN_DAY1_VALIDATION.md
- Live 上线清单：docs/development/LIVE_MODE_CHECKLIST.md
- Owner Moomoo 运维：docs/operations/trading/MOOMOO_PERSONAL_EXECUTION.md
- GEX Explorer 运维：docs/operations/market-data/GEX_EXPLORER.md
- Stripe Payment 运维：docs/operations/payments/README.md
- Soft Open Reset 审计：docs/development/SOFT_OPEN_RESET_2026-08-30.md
- 运维手册：docs/operations/

## 下一优先级

Simple Tracked Swing 已完成独立 tracker 与安全 schema migration，下一步优先验证真实 Entry →
TP → Close → Results，并确认四笔 Active Legacy Swing 继续旧流程。Newcomer Role、中文申请、
Manager join-review、自动 3 U.S. Trading Day Trial、风险扫描和 reconciliation 已实现并部署，
仍需真实 Join → Apply → Approve → Trial → Expiry 时钟验收。Stripe 账户、KYC、payout、Live
Product/Prices、Customer Portal、顾客展示资料和
`https://axisdesk.fyi/webhooks/stripe` 已完成；`STRIPE_MODE=live`、`STRIPE_ENABLED=true`、
`PAYMENTS_ENABLED=true`，Live readiness 为 PASS / 0 blockers。下一步由 Owner 在 Discord
完成第一笔真实 Day Pass 或 Monthly 付款，并记录 webhook、Entitlement 与 Member Role E2E；
自动化不得制造 Live 假付款。

2026-08-31 起由真实输入产生的数据均为永久 Production Data，不再执行全量 Reset 或重新编号。

Secret 只允许存放在本地 .env 或部署 Secret Store，不得进入源码、日志或 Git。
