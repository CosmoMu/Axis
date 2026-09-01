# AXIS Test Status

**Date:** 2026-09-01

## Summary

- Full pytest suite: PASS — 246 passed、0 failed、0 skipped
- Ruff: PASS
- Python compileall: PASS
- Static type checker: NOT CONFIGURED
- Core Gate A automated checks: PASS
- Analysis Gate B automated checks: PASS
- Database verifier: PASS
- Discord runtime verifier: PASS
- Analysis Fusion verifier: PASS
- Stripe Test setup verifier: HISTORICAL PASS / NOT RERUN AFTER KEY ROTATION REQUIREMENT
- Stripe Test external E2E verifier: HISTORICAL PASS / NOT RERUN AFTER KEY ROTATION REQUIREMENT
- Stripe dual-environment / kill switch / livemode / pricing / reconciliation regression: PASS
- Stripe Live readiness verifier: PASS — 0 blockers / payments enabled
- AXIS website build/tests: PASS — 4 passed；ESLint 0 errors
- Daily Results Review regression: PASS
- Soft Open Reset database / Discord verification: PASS
- Short-Term / Massive real E2E: NOT PASSED

## Commands executed

- .venv/bin/ruff check app tests scripts
- .venv/bin/python -m compileall -q app scripts
- .venv/bin/pytest -q
- .venv/bin/python scripts/verify_database.py
- .venv/bin/python scripts/verify_analysis_fusion.py
- .venv/bin/python scripts/verify_discord_runtime.py
- .venv/bin/python scripts/verify_stripe_test_setup.py
- .venv/bin/python scripts/verify_stripe_test_e2e.py
- .venv/bin/python scripts/verify_stripe_live_readiness.py
- .venv/bin/python scripts/reconcile_stripe_memberships.py --dry-run
- website: npm test
- website: npm run lint

没有在 pyproject.toml 或 CI 配置中发现 mypy / pyright，因此没有把未运行的 type check 标记为 PASS。

## Automated coverage

Core / Discord:

- Blueprint 精确结构、权限矩阵、unknown-resource safety、受控 rename 和 Bootstrap 幂等。
- Persistent View、Manager 控制面板、Message ID marker 和 Bot restart recovery。
- Public / Member / Manager / Owner / Bot persona。
- GENERAL Guide、Owner test commands 和 Public Identity Policy。
- Mentor Control 顶层按钮精简、详情 Edit / Delete、删除二次确认、未使用 Mentor 物理删除、
  关联 Trade 历史阻止和 `MENTOR_DELETED` Audit。
- Member Control searchable User Select、选择后详情按钮、会员开始/到期字段和 Member Role 展示。

Signal / Trade:

- Text、image、multi-image、Discord forward、真实文件签名和拒绝输入审计。
- Structured Output、router、invocation trace、missing fields 和 failure draft。
- 新建 ENTRY 完全缺价时使用已验证合约的当前 Massive 期权参考价补入 Review；报价失败保留
  可编辑草稿；任何已识别输入价格绝不被覆盖；内部保存 price source 与行情时间戳。
- S-00001 / A-00001 counter、Category/Mentor/Trade select、modal edit 和并发版本。
- Swing / LEAPS 分区编辑向导、订单类型与仓位下拉、单字段输入、加仓必填项和中文缺失提示。
- Publication claim / retry / finalize、单 Draft 单 Event 和 Public DTO 防泄漏。
- Swing / LEAPS Entry / Add / TP / SL / Runner / Close、category-scoped Active View 和
  weighted Results。
- SWING / LEAPS ENTRY 新中文卡、短公开引用和内部长 ID 隐藏。
- Mentor-first / AXIS-fill-missing 正股点位、真实 K 线、确定性 PNG、Fib 0.618 和
  Discord image attachment。
- 完整会员卡 review、点位编辑、编辑后图片重建、PT 方向递进和 Active View 持仓成本。

Short-Term:

- 简化 Review、无 Mentor/position、ST 编号和 Massive provider abstraction。
- Massive MarketTrackingService、新订单固定 TP1–TP41（10%、20%、50% 起每 25 个百分点至
  1000%）与单次触发。
- 可恢复的单合约 stale / unavailable / outlier / not-found 不触发系统级 ERROR，保存连续错误与
  精确错误码；新有效报价自动清零。认证等 provider 故障仍向上抛出并显示准确错误码。
- ST_TRACKING_V2 / V3 / V4 policy-version isolation；在途旧订单不会切换到新点位。
- High / Low Watermark、Fast Momentum Reversal、Overnight Tracking、Expiry-only Tracking 和
  policy version；Momentum TP 不推进固定编号。
- 验证任意回撤与隔夜跳空均不触发 SL / 保本 / trailing stop，只有合约到期结束追踪并生成
  幂等「到期」卡。
- LOTTO 默认 false、三类 Review toggle、编辑/Category/发布持久化与 public display。
- Short-Term 无 Active Button / Daily Summary；Swing / LEAPS「查看当前持仓订单」与 Summary。
- Swing / LEAPS Summary 只接受 Massive 当日正式期权收盘价，不接受其他日期 bar 或实时价。
- 极简 Daily Results 的全量 Short-Term 全追踪周期最高价收益、ST 订单号升序、Ticker、到期日、
  合约代码和幂等。

Daily Results Review:

- 实际 Market Close + delay 与 Early Close；Public Publish 时间固定为可配置 `16:15 ET`。
- 一个 Trading Date 一个 Draft；默认包含当天停止及仍在追踪的全部 Short-Term 和已关闭的
  Swing / LEAPS。
- Short-Term、Swing、LEAPS 展示规则与 LOTTO。
- Exclude with Reason / Re-Include 不删除 Trade 或 Event history。
- Display Edit 不修改 Trade；Correct Result、Public Correction 与 actor/before/after Audit。
- Preview、Publish Now、Scheduled Publish 去重、restart-safe claim 与不可变 Final Snapshot。
- Swing / LEAPS Daily Summary 不受 Exclude 影响；Short-Term 仍无 Daily Summary。

Membership / Stripe:

- Newcomer Application、PENDING/FLAGGED/APPROVED/REJECTED、答案与两项 agreement 持久化、
  duplicate protection 和 permanent Approval。
- 首次审批自动 Free Trial、Day Pass、Monthly、Gift、Manual Extension、多 Entitlement 与 Role
  reconciliation；Approval 后中断的 Trial 创建可由 reconciliation 幂等恢复。
- Free Trial 严格 7 Calendar Days：周末/美国市场休市日计入、批准时固化 duration/expiry、
  不调用 TradingCalendarService、终身一次、默认无 DM、无 Stripe / Card / Auto Renewal。
- Day Pass 保持 1 XNYS Trading Day；Trial 有效时阻止 Day Pass checkout，但允许 Monthly。
- Welcome 唯一 onboarding CTA `APPLY TO JOIN AXIS`；旧 Apply / Start Trial / Membership CTA 均不存在。
- Newcomer 只能只读 welcome/results/member-wins；所有其他 Blueprint channel 显式 DENY。
- Approved / expired / renamed / active Monthly / never-approved / rejected rejoin 场景与 Trial permanent
  history、database unique、Role sync failure、checkout fail-closed 均有覆盖。
- Risk Scanner 七项规则、protected identity normalization、持久去重、非自动决定和 aggregate health。
- Checkout / Portal、webhook signature、dedup、Price snapshot / Grandfathering。
- renewal、failure、cancel-at-period-end、PAST_DUE 与 provider event ordering。
- Test / Live config fallback rejection、environment-scoped Price/Entitlement/Session/Event。
- `PAYMENTS_ENABLED=false` 阻止 Checkout 但不改变已签名 webhook lifecycle；`livemode` mismatch
  在 event reservation 前拒绝。
- immutable V2 create/switch/rollback、既有 V1 grandfathering 和 reconciliation safe repair。
- final-period `invoice.paid` 不清除已预约的 cancel-at-period-end。

Analysis:

- Signal / Analysis queue 隔离、四类 Analysis、text/image/multi-image 和 strict schema。
- Mentor select、edit、rewrite、archive-only、archive+publish、delete 和 publication retry。
- Raw / Mentor / Stock Analyst / Final Fused / Public Snapshot traceability。
- Mentor-first / fill-missing、provenance、conflict、scenario gate 和 safe fallback。
- 确定性 Prediction Chart、无未来 K 线、source image 不转发和 renderer failure isolation。
- GEX 纯计算 Gamma/IV fallback、Walls、Zero Gamma 与 regime。

Operations / Security:

- Backup 命令不在 argv 泄露密码、Docker context 排除 .env。
- System Alert dedup、occurrence count、RECOVERY 和再次告警。
- Config-reference 与 config 一致、Secret-safe error/log boundaries。

## Live verifier evidence

Database:

- revision=20260831_0026
- source_messages=21
- trade_drafts=21
- trades=16
- trade_events=16
- trade_publications=16
- analysis_drafts=0
- mentor_analyses=0
- analysis_publications=0
- market_quote_snapshots=2
- daily_results_reviews=1
- daily_results_items=14
- membership_entitlements=2
- membership_trials=0
- newcomer_profiles=4（全部为 cutover 前 baseline 的 existing Production users；未授予 Trial）
- access_applications=0
- newcomer_risk_flags=0
- membership_prices=4（TEST 2 / LIVE 2；LIVE V1 已绑定并 current）
- payment_events=0
- system_alerts=2

Feature flags:

- FEATURE_ANALYSIS_ENABLED=true
- FEATURE_AXIS_STOCK_ANALYST_ENABLED=true
- FEATURE_DAILY_SUMMARY_ENABLED=true
- FEATURE_SHORT_TERM_TRACKING_ENABLED=true
- FEATURE_LAB_ENABLED=false
- FEATURE_MODEL_AB_ENABLED=false
- FEATURE_MOOMOO_ENABLED=false
- RESULTS_REVIEW_ENABLED=true

Discord:

- discord_runtime=PASS
- Bootstrap apply 已创建缺失的 `🛂・join-review`，并只更新 AXIS 已登记频道的 Newcomer / Bot
  overwrite；未删除、重命名或移动非 AXIS 资源。
- Apply 后 Bootstrap dry-run=REUSE 31 / UPDATE 0 / CREATE 0 / BLOCK 0；服务器修改 0。
- `⬛・GENERAL` position 0、`👋・welcome` position 0；runtime verifier 确认它是第一个公共入口，
  会员 Category 对 `@everyone` 隐藏。
- Welcome 持久卡片为全英文审批制文案并显示 7 天完整会员体验、No Card / No Automatic Renewal、
  `MY RISK IS NOT YOUR RISK` 与 Safety Notice，唯一按钮为 `APPLY TO JOIN AXIS`。
- Membership 卡片不再提供直接 Free Trial；Day Pass / Monthly checkout 在服务层要求 permanent
  Approval + completed Role sync，Newcomer 无法通过旧 URL / component 绕过。
- Member Wins 最新权限：`@everyone` view/send/attach，内容不计入官方 AXIS Results。
- personas=public, newcomer, member, manager, owner, bot
- GENERAL guides=idempotent
- owner test commands=13

Analysis Fusion:

- draft_layers=8/8
- archive_layers=4/4
- 当前历史归档 indicators/scenarios/path_points 均为 0；结构与回归测试 PASS，但仍需新的真实
  Mentor Fusion / Chart UX 验收。

Stripe Test（Pre-Soft-Open historical acceptance evidence）：

- setup=PASS
- Product=AXIS Membership
- Day Pass=USD 9.99 one-time
- Monthly=USD 99.99 monthly auto-renew
- local webhook=LISTENING
- external E2E=PASS
- Day Pass entitlement 曾达到 ACTIVE。
- Monthly entitlement 曾达到 ACTIVE，auto-renew=ENABLED，invoice.paid=PROCESSED。
- Discord Member Role E2E 曾为 PRESENT。
- Soft Open Reset 已清除这些 Stripe Test membership / payment records；当前数据库不再把它们
  视为 Production entitlement。Stripe Test 配置本身保留；当前运行环境已切换为 Live。
- 2026-08-31 只读 Dashboard 审计后，Test key 按暴露处理；外部 Test verifier 未重跑，
  `STRIPE_ENABLED=false` 且 Test listener 已禁用，等待轮换。

Stripe Live readiness（2026-08-31）：

- account activation / KYC / payout bank = PASS
- Live Product / Day Pass Price / Monthly Price = PASS
- public HTTPS webhook / signing secret / private relay = PASS
- Customer Portal / support / privacy / statement descriptor / customer-facing name = PASS
- `STRIPE_MODE=live`、`STRIPE_ENABLED=true`、`PAYMENTS_ENABLED=true`
- Live blocker count=0；Live reconciliation dry-run clean（provider=0 / local=0 / repairs=0）。
- `axisdesk.fyi` webhook unsigned request=401、relay unauthenticated=401、authorized relay=200、
  payment success page=200。
- Bot service running，Stripe Live subscriptions list request=HTTP 200。
- 未进行或伪造 Live payment；第一笔真实付款、Entitlement 和 Role E2E 仍待 Owner 验收。

Schema drift check：

- 本次 Stripe Price / Entitlement / Session / Payment Event schema 与 ORM 已一致。
- Alembic 仍报告两个早于本次工作的 constraint-name-only baseline drift：
  `membership_acknowledgements` 与 `short_term_tracking`；约束逻辑存在，未在 Stripe 任务中改动。

## Explicit failed / pending Live gate

Short-Term verifier evidence:

- short_term_tracking=21
- short_term_tracking_events=98
- short_term_daily_snapshots=14
- daily_results_publications=0
- market_quote_snapshots=2

2026-09-01 部署 Expiry-only Tracking 后，11 条仍未到期的旧 Protection Stop 已幂等恢复；
当前所有 15 条未到期订单均为 ACTIVE、`tracking_end_reason=None`、Protection Reason 为
`EXPIRY_ONLY`，待发布旧 Stop 通知为 0。数据库共有 21 条 Short-Term tracking 与 98 条
tracking event，但这些计数本身不能替代
对真实 Massive quote、TP / Expiry trigger、Discord event、Daily Results 和 restart recovery
的逐项验收，因此 Short-Term Live E2E 仍不能标记 PASS。Results Review 的代码、自动化、
migration、Discord command 与 job ready 已验证；首个真实 Eligible Trade 的定时公开仍是 Live
acceptance。

## Warnings

- discord.py 间接依赖 audioop，Python 3.13 将移除该模块。
- discord.ui modal 的 label API 有 deprecation warning；当前不影响 246 项测试结果。
