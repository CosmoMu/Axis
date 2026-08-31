# Payment Incident Runbook

## First response

1. 设 `PAYMENTS_ENABLED=false` 并重启，停止新 Checkout。
2. 不关闭 webhook，不删除 Stripe/AXIS 历史，不移除全部 Member Role。
3. 记录环境、开始时间、安全 error code 和影响数量，不记录客户 ID 或 Secret。
4. 运行 readiness verifier、对账 dry-run和数据库备份。

## Webhook outage

确认 HTTPS、证书、reverse proxy、endpoint status 和 signing secret 所属环境。恢复后让 Stripe
retry，检查 duplicate/out-of-order 幂等，再运行对账。不要手工伪造 event ID。

## Signature or livemode mismatch

保持 Checkout 关闭。核对 `STRIPE_MODE`、endpoint secret 和 Dashboard livemode。跨环境事件应被
拒绝且不写 dedup record。若存在错误环境写入，先备份并升级处置，不直接删表。

## Paid but no access

以 Stripe payment/subscription 状态和签名 event 为证据，运行对账 dry-run。只在 Price mapping、
environment 和 Discord identity 全部可证明时 Apply。随后通过 `MembershipAccessService` 同步 Role。

## Access but no valid payment

先检查 Free Trial、Gift、Manual Extension 或其他有效 Entitlement；Role 本身不是付款证据。若无
有效来源，Owner 使用带原因的 revoke，并保存 Audit，不删除历史。

## Duplicate charge or wrong price

停止 Checkout，确认 current Price version 和 Stripe Dashboard。不要修改旧 Price。退款/争议在
Stripe 按公司政策处理；AXIS 只同步最终 lifecycle。错误版本通过新 Price 或 current rollback
修复，既有订阅保持 grandfathering，除非客户明确同意迁移。

## Secret leak

执行 `STRIPE_SECRET_ROTATION.md`。优先撤销 key、查 Stripe request logs、扫描 tracked files/history、
再对账。Live 与 Test 分别处置。

## Database or reconciliation failure

保持 webhook 可重试，先验证数据库连接和 migration revision，禁止重复运行未知状态的写修复。
使用最近一次已验证 custom dump 在非生产环境演练 restore；恢复后 dry-run，再 apply。

## Recovery gate

告警已 RECOVERY、webhook backlog 清空、对账 clean、Role 抽样正确、Secret scan PASS、事故记录
完成并经 Owner 批准后，才能重新设 `PAYMENTS_ENABLED=true`。
