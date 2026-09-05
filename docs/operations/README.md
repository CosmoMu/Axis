# AXIS Operations Runbooks

本目录只记录可重复执行的生产运维流程。产品规格以 `docs/current/` 为准，开发状态以
`docs/development/` 为准。

## Payments

- `payments/README.md` — Stripe、AXIS Entitlement 与 Discord Role 的边界和总入口。
- `payments/STRIPE_LIVE_SETUP.md` — Test / Live 隔离、账户激活与上线步骤。
- `payments/PRICING_MAINTENANCE.md` — 不可变 Price 版本、切换与回滚。
- `payments/MEMBERSHIP_OPERATIONS.md` — Trial、Day Pass、Monthly、Gift、延期、取消和撤权。
- `payments/STRIPE_WEBHOOK_OPERATIONS.md` — HTTPS endpoint、事件、签名、重试和迁移。
- `payments/STRIPE_SECRET_ROTATION.md` — Test / Live 密钥轮换和泄漏处置。
- `payments/PAYMENT_RECONCILIATION.md` — Stripe / AXIS / Discord 对账。
- `payments/PAYMENT_INCIDENT_RUNBOOK.md` — 支付事故诊断与恢复。
- `payments/CHANGELOG.md` — Payment 架构与生产配置变更记录。

## Membership onboarding

- `membership/FREE_TRIAL_ONBOARDING.md` — Welcome-first 新会员入口、3 个交易日 Trial、终身一次
  资格、Day Pass 交易日边界和运行验证。

## Trading

- `trading/SWING_TRACKING.md` — Simple Tracked Swing Entry、共享固定 TP、High Watermark、Close、
  Active View、EOD、Results、Expiry、restart recovery 与 Legacy compatibility。
- `trading/MOOMOO_PERSONAL_EXECUTION.md` — Owner-only Moomoo DRY_RUN、OpenD 对账、风险控制、
  LIVE gate、kill switch 与事故处理。

## Market data

- `market-data/GEX_EXPLORER.md` — Member Lounge `/gex` live、Owner card-testing maintenance、Massive option surface、V7 shared
  classifier、专业 Strike × Expiration Ladder、GEX 公式、
  expiry/near-term、walls/clusters/regime/triggers、heatmap、cache/limits、alerts 与 rollback。

Secret、完整 Stripe payload、客户付款信息、Discord 用户 ID 与数据库连接信息不得写进文档、
命令输出、日志或 Git。
