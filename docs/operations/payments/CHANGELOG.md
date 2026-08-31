# Payment Operations Changelog

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
