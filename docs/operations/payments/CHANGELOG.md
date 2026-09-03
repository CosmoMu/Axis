# Payment Operations Changelog

## 2026-09-02 — Monthly V2 set to USD 149.99

- 在 Stripe Test 与 Live 分别创建 `MONTHLY_V2`：USD 149.99/month recurring。
- Test / Live current catalog 与运行配置均切换到 V2；Discord 和公开网站同步显示 USD 149.99。
- Monthly V1 保持不可变；已有 USD 99.99 订阅不自动迁移，继续 grandfathering。

## 2026-09-02 — Free Trial set to three trading days

- 新批准成员的 Free Trial 从 7 个自然日调整为 3 个 XNYS 交易日；周末和美国市场休市日不计入。
- 已创建 Trial 的固化到期时间保持不变，不追溯缩短。
- Free Trial 和 Day Pass 分别使用 3 个和 1 个 XNYS Trading Day；Stripe 产品、Price、订阅与
  续费逻辑不变。

## 2026-08-31 — Free Trial calendar-day separation

- Free Trial 从三个交易日改为领取时刻起连续 7 个自然日；周末和美国市场休市日计入。
- Day Pass 保持一个 XNYS Trading Day；`TradingCalendarService` 逻辑不变。
- migration `20260831_0025` 新增 duration unit/amount/start 字段并保留历史 Trial 到期时间。
- Trial 有效时阻止 Day Pass checkout，但 Monthly upgrade 继续开放。
- 本变更未修改 Stripe Product、Price、Live Secret、webhook 或订阅 lifecycle。

## 2026-08-31 — Stripe Live activation

- Stripe account activation、KYC、payout 和 Live API key 已完成。
- 创建并绑定 Live `AXIS Membership`、Day Pass USD 9.99 与 Monthly USD 99.99。
- 部署 `axisdesk.fyi` Live webhook、D1 最小事件队列与 Bot 私密 relay poll / ACK / retry。
- 配置 Customer Portal 的付款方式更新、账单记录和到期取消。
- 配置 AXIS 顾客展示名、支持联系方式、公开政策页和 `AXIS MEMBERSHIP` descriptor。
- 新增 payment success、cancel 与 Portal return 页面。
- readiness PASS / 0 blockers；Live reconciliation dry-run clean；`PAYMENTS_ENABLED=true`。
- 第一笔真实付款及完整 Day Pass / Monthly lifecycle E2E 仍待 Owner 完成；自动化未制造付款。

## 2026-08-31 — Dual environment foundation

- 新增独立 Test / Live env namespace、`STRIPE_MODE` 和 `PAYMENTS_ENABLED`。
- 数据库迁移到 `20260831_0023`：Price、Entitlement、Session 和 Payment Event 按环境隔离。
- 数据库 `20260831_0024` 只规范上述四个新 check constraint 名称，不改变业务数据或规则。
- Test V1 Product/Price binding 保留；Live V1 catalog 只建立未绑定占位，不含 Live ID。
- webhook 强制验证 `livemode` 与 metadata environment，dedup key 加入 environment。
- 新增 immutable Price version 管理、grandfathering、Stripe/AXIS 对账与 Owner-only alert。
- 新增受控 Live resource setup 和 readiness verifier；脚本不会自动开启收款。
- 本地 `.env` 从 legacy Test 命名迁移为 dual namespace，权限保持 0600。
- `STRIPE_ENABLED=false`、`PAYMENTS_ENABLED=false`；旧 Test listener 已停止并禁用，等待 Test key
  轮换。Stripe 账户激活/KYC、Live resources、公开 HTTPS webhook、Portal、
  支持联系方式、隐私检查和首笔真实付款尚未完成。
- Test key 因只读 Dashboard 审计按暴露处理，下一次 Test 外部调用前必须轮换。

本记录不包含 Secret、Stripe resource ID、客户 ID 或付款资料。
