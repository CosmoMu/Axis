# AXIS GENERAL 与 Membership Payment

## GENERAL 频道

- `👋・welcome`：所有人可见，仅 Bot 发布；包含 `JOIN AXIS`。
- `💳・subscriptions`：单一 `AXIS Membership`，价格来自配置，不显示具体支付商名称。
- `📊・results`：仅 AXIS 系统记录的官方结果，普通用户不能发言。
- `💬・lobby`：公开聊天，不接收自动 Signal、Analysis 或 Results。
- `🏆・member-wins`：公开可见，仅 Member 可发文字与图片；置顶说明与官方 Results 隔离。

五条长期消息的 Discord Message ID 保存在 `guild_config`。Bot 启动时先按 ID 编辑，ID
失效时再按 Embed footer marker 恢复，只有两者都不存在才创建。重复启动不会产生重复卡片。

## 环境配置

所有值只写入 `.env` 或部署 Secret Manager：

```text
MEMBERSHIP_PRICE_DISPLAY=价格见支付页面
SUBSCRIPTION_URL=https://checkout.example.com/axis
CUSTOMER_PORTAL_URL=
PAYMENT_PROVIDER=external
PAYMENT_WEBHOOK_HOST=127.0.0.1
PAYMENT_WEBHOOK_PORT=8787
PAYMENT_WEBHOOK_SECRET=<strong-random-secret>
MEMBERSHIP_SESSION_TTL_MINUTES=30
```

`CUSTOMER_PORTAL_URL` 可选；未配置时不显示 Manage Membership。`SUBSCRIPTION_URL` 或
`PAYMENT_WEBHOOK_SECRET` 任一缺失时，Checkout 安全禁用。

## Provider-neutral Contract

点击 `JOIN AXIS` 后，AXIS 创建一次性 `membership_session`，并把以下 query metadata 附加到
Checkout URL：

```text
discord_user_id=<Discord Snowflake>
membership_session_id=<opaque session token>
payment_provider=<provider name>
```

支付页面必须原样保存这两个身份字段，并在 webhook metadata 中返回。不得用 email 或
Discord username 猜测会员身份。

Webhook endpoint：

```text
POST /webhooks/membership
X-AXIS-Signature: sha256=<HMAC-SHA256 hex digest>
```

签名内容是未经修改的原始 request body，密钥是 `PAYMENT_WEBHOOK_SECRET`。若接收器监听本机
回环地址，生产部署必须通过受控的公开 TLS reverse proxy 暴露该 endpoint。

第一版 provider adapter 接受：

```json
{
  "event_id": "provider-event-id",
  "event_type": "subscription.active",
  "status": "ACTIVE",
  "customer_id": "provider-customer-id",
  "subscription_id": "provider-subscription-id",
  "current_period_start": "2026-08-30T00:00:00Z",
  "current_period_end": "2026-09-30T00:00:00Z",
  "cancel_at_period_end": false,
  "metadata": {
    "discord_user_id": "1234567890",
    "membership_session_id": "opaque-session-token"
  }
}
```

支持的 event type：`subscription.active`、`subscription.updated`、
`subscription.past_due`、`subscription.cancelled`、`subscription.expired`。

## Role Lifecycle

- `ACTIVE`：创建/更新 Membership，并添加 Member Role。
- `CANCEL_AT_PERIOD_END`：保留 Role 到 `current_period_end`，Scheduled Job 到期移除。
- `PAST_DUE`：当前版本不保留 Member Role；provider 恢复为 ACTIVE 后可再次同步。
- `CANCELLED` / `EXPIRED`：立即使支付会员失效并移除 Role。
- Manager `Revoke Now`：立即标记 REMOVED 并移除 Role。
- Gift / Manual：继续使用现有 Member Role，不依赖 Payment Provider。

Webhook event 以 `provider + event_id` 幂等；若数据库已经处理而 Discord Role 更新临时失败，
provider 重试同一 event 会再次执行 Role sync，不重复创建 Membership。

## 上线验收

生产收款前，必须在 provider sandbox 依次验证：

1. 两个不同 Discord User 的 Checkout metadata 不串号。
2. ACTIVE 自动添加 Member Role。
3. 同一 webhook 重放不创建重复 Membership/Event。
4. period-end cancel 在到期前保留 Role，到期后移除。
5. immediate cancel/revoke 立即移除 Role。
6. Gift 和 Manual Role sync 不受支付 webhook 干扰。
