# Stripe Webhook Operations

## Endpoint

正式 endpoint 固定为：

```text
POST https://axisdesk.fyi/webhooks/stripe
```

必须使用有效 HTTPS、原始 request body 和 `Stripe-Signature`。Live URL 不得是 localhost、
临时隧道或不受 AXIS 控制的域名。

当前架构：Sites Worker 验证签名与 Live event，提取最小必要字段后写入 D1；Bot 通过 Bearer
保护的 `/internal/stripe-events` 拉取租约并处理现有 `MembershipStripeService`，成功后 ACK，失败
则按退避重试。完整 Stripe payload、银行卡资料和 Secret 不写入 D1、日志或 Git。公开访问私密
relay 必须返回 401；Bot 授权访问必须返回 200。

## Required events

- `checkout.session.completed`
- `invoice.paid`
- `invoice.payment_failed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Checkout 当前只允许 card payment method，因此未订阅异步 payment success/failure 事件。若以后
开放异步支付方式，必须先扩展规格、事件处理和回归测试。

## Validation order

1. 用当前环境的 webhook secret 验证签名。
2. 要求 Stripe event 明确带 `livemode`。
3. `STRIPE_MODE=test` 只接受 `livemode=false`；Live 只接受 `true`。
4. metadata `environment` 必须与当前环境一致。
5. Sites D1 以 provider event ID 幂等排队，并使用租约、ACK 和 retry。
6. Bot 使用 `provider + environment + provider_event_id` 幂等预留。
7. 只保存最小事件状态，不保存完整 payload 或支付资料。
8. 应用 Entitlement，提交后执行 Role reconciliation。

环境不匹配必须在预留 event 之前拒绝，避免 Test event 污染 Live dedup namespace。

## Retry and ordering

Stripe 可能重复、延迟或乱序投递。重复 event 返回现有结果；`invoice.paid` 早于 Checkout identity
link 时允许失败并等待 Stripe retry，不通过猜测 Discord 用户修复。Webhook handler 必须快速
返回，内部错误只记录安全 error code。

## Endpoint migration

迁移域名时：

1. 保持旧 endpoint 正常接收；
2. 创建新 HTTPS endpoint 并保存新 signing secret；
3. 两个 endpoint 短期重叠，验证 dedup；
4. 对账 dry-run 为 clean；
5. 更新 `STRIPE_LIVE_WEBHOOK_URL` 并重启；
6. 观察至少一个完整账单周期或经 Owner 批准的窗口后再禁用旧 endpoint。

不要复用旧 endpoint secret；不要先删除旧 endpoint。
