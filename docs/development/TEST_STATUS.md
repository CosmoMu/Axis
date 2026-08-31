# AXIS Test Status

**Date:** 2026-08-31

## Summary

- Full pytest suite: PASS — 211 passed、0 failed、0 skipped
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
- Publication claim / retry / finalize、单 Draft 单 Event 和 Public DTO 防泄漏。
- Swing / LEAPS Entry / Add / TP / SL / Runner / Close、category-scoped Active View 和
  weighted Results。
- SWING / LEAPS ENTRY 新中文卡、短公开引用和内部长 ID 隐藏。
- Mentor-first / AXIS-fill-missing 正股点位、真实 K 线、确定性 PNG、Fib 0.618 和
  Discord image attachment。
- 完整会员卡 review、点位编辑、编辑后图片重建、PT 方向递进和 Active View 持仓成本。

Short-Term:

- 简化 Review、无 Mentor/position、ST 编号和 Massive provider abstraction。
- Massive MarketTrackingService、固定 TP1–TP10（20%–1000%）与单次触发。
- High / Low Watermark、Tracking Protection、Fast Momentum Reversal、Overnight Tracking、
  Tracking Stop 和 policy version；Momentum TP 不推进固定编号。
- LOTTO 默认 false、三类 Review toggle、编辑/Category/发布持久化与 public display。
- Short-Term 无 Active Button / Daily Summary；Swing / LEAPS「查看当前持仓订单」与 Summary。
- 极简 Daily Results 的 TP highest / no-TP tracking-end 选择、LOTTO、TP 顺序和幂等。

Daily Results Review:

- 实际 Market Close + delay 与 Early Close；Public Publish 时间固定为可配置 `16:15 ET`。
- 一个 Trading Date 一个 Draft；默认包含所有 Ended Trade，Active Trade 排除。
- Short-Term、Swing、LEAPS 展示规则与 LOTTO。
- Exclude with Reason / Re-Include 不删除 Trade 或 Event history。
- Display Edit 不修改 Trade；Correct Result、Public Correction 与 actor/before/after Audit。
- Preview、Publish Now、Scheduled Publish 去重、restart-safe claim 与不可变 Final Snapshot。
- Swing / LEAPS Daily Summary 不受 Exclude 影响；Short-Term 仍无 Daily Summary。

Membership / Stripe:

- Free Trial、Day Pass、Monthly、Gift、Manual Extension、多 Entitlement 与 Role reconciliation。
- XNYS 交易日、风险确认、终身一次 Trial 和 scheduled expiry。
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

- revision=20260831_0024
- source_messages=0
- trade_drafts=0
- trades=0
- trade_events=0
- trade_publications=0
- analysis_drafts=0
- mentor_analyses=0
- analysis_publications=0
- daily_results_reviews=0
- daily_results_items=0
- membership_entitlements=1（真实 Discord Member Role reconciliation）
- membership_prices=4（TEST 2 / LIVE 2；LIVE V1 已绑定并 current）
- payment_events=0
- system_alerts=0

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
- Bootstrap dry-run=REUSE 29 / UPDATE 0 / CREATE 0 / BLOCK 0；服务器修改 0。
- Member Wins 最新权限：`@everyone` view/send/attach，内容不计入官方 AXIS Results。
- personas=public, member, manager, owner, bot
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

- short_term_tracking=0
- short_term_tracking_events=0
- short_term_daily_snapshots=0
- daily_results_publications=0
- market_quote_snapshots=0

Soft Open Reset 后没有正式 ST Trade；下一笔真实发布将是 ST-0001。真实 Massive quote、TP /
Protection trigger、Discord event、Daily Results 和 restart recovery 必须完成后，Short-Term
Live E2E 才能标记 PASS。Results Review 的代码、自动化、migration、Discord command 与 job
ready 已验证；首个真实 Eligible Trade 的定时公开仍是 Live acceptance。

## Warnings

- discord.py 间接依赖 audioop，Python 3.13 将移除该模块。
- discord.ui modal 的 label API 有 deprecation warning；当前不影响 208 项测试结果。
