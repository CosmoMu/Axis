# AXIS Known Issues

**Updated:** 2026-09-04

这里只记录当前真实问题和未完成验收。有意 deferred 的 AXIS LAB 不作为缺陷。

## P0 — GEX Explorer 仍为 TEST ONLY；SPX Provider entitlement 不足

Phase 1 `/gex`、Massive option-chain aggregation、card、heatmap、cache、single-flight、limits、audit
与 alerts 已实现，但当前只允许 Owner 在 `🧪・card-testing` 使用。Member Lounge 没有开放，也不应
写成 Live。真实 closed-market checks 中 SPY、QQQ、NVDA、TSLA、AAPL 均 PASS；当前 Massive
账户对 SPX index snapshot 无 entitlement，option-chain seed 也无法提供可用 underlying spot，故
返回 `GEX_SPX_UNSUPPORTED`。禁止用 SPY 替代 SPX。

在 Owner 明确发送 `APPROVE GEX LOUNGE LAUNCH` 前，不得实施/启用 Phase 2。正式上线前还需真实
Discord Desktop/Mobile Test Gate 证据与交易时段 freshness 验证。

## P0 — Owner Personal Moomoo Execution 外部 DRY_RUN E2E 被 OpenD 阻塞

代码、migration、Discord Owner-only control、synthetic DRY_RUN 与 fail-closed LIVE gate 已完成。
本机 OpenD app 已安装，但 `127.0.0.1:11111` 当前没有监听，因此尚不能读取并核对目标 account、
positions、orders、fills 或执行 SIMULATE lifecycle。必须由 Owner 启动/登录 OpenD 并明确选择
security firm 和唯一 US securities account；不能猜测账户。

在 read-only + SIMULATE E2E、restart、Discord UX 和 kill-switch rehearsal 完成前：

- LIVE broker writes 保持禁用。
- `PERSONAL_DRY_RUN_VALIDATED=false`。
- 不调用/自动化 `unlock_trade`。
- 不把 DRY_RUN decision 视为真实 fill 或真实 performance。

## P0 — Newcomer Gate 真实用户生命周期 E2E 待验收

Newcomer Role、Discord overwrite、中文 Application、join-review、审批后自动 Trial、终身唯一约束、
Risk Scanner 与 Role reconciliation 已完成自动化和 production-safe rollout 工具。仍需使用真实
Discord 新账户完成 Join → Apply → Approve → Trial → Expiry → Rejoin 的时钟验收；在此之前不能把
Newcomer Gate 标记为 Live Complete。

## P0 — Short-Term tracking 尚未完成 Live E2E

生产数据库当前已有 21 条 Short-Term tracking、101 条 tracking event 与 29 条 Short-Term
daily snapshot，但尚未完成按验收清单逐项核对的真实 Massive / Discord 完整证据链。

2026-09-01 已修复单个期权 MID quote 超过 120 秒未更新时反复产生系统级 ERROR / RECOVERY 的
告警抖动；此类数据质量状态现在留在对应 tracking，且不会使用陈旧价格触发 TP。真实 provider
故障仍保留系统告警。

影响：

- 自动化已证明已发布 Short-Term 订单能够幂等注册和恢复跟踪，数据库也已有生产追踪记录。
- 现有计数尚不能证明 Massive 真实报价已按清单完整驱动固定 TP、Momentum TP、Expiry 事件与
  当天 Results 发布。
- 仍需核对 Discord 自动事件、Daily Results 和重启恢复的真实行情完整证据链。

下一步在美股交易时段做一笔可控的真实端到端验收，并记录 quote timestamp、event、Discord
message 与重启幂等证据。

## P0 — Simple Tracked Swing 真实 E2E 待验收

Swing V2 code、280 项全量回归、forward-only migration 与生产分类检查已经通过，但尚未用一笔
真实新 Swing 完成 Entry → Massive quote → fixed TP → Manager Close → EOD / Results → restart
证据链。当前状态必须保持 `CODE COMPLETE / DB MIGRATED / LIVE E2E PENDING`。

迁移时发现五笔既有 Swing，其中四笔 Active；全部已标记为 `LEGACY_SWING` 并保留原 Mentor、
Position、事件和公开历史。它们继续旧引擎直到关闭，不是迁移错误，也不得手工改成 Simple。

## P1 — Daily Results Review 首个 Production Day E2E 待验收

Results Review schema、Discord channel、Manager UI、Include / Exclude、不可删除历史、Preview、
Publish Now、`16:15 ET` scheduled publish 与 restart idempotency 均已实现并通过自动化。Soft
Open Reset 后尚无 Eligible Production Trade，因此仍需在第一个实际有停止/关闭订单的交易日
记录 Draft time、Manager interaction、Final Snapshot、Discord Message ID 与 scheduled dedup。

## P1 — Stripe Live 第一笔真实付款与 lifecycle 待验收

双环境、kill switch、数据库隔离、价格版本、对账和 runbook 已完成；账户、KYC、payout、Live
Product/Prices、公开 webhook、Portal、顾客展示资料和 0-blocker readiness 均已完成，Live Checkout
已启用。但以下真实 lifecycle 证据仍未完成：

- 第一笔真实 Day Pass 或 Monthly 付款与 Role 授权。
- renewal、payment failure、payment-method update、cancel、duplicate delivery。
- Price Grandfathering 的真实价格变更演练。
- 2026-08-31 审计后 Test secret key 尚未轮换。

当前 `STRIPE_MODE=live`、`STRIPE_ENABLED=true`、`PAYMENTS_ENABLED=true`，旧 Test listener 已禁用。
系统可接收真实付款，但不得在 Owner 完成第一笔真实 E2E 前把全部 lifecycle 标记为验收完成。

## P1 — Production backup / restore 不完整

本地已有经过 pg_restore --list 验证的 custom-format backup，但没有 off-host 备份证明，
也没有在非生产环境完成一次完整 restore、数据核对和 rollback rehearsal。

## P1 — Production monitoring 尚未完成故障演练

System Alerts、结构化日志和 verifier 已实现；尚未对 Database、OpenAI、Discord、Jobs、
Membership expiry、Massive 和 Stripe 逐项做真实故障/恢复演练，也没有集中式外部健康监控。

## P2 — Analysis / Prediction Chart 仍需真实 UX 复核

Analysis Fusion 已有真实 Published 数据，确定性 chart renderer 也已实现，但尚未完成一套记录化
的 Mentor-first 点位、warnings、公开卡片和移动端图片体验验收。此项不阻止文字 Analysis 使用，
但阻止把视觉体验标记为最终完成。

## P2 — Select 菜单容量

Mentor、Trade 和 Active View 受 Discord 单个 Select / Embed 25 项限制。当前规模可用；
超过 25 项时需要分页或搜索，不应通过丢弃数据规避。

## P2 — Legacy Swing / LEAPS 后续卡片尚未视觉统一

Legacy Swing 与 LEAPS 的 ENTRY / STARTER ENTRY 已升级为结构图 + 新文字卡。ADD、TP、RUNNER、
CLOSE / SL 仍沿用现有公开卡样式；Simple Tracked Swing 不使用这些动作或结构图。

## P2 — 两个旧 check constraint 名称与 ORM naming convention 不一致

Alembic drift check 只剩 `membership_acknowledgements` 和 `short_term_tracking` 两个早于本次 Stripe
工作的 constraint-name-only drift；约束逻辑都存在。本次 0024 已消除新 Stripe 四个约束的同类
问题，但为避免改动 Short-Term schema，没有顺带修复旧项。后续应作为独立、已备份迁移处理。

## Non-blocking dependency warning

Python 3.12 下 discord.py 的 audioop 依赖会提示 Python 3.13 removal warning。当前不影响
业务测试；升级 Python / discord.py 时需要重新验证音频兼容。

## Deliberately deferred, not bugs

- AXIS LAB、Model A / B、Generate / Shadow / Champion / Challenger。
- GEX Member Lounge 发布、自动发布和交易接口；Owner-only card-testing Phase 1 不属于 deferred。
- 除已授权但仍处于 DRY_RUN gate 的 Owner-only Personal Moomoo Execution 外，任何会员交易、模型
  扫描或其他自动下单。
- 图片生成模型；当前 Prediction Chart 使用确定性 renderer。
