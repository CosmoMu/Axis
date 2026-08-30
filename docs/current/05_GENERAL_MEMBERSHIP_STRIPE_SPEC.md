# AXIS General / Membership / Stripe Lock

**版本：** 2026-08-30

**状态：** 当前 Source of Truth；与旧 Membership、Stripe、General UI 或公开身份要求冲突时，
以本文件为准。

## 范围边界

- 保留已完成的 Signal、Analysis、Mentor、Member、Results 与 Active Trades。
- 当前只启用 AXIS Core；`FEATURE_LAB_ENABLED`、`FEATURE_MODEL_AB_ENABLED` 与
  `FEATURE_MOOMOO_ENABLED` 必须同时为 `false`。
- 不开发 Model A/B、模型扫描、自动交易或任何 AXIS LAB 工作流。

## 公开身份与隐私

- 对外品牌只有 `AXIS`，Bot 为 `AXIS BOT`，匿名运营人格默认 `VALE`。
- `PublicIdentityPolicy` 是所有 Member-facing Card、DTO、支付文案和公开消息的统一边界。
- Owner ID 只能用于内部权限；真实身份、私人联系方式、个人资料、内部备注和内部来源不得
  出现在会员界面或 customer-facing Stripe metadata。
- 代码不生成或覆盖 Avatar，也不伪造职业履历。Stripe 法定/KYC 要求不得绕过或伪造。

## Membership 产品

- 仅有一个 `Member` Role，三种公开方案获得完全相同的频道权限。
- `FREE TRIAL`：$0、3 个 XNYS Trading Days、每个 Discord User 终身一次、不需要支付方式。
- `DAY PASS`：$9.99、一次性付款、1 个 XNYS Trading Day、Stripe `mode=payment`。
- `MONTHLY`：$99.99/month，Stripe 月度订阅；不换算成日历日或交易日。
- Trial 和 Day Pass 在收盘前把当前 Session 计作 Day 1；收盘后、周末或正式休市日从下个
  Session 开始，最后一天在 `23:59:59 America/New_York` 到期。

## 风险确认与访问

- 第一次领取或购买前必须展示 `AXIS_RISK_DISCLOSURE_V1`，用户点击 `I UNDERSTAND` 后才可
  激活 Trial 或创建 Checkout。
- Trial Claim 和带版本的 Acknowledgement 永久保存，退出并重新加入 Server 不能重领。
- `MembershipAccessService` 按 Entitlement 合并访问；只要 `FREE_TRIAL`、`DAY_PASS`、
  `MONTHLY`、`GIFT`、`MANUAL` 或 `MANUAL_EXTENSION` 任意一个有效，Member Role 就必须存在。
- `PAST_DUE` 在 Stripe 重试期间保留访问；只有全部 Entitlement 失效才移除 Role。

## Stripe 与价格

- `membership_prices` 是展示和收费的唯一价格目录；业务代码不得直接写死公开价格。
- 每次购买保存 `pricing_version`、Stripe Price ID 和 signup amount。新价格必须新建版本，
  不得自动迁移既有 Monthly Subscription。
- Discord 按 User ID 动态创建 Checkout 和 Customer Portal，不使用固定 Payment/Portal Link。
- Stripe 签名 Webhook 是付款 Source of Truth，至少处理完成付款、续费成功、续费失败、订阅
  更新和订阅删除；Provider Event ID 必须幂等，普通日志和数据库不保存完整支付 Payload。
- Live Mode 前必须完成 Stripe Test Mode E2E 和人工公开隐私检查。

## Manager 与 General UI

- Manager 支持 View、Gift、Extend、Cancel at Expiry 与 Revoke Now。
- Extension 必须创建独立 `MANUAL_EXTENSION`，不能改写 Trial、Day Pass 或 Stripe 周期；支持
  Trading Day、Calendar Day、Calendar Month 与 Custom，完整保存审计字段。
- General 固定为 Welcome、Subscriptions、Results、Lobby 与 Member Wins。Lobby 仅保留英文
  Topic；Card 保持极简，不重复 Logo、不显示版本 Footer。
- System Alerts 与 Card Testing 仅 Owner + AXIS BOT 可见；测试卡不能写入正式交易、分析、
  Results 或 Active Trades 数据。

## 上线 Gate

实际状态、Stripe 人工项目和停止条件以：

- `docs/development/LIVE_MODE_CHECKLIST.md`
- `docs/development/STRIPE_PUBLIC_PRIVACY_CHECKLIST.md`

为准。完成本轮实现后停止，不自动开始 AXIS LAB。
