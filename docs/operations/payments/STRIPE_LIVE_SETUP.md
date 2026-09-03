# Stripe Live Setup

## Non-negotiable isolation

```dotenv
STRIPE_MODE=test
PAYMENTS_ENABLED=false

STRIPE_TEST_SECRET_KEY=
STRIPE_TEST_PUBLISHABLE_KEY=
STRIPE_TEST_WEBHOOK_SECRET=
STRIPE_TEST_WEBHOOK_URL=
STRIPE_TEST_SUCCESS_URL=
STRIPE_TEST_CANCEL_URL=
STRIPE_TEST_PORTAL_RETURN_URL=
STRIPE_TEST_DAY_PASS_PRODUCT_ID=
STRIPE_TEST_DAY_PASS_PRICE_ID=
STRIPE_TEST_DAY_PASS_PRICING_VERSION=DAY_PASS_V1
STRIPE_TEST_MONTHLY_PRODUCT_ID=
STRIPE_TEST_MONTHLY_PRICE_ID=
STRIPE_TEST_MONTHLY_PRICING_VERSION=MONTHLY_V2

STRIPE_LIVE_SECRET_KEY=
STRIPE_LIVE_PUBLISHABLE_KEY=
STRIPE_LIVE_WEBHOOK_SECRET=
STRIPE_LIVE_WEBHOOK_URL=
STRIPE_LIVE_SUCCESS_URL=
STRIPE_LIVE_CANCEL_URL=
STRIPE_LIVE_PORTAL_RETURN_URL=
STRIPE_LIVE_DAY_PASS_PRODUCT_ID=
STRIPE_LIVE_DAY_PASS_PRICE_ID=
STRIPE_LIVE_DAY_PASS_PRICING_VERSION=DAY_PASS_V1
STRIPE_LIVE_MONTHLY_PRODUCT_ID=
STRIPE_LIVE_MONTHLY_PRICE_ID=
STRIPE_LIVE_MONTHLY_PRICING_VERSION=MONTHLY_V2
```

Live 不得回退读取 Test 或旧的通用 `STRIPE_SECRET_KEY`。所有值只写 `.env` 或部署 Secret
Store；禁止粘贴到聊天、源码、文档、日志或 Git。

## External activation checklist

- [ ] Stripe Account activation 完成，`charges_enabled=true`。
- [ ] Live KYC/业务资料没有 `currently_due` 或 `past_due`。
- [ ] Payout bank account 完成，`payouts_enabled=true`。
- [ ] Customer-facing business name 使用 AXIS 品牌且人工复核。
- [ ] 支持邮箱或支持 URL 已配置；不得使用私人身份作为公开品牌。
- [ ] Privacy、refund、cancellation 和风险声明可公开访问并人工复核。
- [ ] Statement descriptor 在 Stripe 接受的 5–22 字符范围内。`AXIS` 只有 4 字符，不能直接
  作为完整 descriptor；候选值为 `AXIS MEMBERSHIP`，最终以 Dashboard 验证为准。
- [ ] 已准备稳定域名、TLS 和 `POST /webhooks/stripe`。

## Resource creation

先把 Live key 和公开 URL 写入 Secret Store，保持 `STRIPE_MODE=test` 与
`PAYMENTS_ENABLED=false`，然后执行只读检查：

```bash
.venv/bin/python scripts/verify_stripe_live_readiness.py
```

账户和 URL 就绪后，受控创建或复用 Live Product / Prices / webhook：

```bash
.venv/bin/python scripts/setup_stripe_live_resources.py --apply --confirm-live
```

脚本只创建/复用：

- `AXIS Membership` Product；
- Day Pass USD 9.99 one-time Price；
- Monthly V2 USD 149.99/month recurring Price；V1 已有订阅保持 USD 99.99/month；
- 五个所需事件的 Live webhook endpoint。

脚本把新 ID 和首次返回的 webhook signing secret 直接写入 gitignored `.env`（0600），不会
输出值，也不会启用收款。KYC、银行、Portal、业务资料、支持和法律页面仍需在 Dashboard 人工
完成。

## Customer Portal

Live Portal 必须启用 payment method update、invoice history 和 subscription cancellation；取消
模式必须是 `at_period_end`。Portal return URL 必须为 AXIS 控制的 HTTPS 页面。完成后重新运行
readiness verifier。

## Activation gate

只有以下全部成立，才能切换：

1. readiness verifier `PASS`；
2. `docs/development/LIVE_MODE_CHECKLIST.md` Stripe Live 项完成；
3. 数据库备份已验证；
4. Live 对账 dry-run 无未知差异；
5. Owner 明确批准。

然后先设 `STRIPE_MODE=live`、保持 `PAYMENTS_ENABLED=false` 重启并验证 webhook/Portal；最后才
设 `PAYMENTS_ENABLED=true`。真实首笔付款必须由 Owner 自己使用真实支付方式完成，自动化工具
不得制造或伪造 Live payment。
