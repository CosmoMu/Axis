# AXIS — Stripe Live Payment Specification

**Effective:** 2026-08-31

本文件补充 `01_AXIS_CORE_MVP_SPEC.md` 的 Membership / Stripe Lock。它只修改支付上线与运维
边界，不改变 Signal、Analysis、Mentor、Member Control、Results、Discord 结构或 AXIS LAB。

## Environment isolation

- Test 与 Live 使用完全独立的 secret、publishable key、webhook secret/URL、Product、Price、
  Portal 与数据库 namespace。
- `STRIPE_MODE=test|live` 选择运行环境；Live 不得回退到 Test 或旧通用变量。
- `PAYMENTS_ENABLED=false` 是强制 kill switch，只阻止新 Checkout，不停止 webhook、既有订阅
  lifecycle、到期、对账或 Role reconciliation。
- Stripe event 必须先通过签名，再严格匹配 `livemode` 和 metadata environment，最后才写入按
  environment 隔离的幂等 event record。

## Products and prices

- Product：`AXIS Membership`。
- Day Pass V1：USD 9.99 one-time，一个 XNYS Trading Day。
- Monthly V1：USD 99.99/month，自动续费。
- Free Trial 继续是 AXIS 内部 Entitlement，不通过 Stripe。
- Price 不可变；新金额创建 V2，只有新 Checkout 使用 current 版本。既有 subscription 保留
  signup Price、版本、金额和币种快照，不自动迁移。

## Lifecycle

- 签名 webhook 是付款事实来源，成功 redirect 和 Discord Role 不是。
- 最低事件集：`checkout.session.completed`、`invoice.paid`、`invoice.payment_failed`、
  `customer.subscription.updated`、`customer.subscription.deleted`。
- Portal 取消必须为 period end；payment failed 进入 `PAST_DUE`，不立即删除访问；最终无效后
  再结束对应 Entitlement。
- `MembershipAccessService` 汇总全部 Entitlement 决定访问，Discord Member Role 只是投影。

## Live gate

Live 必须具备：Stripe account activation、KYC、payout bank、Live Product/Prices、稳定 HTTPS
webhook、Live signing secret、Portal、business profile、支持联系方式、privacy/refund/cancel 页面、
有效 statement descriptor、对账和告警。`AXIS` 只有 4 字符，不能作为完整 Stripe statement
descriptor；候选 `AXIS MEMBERSHIP` 必须由 Dashboard 人工验证。

不得由自动化制造 Live 假付款。Owner 完成真实首笔付款和完整 Day Pass / Monthly lifecycle 验收
前，不得标记 `PRODUCTION ENABLED`。有任何阻塞时保持 `PAYMENTS_ENABLED=false`。

详细命令和事故处理以 `docs/operations/payments/` 为准。
