# AXIS Known Issues

**Updated:** 2026-08-31

这里只记录当前真实问题和未完成验收。有意 deferred 的 AXIS LAB 不作为缺陷。

## P0 — Short-Term tracking 尚未完成 Live E2E

Soft Open Reset 后正式 Short-Term、tracking 与 event 均为 0；下一笔真实发布将使用 ST-0001。
当前仍没有 Soft Open Production 数据上的 Massive quote 触发记录。

影响：

- 自动化已证明已发布 Short-Term 订单能够幂等注册和恢复跟踪；正式 ST-0001 尚未产生。
- 仍不能证明 Massive 真实报价会驱动固定 TP、Momentum TP、protection 或 stop。
- 仍不能证明 Discord 自动事件、Daily Results 和重启恢复在真实行情路径上工作。

下一步在美股交易时段做一笔可控的真实端到端验收，并记录 quote timestamp、event、Discord
message 与重启幂等证据。

## P1 — Daily Results Review 首个 Production Day E2E 待验收

Results Review schema、Discord channel、Manager UI、Include / Exclude、不可删除历史、Preview、
Publish Now、`16:15 ET` scheduled publish 与 restart idempotency 均已实现并通过自动化。Soft
Open Reset 后尚无 Eligible Production Trade，因此仍需在第一个实际有停止/关闭订单的交易日
记录 Draft time、Manager interaction、Final Snapshot、Discord Message ID 与 scheduled dedup。

## P1 — Stripe Live 外部激活阻塞

双环境、kill switch、数据库隔离、价格版本、对账和 runbook 已完成；Day Pass 与 Monthly Test
payment 有历史成功证据，但以下 Live 条件未完成：

- Account activation、KYC 和 payout bank。
- 公开 TLS webhook 与 Live signing secret。
- Live Product / Price / Key 和真实付款。
- renewal、payment failure、payment-method update、cancel、duplicate delivery。
- Price Grandfathering 的真实价格变更演练。
- Stripe customer-facing business name、支持联系方式、statement descriptor、退款/取消文案和
  人工隐私检查。
- 2026-08-31 审计后 Test secret key 尚未轮换。

当前 `STRIPE_ENABLED=false`、`PAYMENTS_ENABLED=false`，旧 Test listener 已禁用。在 Live
Checklist 全部签字前不得切换为 Live billing。

## P1 — member-wins 权限漂移需要人工授权修复

2026-08-31 只读 Discord verifier 和 Bootstrap dry-run 确认唯一漂移：`🏆・member-wins` 的
`@everyone` 实际可发消息/附件，而 Blueprint 要求 `send=false / attach=false`，Member 仍可发。
Bootstrap apply 被 Discord 403 拒绝，AXIS BOT 当前缺少修改该 overwrite 的权限。没有创建、
删除、移动或重命名资源，也没有发生部分写入。

下一步由 Server Owner 临时授予 Bot 足够的 Manage Channels 权限后重跑严格 Bootstrap，或在
Discord UI 手动把该频道 `@everyone` 的 Send Messages / Attach Files 设为 deny，再运行
`scripts/verify_discord_runtime.py`。此问题与 Stripe 代码无关，但当前 Discord runtime verifier
不能标记 PASS。

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

## P2 — SWING / LEAPS 后续卡片尚未视觉统一

ENTRY / STARTER ENTRY 已升级为结构图 + 新文字卡。ADD、TP、RUNNER、CLOSE / SL 仍沿用
现有公开卡样式；这是本轮明确保留的后续视觉工作，不影响现有交易状态机。

## P2 — 两个旧 check constraint 名称与 ORM naming convention 不一致

Alembic drift check 只剩 `membership_acknowledgements` 和 `short_term_tracking` 两个早于本次 Stripe
工作的 constraint-name-only drift；约束逻辑都存在。本次 0024 已消除新 Stripe 四个约束的同类
问题，但为避免改动 Short-Term schema，没有顺带修复旧项。后续应作为独立、已备份迁移处理。

## Non-blocking dependency warning

Python 3.12 下 discord.py 的 audioop 依赖会提示 Python 3.13 removal warning。当前不影响
业务测试；升级 Python / discord.py 时需要重新验证音频兼容。

## Deliberately deferred, not bugs

- AXIS LAB、Model A / B、Generate / Shadow / Champion / Challenger。
- GEX Discord 频道、自动发布和交易接口。
- Moomoo 账户、持仓、订单、交易和任何自动下单。
- 图片生成模型；当前 Prediction Chart 使用确定性 renderer。
