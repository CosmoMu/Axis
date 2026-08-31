# Payment Reconciliation

## Purpose

对账比较 Stripe subscription、AXIS Monthly Entitlement 和最终 Discord Role 访问决策。定时任务
默认每 15 分钟运行，发现 provider/local 缺失、价格不匹配或修复失败时向 Owner-only System
Alerts 发送去重告警。

## Manual dry-run

先确认 `.env` 的 `STRIPE_MODE`，再执行：

```bash
.venv/bin/python scripts/reconcile_stripe_memberships.py --dry-run
```

输出只包含环境和汇总计数，不输出 customer、subscription、checkout、用户或 Secret。

## Apply

只有 dry-run 已人工解释且目标环境明确时：

```bash
.venv/bin/python scripts/reconcile_stripe_memberships.py \
  --apply --confirm-environment test
```

Live 必须把确认值改为 `live`。Apply 仅对可证明 identity、environment 和 Price mapping 的缺失
Monthly Entitlement 进行安全修复，并同步可验证状态；未知 Price、跨环境或 identity 不完整只告警，
不猜测。Price mismatch 不自动迁移，以保护 grandfathering。

## Review sequence

1. provider subscription count；
2. local Membership/Entitlement count；
3. repaired count；
4. provider missing、local missing、price mismatch 和 identity error；
5. `MembershipAccessService` 汇总结果；
6. Discord Member Role reconciliation。

`PAYMENTS_ENABLED=false` 不阻止对账。紧急停收款后仍应继续运行 dry-run 和已授权的修复。
