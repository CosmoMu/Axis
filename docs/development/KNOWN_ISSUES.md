# AXIS Known Issues

## P1 — Moomoo SPX underlying snapshot unsupported

真实 OpenD 测试可读取 SPX option chain 和 SPXW option snapshot，但 `US..SPX` market snapshot
返回“不支持美股指数”。GEX 需要可靠 spot，因此 AXIS 对 SPX 明确返回
`SPX_PROVIDER_UNSUPPORTED`，不映射 SPY；SPY/QQQ/equity 不受影响。

## P1 — OPRA closed-market depth metadata limited

闭市 Gate 可读取 OPRA best bid/ask，但缓存 order book 只返回一档且 server bid/ask timestamp
为空。AXIS GEX 不依赖 depth；tracking 使用 option snapshot `update_time` 做 freshness。下一个
真实交易时段继续观察多档和 push timestamp，但这不构成购买额外行情包的依据。

## P1 — Public website GEX API is a separate Massive-based deployment

Discord `/gex` 已切换到本地 OpenD / Moomoo，但 `website/` 是独立 Sites 项目，不复用 Python GEX
service；其 serverless `/api/gex` 当前仍直接调用 Massive。托管 Worker 不能直接连接本机 OpenD，
因此网站迁移需要独立的安全 remote-Moomoo relay 设计。本轮网站 4 项测试与构建通过，但没有修改
或重新发布该独立项目，也不会把它误报为已完成 Moomoo cutover。

**Updated:** 2026-09-13

这里只记录当前真实问题和未完成验收。有意 deferred 的 AXIS LAB 不作为缺陷。

## P0 — Multi-Agent Research 真实 Massive E2E 受 provider rate limit 阻塞

AXIS-native graph、strict schemas、permissions、cache/single-flight、数据库、outcome/memory 和
自动化回归已通过；生产 migration 为 `20260913_0033`。真实 smoke 中 Massive 并发边界返回
`MASSIVE_RATE_LIMITED`：一次 SPY 请求恢复了 Technical + News，但 GEX 与 Sentiment 不可用，
没有满足 Technical + two optional coverage gate。系统按设计保存 insufficient-data view 并保持
LLM calls=0，没有使用未来、陈旧或虚构数据。

当前 Research 必须保持 TEST-only。需在 provider window/plan capacity 稳定后重跑五个 ticker、
cache 与 Discord Desktop/Mobile；Member Lounge launch 需要未来单独 Owner approval。

## P0 — Stock Analyst Member Lounge 交易时段与移动端证据待积累

Cosmos v0.1 parity、Moomoo 8-ticker read-only、card/chart、cache/single-flight/limits、权限与自动化
均已通过；Guild `/stock`、真实 SPY 图、Member/Manager/Owner lounge gate、30/60 秒 cooldown、
Manager/Owner bypass 与 command visibility verifier 均已验证。Owner 已于 2026-09-05 要求上线，
runtime 当前为 `MEMBER_LOUNGE`。尚未积累真实会员并发、交易时段 freshness 与移动端运营证据。

Cosmos v0.1 只使用 Daily timeframe，且不计算 RVOL、Bollinger、VWAP 或真实逐笔机构资金流。
AXIS 没有伪造这些组件：RVOL 保持 unavailable，Volume 明确标为 20 日 OHLCV pressure proxy，
POC/VA 是 Daily OHLCV high-low 分箱代理。闭市验收已完成；交易时段 live/stale UX 仍待后续
受控验证。Phase 1 没有 LLM rewrite，因此 `STOCK_ANALYST_LLM_FAILURE` 只是保留错误类型。

## P0 — GEX Explorer SPX underlying snapshot 不受支持

V7 Moomoo option-chain aggregation、card、heatmap、cache、single-flight、limits、audit 与 alerts
已实现；严格 `gex TICKER`、Member/Manager/Owner role gate 和 exact channel gate 已通过自动化。
Member Lounge 已于 2026-09-05 获 Owner 批准并部署，runtime verifier PASS。真实 closed-market checks 中 SPY、QQQ、NVDA、TSLA、AAPL 均 PASS；当前
Moomoo 可读取 SPXW chain / option snapshot，但 OpenD 对 `US..SPX` underlying snapshot 返回不支持
美股指数，故返回 `SPX_PROVIDER_UNSUPPORTED`。禁止用 SPY 替代 SPX。

仍需积累真实会员请求的 Discord Desktop/Mobile、交易时段 freshness、rate-limit 和
entitlement 证据。

## P0 — Owner Personal Moomoo Execution real-account DRY_RUN E2E blocked

代码、migration、Discord Owner-only control、synthetic DRY_RUN 与 fail-closed LIVE gate 已完成。
本机 OpenD 已启动且行情连接正常；个人执行 verifier 的 broker fill-list 只读步骤仍返回
`MOOMOO_FILL_LIST_FAILED`，因此尚未完成目标 account、positions、orders、fills 与 SIMULATE
lifecycle 的完整核对。该问题不阻塞市场数据 cutover，但继续阻止 Personal LIVE writes。

在 read-only + SIMULATE E2E、restart、Discord UX 和 kill-switch rehearsal 完成前：

- LIVE broker writes 保持禁用。
- `PERSONAL_DRY_RUN_VALIDATED=false`。
- 不调用/自动化 `unlock_trade`。
- 不把 DRY_RUN decision 视为真实 fill 或真实 performance。

## P0 — Newcomer Gate 真实用户生命周期 E2E 待验收

Newcomer Role、Discord overwrite、中文 Application、入群审核、审批后自动 Trial、终身唯一约束、
Risk Scanner 与 Role reconciliation 已完成自动化和 production-safe rollout 工具。仍需使用真实
Discord 新账户完成 Join → Apply → Approve → Trial → Expiry → Rejoin 的时钟验收；在此之前不能把
Newcomer Gate 标记为 Live Complete。

## P0 — Short-Term tracking 尚未完成 Live E2E

生产数据库已有 Short-Term tracking/event/snapshot 记录，但尚未完成按验收清单逐项核对的真实
Moomoo 交易时段 / Discord 完整证据链。

2026-09-01 已修复单个期权 MID quote 超过 120 秒未更新时反复产生系统级 ERROR / RECOVERY 的
告警抖动；此类数据质量状态现在留在对应 tracking，且不会使用陈旧价格触发 TP。真实 provider
故障仍保留系统告警。

影响：

- 自动化已证明已发布 Short-Term 订单能够幂等注册和恢复跟踪，数据库也已有生产追踪记录。
- 现有计数尚不能证明 Moomoo 真实报价已按清单完整驱动固定 TP、Momentum TP、Expiry 事件与
  当天 Results 发布。
- 仍需核对 Discord 自动事件、Daily Results 和重启恢复的真实行情完整证据链。

下一步在美股交易时段做一笔可控的真实端到端验收，并记录 quote timestamp、event、Discord
message 与重启幂等证据。

## P0 — Simple Tracked Swing 真实 E2E 待验收

Swing V2 code、280 项全量回归、forward-only migration 与生产分类检查已经通过，但尚未用一笔
真实新 Swing 完成 Entry → Moomoo quote → fixed TP → Manager Close → EOD / Results → restart
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
- GEX 自动发布和交易接口；Member Lounge 只读查询入口已上线。
- 除已授权但仍处于 DRY_RUN gate 的 Owner-only Personal Moomoo Execution 外，任何会员交易、模型
  扫描或其他自动下单。
- 图片生成模型；当前 Prediction Chart 使用确定性 renderer。
