# Membership Pricing Maintenance

## Immutable versions

`membership_prices` 按 `environment + plan_type + pricing_version` 唯一。已经被 Checkout 或
Entitlement 引用的 Price 不修改金额、不覆盖版本、不自动迁移现有 Monthly subscription。
Entitlement 保存 signup 时的 `stripe_price_id`、版本、金额和币种快照，这就是 grandfathering。

查看目录不会修改 Stripe 或数据库：

```bash
.venv/bin/python scripts/manage_membership_pricing.py list --environment test
.venv/bin/python scripts/manage_membership_pricing.py list --environment live
```

## Create V2

先在对应 Stripe 环境创建新 immutable Price，再登记数据库。以下仅为命令格式；ID 只能从对应
环境 Dashboard/API 获取，不能复制 Test ID 到 Live：

```bash
.venv/bin/python scripts/manage_membership_pricing.py create \
  --environment live --confirm-environment live \
  --plan MONTHLY --version MONTHLY_V2 --unit-amount 14999 \
  --product-id prod_... --price-id price_...
```

Day Pass 使用 `--plan DAY_PASS --version DAY_PASS_V2`。先不加 `--make-current`，核对币种、金额、
interval、livemode 和 Product 后，再切 current：

```bash
.venv/bin/python scripts/manage_membership_pricing.py switch \
  --environment live --confirm-environment live \
  --plan MONTHLY --version MONTHLY_V2
```

新 Checkout 使用 current 版本；旧 Entitlement 和旧 Stripe subscription 继续使用 V1。

## Rollback

价格切换回滚不是删除 Price，而是把 current 指回上一版本：

```bash
.venv/bin/python scripts/manage_membership_pricing.py switch \
  --environment live --confirm-environment live \
  --plan MONTHLY --version MONTHLY_V1
```

这只影响后续 Checkout，不更改已经购买 V2 的用户。回滚后运行对账 dry-run，并在
`CHANGELOG.md` 记录原因、环境、版本和时间；不得记录 Price ID 或客户 ID。

## Change checklist

- [ ] 确认目标环境和 key prefix。
- [ ] 新 Stripe Price 的 livemode、amount、currency、recurring interval 正确。
- [ ] 数据库新版本不是覆盖旧行。
- [ ] 先登记，再显式 switch；禁止直接 SQL 修改 current。
- [ ] Discord 展示价格与 current catalog 一致。
- [ ] 既有订阅仍指向原 Price，grandfathering dry-run 无 mismatch。
- [ ] Test 和 Live 分别验证，不跨环境复制事件或 ID。
