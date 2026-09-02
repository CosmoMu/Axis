# Membership Operations

## Access decision

所有入口最终调用 `MembershipAccessService`。用户拥有任一有效的 `FREE_TRIAL`、`DAY_PASS`、
`MONTHLY`、`GIFT`、`MANUAL` 或 `MANUAL_EXTENSION` Entitlement 时保留 Member Role。Role 不得
反向创建付款记录；Discord Role reconciliation 产生的访问也必须作为独立来源审计。

## Flows

- Free Trial：AXIS 内部能力，终身一次，从批准后覆盖 3 个 XNYS 交易日；周末和美国市场休市日
  不计入，通过 `TradingCalendarService` 固化边界，但不经过 Stripe。
- Day Pass：Stripe one-time payment 成功后，按 XNYS 一个交易日创建 Entitlement。
- Monthly：Stripe recurring subscription；价格和版本在 signup 时快照，后续自动续费。
- Gift / Manual：Manager/Owner 授权并写 Audit；不冒充 Stripe payment。
- Manual Extension：新增独立 Entitlement，不覆盖原付款来源或到期日。

Free Trial 有效期间阻止重复购买 Day Pass，但允许用户升级 Monthly。已有 Gift、Manual、Paid
或 Extension 访问时不领取、也不消耗 Trial 资格。

## Cancel, past due, revoke

- 用户在 Customer Portal 取消时使用 `cancel_at_period_end=true`；在 period end 前继续访问。
- `invoice.payment_failed` 标记 `PAST_DUE`，保留 Stripe retry 窗口，不立即伪装成 cancelled。
- `customer.subscription.deleted` 或最终无效状态结束对应 Monthly Entitlement。
- Owner immediate revoke 是独立管理动作，必须写原因和 Audit；它不删除 Stripe 历史。
- 移除一个 Entitlement 后重新汇总全部 Entitlement，再决定是否移除 Role。

## Member Control verification

Member Control 的 searchable user dropdown 只选择 Guild 成员。查看信息至少核对 Discord 加入
时间、会员开始时间、有效 Entitlement、来源、到期日、cancel-at-period-end 和 Member Role。
任何金额或付款状态疑问以 Stripe + Entitlement 对账为准，不以 Role 外观为准。

## Never do

- 不直接编辑数据库把 Stripe subscription 变为 ACTIVE。
- 不删除 webhook、payment event、价格快照或历史 Entitlement 来“修复”显示。
- 不因单个 Entitlement 到期就无条件移除 Role。
- 不在 Discord 卡片或日志展示 customer/subscription/checkout ID。
