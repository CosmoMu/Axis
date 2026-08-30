# AXIS Live Mode Checklist

**Current decision:** STOP FOR FULL LIVE CLAIM

Core Bot 和 Analysis 已在目标 Guild 运行；Stripe 仍为 Test Mode；Short-Term Automated Tracking
尚未完成真实 E2E。任何单项启用都不代表整套系统已经 Production-complete。

## Short-Term / Massive

- [x] MASSIVE_API_KEY 已通过 .env 配置，文档和日志不记录值。
- [ ] 已发布 ST 订单自动写入 short_term_tracking。
- [ ] Massive 返回真实 quote，symbol/contract、价格和 timestamp 已核对。
- [ ] high/low watermark 在多次 quote 后正确更新。
- [ ] TP1–TP10 真实触发且每一级只发一次；频道中没有 Runner。
- [ ] Fast Momentum Reversal 真实路径已验证。
- [ ] Tracking Protection（-50% / Entry / 前一级 TP）与 Tracking Stop 真实路径已验证。
- [ ] Overnight 规则与下一交易日恢复已验证。
- [ ] Discord Entry / TP / 停止追踪与数据库状态一致，Short-Term 无 Active Button。
- [ ] Short-Term 不发 Daily Summary；Swing / LEAPS Summary 与官方 Results 已验证。
- [ ] Bot 重启恢复 tracking，且不重复 event / publication。
- [ ] Massive 故障和恢复能够产生去重 WARNING/ERROR 与 RECOVERY。

## Stripe Test Mode baseline

- [x] Test Product 和 Day Pass / Monthly Prices 已创建。
- [x] Test Secret、webhook signing secret、Price IDs 和 return URLs 只存在于 .env。
- [x] Day Pass Test payment 已完成。
- [x] Monthly Test signup 和 active auto-renewal 已完成。
- [x] invoice.paid 乱序 replay 与 event idempotency 已验证。
- [x] Entitlement 和 Member Role E2E 已验证。

## Stripe Live activation

- [ ] 公开 POST /webhooks/stripe 已通过受限 TLS reverse proxy。
- [ ] Live Product、Day Pass Price、Monthly Price 和 Customer Portal 已配置。
- [ ] Live Secret / IDs 只进入部署 Secret Store。
- [ ] Live webhook signing secret 已登记并验证。
- [ ] Day Pass Live payment、expiry 和 Role reconciliation 已验证。
- [ ] Monthly signup、renewal、payment failure 和 recovery 已验证。
- [ ] payment-method update、cancel-at-period-end 和 immediate revoke 已验证。
- [ ] duplicate / out-of-order webhook delivery 已验证。
- [ ] 新 Price 不改变既有 subscription，Grandfathering 已真实验证。
- [ ] 商家名称、支持邮箱、退款/取消条款和风险声明已检查。
- [ ] Checkout / Portal 页面已人工确认不暴露 Discord ID、内部 ID、Secret 或多余 metadata。
- [ ] Owner 已逐项批准 Live billing。

## Discord / Analysis UX

- [x] Discord Blueprint 幂等且不删除、移动或重命名非 AXIS 资源。
- [x] Public / Member / Manager / Owner / Bot 权限矩阵有自动化和 runtime verifier。
- [x] Welcome、Membership、Results、Member Wins 和 Lobby Guide 幂等。
- [x] Signal / Analysis Public DTO 有防泄漏测试。
- [ ] 一套真实 Short-Term review → LOTTO → tracking → 停止追踪的桌面/移动端验收完成。
- [ ] 一套真实 Mentor Analysis Fusion / Prediction Chart 的桌面/移动端验收完成。
- [ ] Review 发布后保留最终卡片，仅 ephemeral interaction 回执由 Discord 客户端 dismiss。

## Backup / Restore / Monitoring

- [x] PostgreSQL custom-format 本地备份存在且 pg_restore --list 可读。
- [x] 备份命令不在 argv、日志或 Git 暴露数据库密码。
- [ ] 加密 off-host backup、保留策略和失败告警已配置。
- [ ] 非生产环境完整 restore、数据核对与 rollback rehearsal 已完成。
- [ ] Database 故障 / 恢复演练完成。
- [ ] OpenAI 故障 / 恢复演练完成。
- [ ] Discord 故障 / 恢复演练完成。
- [ ] Scheduled Job 与 Membership expiry 故障 / 恢复演练完成。
- [ ] Massive 故障 / 恢复演练完成。
- [ ] Stripe webhook 故障 / 恢复演练完成。
- [ ] 外部健康检查、告警接收人和响应步骤已记录。

## Security and scope

- [x] .env、运行附件、日志和本地备份被 Git 忽略。
- [x] Secret 仅从 .env 或部署 Secret Store 读取。
- [x] FEATURE_LAB_ENABLED=false。
- [x] FEATURE_MODEL_AB_ENABLED=false。
- [x] 不读取 Moomoo 账户、持仓或订单，不执行自动交易。
- [ ] 发布前再次运行 tracked-files Secret scan 并记录 PASS。

Do not start AXIS LAB as part of this checklist.
