# AXIS Known Issues

**Updated:** 2026-08-30

这里只记录当前真实问题和未完成验收。有意 deferred 的 AXIS LAB 不作为缺陷。

## P0 — Short-Term tracking 尚未完成 Live E2E

ST-0001 的旧 Mentor 关联已由 revision 0020 清理，Bot 已成功补注册
short_term_tracking=1、short_term_events=1（Entry）。当前仍没有真实 Massive quote 触发记录。

影响：

- 已证明已发布 Short-Term 订单能够幂等补注册跟踪。
- 仍不能证明 Massive 真实报价会驱动固定 TP、Momentum TP、protection 或 stop。
- 仍不能证明 Discord 自动事件、Daily Results 和重启恢复在真实行情路径上工作。

下一步在美股交易时段做一笔可控的真实端到端验收，并记录 quote timestamp、event、Discord
message 与重启幂等证据。

## P1 — Stripe 仍是 Test Mode

Day Pass 与 Monthly Test payment 已成功，但以下 Live 条件未完成：

- 公开 TLS webhook 与 Live signing secret。
- Live Product / Price / Key 和真实付款。
- renewal、payment failure、payment-method update、cancel、duplicate delivery。
- Price Grandfathering 的真实价格变更演练。
- Stripe 商家法律资料、退款/取消文案和人工隐私检查。

在 Live Checklist 全部签字前不得切换为 Live billing。

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

## Non-blocking dependency warning

Python 3.12 下 discord.py 的 audioop 依赖会提示 Python 3.13 removal warning。当前不影响
业务测试；升级 Python / discord.py 时需要重新验证音频兼容。

## Deliberately deferred, not bugs

- AXIS LAB、Model A / B、Generate / Shadow / Champion / Challenger。
- GEX Discord 频道、自动发布和交易接口。
- Moomoo 账户、持仓、订单、交易和任何自动下单。
- 图片生成模型；当前 Prediction Chart 使用确定性 renderer。
