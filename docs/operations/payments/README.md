# AXIS Payment Operations

## Source of truth

三层职责必须分开：

1. Stripe 是付款、订阅状态、发票和 Customer Portal 的事实来源。
2. `MembershipAccessService` 汇总 AXIS Entitlement，决定用户当前是否有访问权。
3. Discord `Member` Role 只是访问权的投影，不是付款或会员事实来源。

成功跳转、Checkout 按钮和 Discord Role 都不能直接激活付费权限。只有签名有效、环境匹配且
通过幂等处理的 Stripe webhook 可以创建或更新付费 Entitlement。一个 Entitlement 到期或撤销
时，只要同一用户仍有另一个有效 Entitlement，就不得移除 `Member` Role。

## Current production boundary — 2026-08-31

- 双环境代码、数据库隔离、价格版本、webhook `livemode` 验证、对账和 kill switch 已完成。
- `STRIPE_MODE=test`；Test V1 catalog 保留。
- `STRIPE_ENABLED=false`；使用待轮换 Test key 的本机 Stripe Test listener 已停止并禁用。
- `PAYMENTS_ENABLED=false`；Checkout 创建被阻止，webhook、Portal 生命周期和对账不被 kill
  switch 关闭。
- Stripe Dashboard 显示账户激活/KYC 尚未完成。
- Live Product、Prices、公开 HTTPS webhook、Live signing secret、Portal、支持联系方式和隐私
  人工检查均未完成。
- 未进行真实 Live 付款；不得把当前状态称为 `PRODUCTION ENABLED`。
- 2026-08-31 的只读 Dashboard 审计曾使 Test key 出现在受限工具输出中；继续使用 Test Mode
  前必须先轮换 Test secret key，并同步本地 Secret Store。

## Kill switch

```dotenv
PAYMENTS_ENABLED=false
```

紧急停收款时设为 `false` 并重启 Bot。正常情况下此开关只阻止新 Checkout；必须继续接收
webhook、处理既有订阅更新、执行到期和 Role reconciliation。若 key 已泄漏，则另设
`STRIPE_ENABLED=false` 并停用对应 listener，直到完成轮换；此时 Stripe 外部集成整体离线。
恢复前先运行 Live readiness 和对账 dry-run，再由 Owner 明确批准设为 `true`。

## Runbook index

按 `STRIPE_LIVE_SETUP` → `STRIPE_WEBHOOK_OPERATIONS` → `PRICING_MAINTENANCE` →
`PAYMENT_RECONCILIATION` 的顺序上线。日常会员操作使用 `MEMBERSHIP_OPERATIONS`；轮换与事故
分别使用 `STRIPE_SECRET_ROTATION` 和 `PAYMENT_INCIDENT_RUNBOOK`。
