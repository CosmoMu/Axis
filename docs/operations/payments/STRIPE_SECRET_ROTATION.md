# Stripe Secret Rotation

## Rules

Test 和 Live 分别轮换，禁止同时把一个环境的值复制到另一个环境。Secret 只写本地 `.env`
（0600）或部署 Secret Store；命令输出、截图、文档、Git 和聊天都不能含值。

## Secret key rotation

1. 设 `PAYMENTS_ENABLED=false`，保留 webhook 处理。
2. 确认当前 `STRIPE_MODE` 和目标环境。
3. 在 Stripe Dashboard 创建/roll 对应环境 secret key。
4. 更新对应 `STRIPE_TEST_SECRET_KEY` 或 `STRIPE_LIVE_SECRET_KEY`。
5. 重启服务，运行对应 readiness/setup verifier 和对账 dry-run。
6. 确认旧 key 没有调用后，在 Dashboard 撤销旧 key。
7. 记录时间、环境和结果，不记录 key。

## Webhook secret rotation

Webhook signing secret 与 endpoint 一一对应。新增 endpoint 或 secret 时先让旧、新 endpoint
短期重叠，分别配置正确 secret，确认投递和 dedup 后再停旧 endpoint。不得把 Test CLI signing
secret 用作 Live endpoint secret。

## Known rotation action

2026-08-31 的只读 Stripe Dashboard 审计使 Test publishable/secret key 出现在受限工具输出中。
虽然没有进入仓库、源码或文档，仍按已暴露处理：继续运行 Test 外部验证前，必须在 Dashboard
轮换 Test secret key，并更新 `.env`。Live key 当时不存在/未读取。

## Suspected leak

立即关闭 Checkout、撤销/roll 泄漏 key、检查 Stripe request logs、webhook endpoint 和近期资源
变更；运行 tracked-file 和 Git history secret scan；对账 Test/Live；创建 System Alert 与事故记录。
不要把疑似值复制进 ticket 或 Discord。
