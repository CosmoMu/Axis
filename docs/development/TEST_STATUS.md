# AXIS Test Status

**Date:** 2026-09-05

## Summary

- Full pytest suite: PASS — 311 collected / passed、0 failed、0 skipped
- Ruff: PASS
- Python compileall: PASS
- Static type checker: NOT CONFIGURED
- Core Gate A automated checks: PASS
- Analysis Gate B automated checks: PASS
- Analysis chart-source schema width / migration: PASS
- Database verifier: PASS
- Discord runtime verifier: PASS
- Analysis Fusion verifier: PASS
- Analysis Pilot-style 日 K Prediction Chart：PASS — 真实 Daily OHLC、HLX 25 / 90
  High-Low EMA、Mentor-first 关键位、白色单一预测路径、缺失 OHLC 时拒绝合成蜡烛
- Stripe Test setup verifier: HISTORICAL PASS / NOT RERUN AFTER KEY ROTATION REQUIREMENT
- Stripe Test external E2E verifier: HISTORICAL PASS / NOT RERUN AFTER KEY ROTATION REQUIREMENT
- Stripe dual-environment / kill switch / livemode / pricing / reconciliation regression: PASS
- Stripe Live readiness verifier: PASS — 0 blockers / payments enabled
- AXIS website build/tests: PASS — 4 passed；ESLint 0 errors
- Daily Results Review regression: PASS
- Soft Open Reset database / Discord verification: PASS
- Short-Term / Massive real E2E: PARTIAL — live SPXW quote PASS；真实 TP / internal Expiry E2E PENDING
- Simple Tracked Swing: CODE / MIGRATION TEST PASS；真实 Discord / Massive E2E PENDING
- Swing V2 post-deploy runtime: PASS — Bot running、runtime hash match、Discord verifier PASS、
  Legacy Swing 未误注册（new Swing tracking tables remain 0 before first Simple Swing）
- GEX Explorer Phase 1: TEST ONLY / PASS — Owner-only card-testing、Massive 成交量 GEX / spot /
  真实 5 分钟 K 线正式数据、Moomoo 后台 shadow、中文双面板图、cache/single-flight/limits/audit
  均通过；
  Member Lounge 未上线。
- GEX Live symbols: SPY / QQQ / NVDA / TSLA / AAPL PASS（各 10 valid expirations）；SPX
  `GEX_SPX_UNSUPPORTED`（当前 Massive entitlement blocker，未 fallback SPY）。
- GEX V3 RDDT Massive-primary / Moomoo-shadow evidence: PASS — Massive 10 valid expirations /
  338 option contracts / 240 genuine 1-minute RTH bars；Moomoo shadow comparison does not select
  public output；1800x1125 balanced PNG rendered and visually reviewed。
- GEX V3 AVGO real comparison: PASS — Massive 10 valid expirations / 654 option contracts /
  240 one-minute RTH bars；Moomoo shadow 240 bars / 240 overlapping timestamps；latest common-close
  difference `0.0545%`、timestamp difference `0s`；Call Wall / Put Wall / 0 Gamma 全部显示。
- GEX V4 tiered levels / V5 volume-flow evidence: historical PASS — 原 Gross Wall
  压力/支撑展示语义已由 V6 Net Magnet / Acceleration 取代；Massive 5 分钟正式源与 Moomoo
  shadow 边界保持不变。
- GEX V6 Net Magnet / Acceleration: PASS — AVGO Massive 78 根 5 分钟 K 线、10 valid
  expirations、654 contracts；上方正 Net GEX 磁吸 370 / 357.5、下方磁吸 355 / 332.5、
  负 Net GEX 加速区独立计算，0 Gamma 359.79。Gross Call Wall 360 / Put Wall 355 只作
  参考；自动验证 `magnets_do_not_overlap_acceleration=true`。新增回归覆盖 Gross Call Wall
  位于负 Net GEX 执行价时不得被标为磁吸。

## Commands executed

- .venv/bin/ruff check app tests scripts
- .venv/bin/python -m compileall -q app scripts
- .venv/bin/pytest -q
- .venv/bin/python scripts/verify_gex_explorer.py
- .venv/bin/python scripts/verify_database.py
- .venv/bin/python scripts/verify_analysis_fusion.py
- .venv/bin/python scripts/verify_discord_runtime.py
- .venv/bin/python scripts/verify_personal_execution.py
- .venv/bin/python scripts/verify_stripe_test_setup.py
- .venv/bin/python scripts/verify_stripe_test_e2e.py
- .venv/bin/python scripts/verify_stripe_live_readiness.py
- .venv/bin/python scripts/reconcile_stripe_memberships.py --dry-run
- website: npm test
- website: npm run lint
- .venv/bin/python scripts/bootstrap_discord.py（read-only dry-run）

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
- SWING / LEAPS ENTRY 新中文卡；所有 `P-*` publication reference 隐藏，只显示正式订单号。
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
- 验证任意回撤与隔夜跳空均不触发 SL / 保本 / trailing stop；合约到期只在后台幂等结束
  Tracking 并进入 Results / Audit，不向 Short-Term 频道发卡。
- LOTTO 默认 false、三类 Review toggle、编辑/Category/发布持久化与 public display。
- Short-Term 无 Active Button / Daily Summary；Swing / LEAPS「查看当前持仓订单」与 Summary。
- Swing / LEAPS Summary 只接受 Massive 当日正式期权收盘价，不接受其他日期 bar 或实时价。
- 极简 Daily Results 使用从入场到到期/停止追踪期间的 lifetime high；覆盖历史高点高于当日
  High 的跨日场景、ST 订单号升序、Ticker、到期日、合约代码和幂等。
- Short-Term Results New-High Suppression：相同订单只有 lifetime high 严格超过此前已发布最佳
  值才进入下一轮 Review；相同或更低值被抑制，新订单首次仍正常显示。

Simple Tracked Swing:

- Simple Entry 无 Mentor/Position/ADD/SL/Runner/chart，Category 切换和显式到期日校验。
- 与 Short-Term 共享同一个 active fixed-TP policy source，同时验证 Swing 没有 protection 或
  Momentum；policy version、TP event、High/Low Watermark 和跨日状态幂等。
- `close SW-XXXX`、完整合约与 optional `@price` parser；零/多匹配阻塞和 Dropdown 路径。
- Entry publication → tracker → verified high → Manager Close → tracker stop → lifetime-high final
  result 的端到端集成；Close 卡区分 lifetime High 与平仓收益，Results 不被 Close Reference 替代。
- Active View 精简字段且 Swing 不暴露仓位、forced refresh fallback、daily snapshot、expiry、
  restart reconciliation 和 Legacy Swing isolation。
- Simple / Legacy Swing 合并成单张 Active View、统一字段与 SW 编号排序；Legacy 使用只读实时
  quote / snapshot fallback，但不会创建 `swing_tracking` 记录。

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
- Free Trial 严格 3 XNYS Trading Days：周末/美国市场休市日不计入、批准时通过
  TradingCalendarService 固化首末交易日与 expiry、终身一次、默认无 DM、无 Stripe / Card /
  Auto Renewal。
- Day Pass 保持 1 XNYS Trading Day；Trial 有效时阻止 Day Pass checkout，但允许 Monthly。
- Welcome 与完整申请/审核流程为中文，唯一 onboarding CTA 为 `申请加入 AXIS`；来源、兴趣、
  推荐人、两份协议、提交结果与 Manager 审核按钮中文化，内部状态码不变；旧 Apply /
  Start Trial / Membership CTA 均不存在。
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
- Mentor select、关键点位逐项下拉编辑/新增/删除、edit、rewrite、archive-only、
  archive+publish、delete 和 publication retry。
- Raw / Mentor / Stock Analyst / Final Fused / Public Snapshot traceability。
- Mentor-first / fill-missing、provenance、conflict、scenario gate 和 safe fallback。
- Pilot-style 确定性 Prediction Chart、Manager 点位重建、无未来 K 线、source image 不转发和
  renderer failure isolation；使用已保存的 RDDT 82 根真实日 K 完成 1600×900 视觉复核。
- Analysis 与独立 GEX surface 保持隔离。

GEX Explorer Phase 1:

- `/gex` 唯一入口、Ticker normalization、SPX 独立映射与 plain-ticker no-trigger。
- Owner/card-testing authorization、wrong-channel / Manager / Member / Newcomer denial。
- 10 valid expirations、0DTE / Near-Term、empty/incomplete/partial skip、minimum coverage fail-close。
- Option Volume/Gamma、IV fallback、Net/Positive/Negative GEX、五级 Regime、Zero Gamma、
  GEX Walls、Clusters、
  deterministic Bias/Triggers 与 no-LLM level boundary。
- Deterministic 1800x1125 Chinese composite chart；candle-first adaptive axis；full-width off-scale
  pressure/support/Gamma rails；real 5-minute K-line；full-width purple negative-GEX acceleration
  bands with actual levels；
  strike x expiration heatmap。
- Massive GEX or Massive minute failure is fail-closed；Moomoo shadow failure is non-blocking；
  no synthetic candle fallback；PNG dimension and shadow metadata tests PASS。
- ticker+policy+provider cache、single-flight、user cooldown、guild limit 与全部 GEX Audit event。
- GEX 查询后 Trade count 保持 0 的 isolation test；不创建 Signal/Result/Analysis/Tracking/Moomoo。
- 真实 cold request `1627ms`；同进程 cache hit `2ms`。

Operations / Security:

- Backup 命令不在 argv 泄露密码、Docker context 排除 .env。
- System Alert dedup、occurrence count、RECOVERY 和再次告警。
- Config-reference 与 config 一致、Secret-safe error/log boundaries。

## Live verifier evidence

Database:

- revision=20260904_0031
- source_messages=88
- trade_drafts=87
- trades=67
- trade_events=66
- trade_publications=66
- analysis_drafts=1
- mentor_analyses=1
- analysis_publications=1
- market_quote_snapshots=13
- daily_results_reviews=5
- daily_results_items=103
- membership_entitlements=8
- membership_trials=3
- newcomer_profiles=8
- access_applications=3
- newcomer_risk_flags=3
- membership_prices=6
- payment_events=0
- system_alerts=4
- swing_tracking=8 / swing_tracking_events=12 / swing_daily_snapshots=8
- personal execution settings / positions / orders / fills / events / snapshots / summaries 均为 0；
  DRY_RUN 没有创建假成交或假持仓。

Feature flags:

- FEATURE_ANALYSIS_ENABLED=true
- FEATURE_AXIS_STOCK_ANALYST_ENABLED=true
- FEATURE_DAILY_SUMMARY_ENABLED=true
- FEATURE_SHORT_TERM_TRACKING_ENABLED=true
- FEATURE_LAB_ENABLED=false
- FEATURE_MODEL_AB_ENABLED=false
- FEATURE_MOOMOO_ENABLED=false
- FEATURE_PERSONAL_EXECUTION_ENABLED=false
- RESULTS_REVIEW_ENABLED=true
- GEX_EXPLORER_ENABLED=true / GEX_EXPLORER_MODE=TEST

Discord:

- discord_runtime=PASS
- 本轮 GEX Phase 1 没有创建或修改 Discord 资源；Bootstrap dry-run=REUSE 32 / UPDATE 0 /
  CREATE 0 / BLOCK 0，服务器修改 0。
- `⬛・GENERAL` position 0、`👋・welcome` position 0；runtime verifier 确认它是第一个公共入口，
  会员 Category 对 `@everyone` 隐藏。
- Welcome 持久卡片为纯中文审批制文案并显示 3 个美国股票市场交易日完整会员体验、无需信用卡、
  不会自动续费、中文风险与安全提示，唯一按钮为 `申请加入 AXIS`。
- Membership 卡片不再提供直接 Free Trial；Day Pass / Monthly checkout 在服务层要求 permanent
  Approval + completed Role sync，Newcomer 无法通过旧 URL / component 绕过。
- Member Wins 最新权限：`@everyone` view/send/attach，内容不计入官方 AXIS Results。
- personas=public, newcomer, member, manager, owner, bot
- GENERAL guides=idempotent
- owner test commands=13（包含 `/gex`）；GEX smoke card 已在 card-testing 发送成功。

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
- 当前 Test / Live 新购 Monthly 已切换为 V2 USD 149.99；以上 USD 99.99 为 V1 历史验收证据，
  既有订阅不自动迁移。
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

Swing V2 migration evidence（2026-09-03）：

- before revision=`20260902_0028`
- after revision=`20260903_0029`
- pre-migration Swing=5，Active Legacy Swing=4
- post-migration classification=`LEGACY_SWING ACTIVE:4 / CLOSED:1`
- `swing_tracking`、`swing_tracking_events`、`swing_daily_snapshots` 已创建；Production Simple Swing=0
- offline SQL dry-run 与 post-migration read-only verification PASS；无删除、重编号或历史重写

## Explicit failed / pending Live gate

Short-Term verifier evidence after the verified-contract deployment:

- short_term_tracking=23
- short_term_tracking_events=116
- short_term_daily_snapshots=31
- active_tracking=17
- verified-contract mismatches=0
- active rows without any quote=0
- active rows with a current data-quality error=1 (`ST-0023 · MASSIVE_QUOTE_STALE`)
- live SL_ALERT events=0；Short-Term SL 已移除，未发布的 legacy SL event 会自动抑制

`ST-0022 · SPX 09/01 7625P` 已从错误重建的 `O:SPX...` 修复为 Review 验证的
`O:SPXW260901P07625000`，部署后实时 MID 报价、TP 和 Daily Snapshot 已更新。漏追踪窗口使用
Massive 历史 MID 按分钟核验：最高 `$5.55` 已由实时轮询重新记录，最低 `$2.175 / -19.44%`
已回补至 Low Watermark 与当日 Snapshot。Short-Term 不再生成 -50% / breakeven SL Card；
Discord Live E2E 只保留真实固定 TP 与 Momentum TP；到期只验收内部 Tracking / Results。

## Warnings

- discord.py 间接依赖 audioop，Python 3.13 将移除该模块。
- discord.ui modal 的 label API 有 deprecation warning；当前不影响 311 项测试结果。

## Owner Personal Moomoo DRY_RUN evidence（2026-09-04）

- Policy / budget / opening guard / risk ladder / publication idempotency / adapter safety automated tests: PASS。
- Safety gate: PASS；mode=`DRY_RUN`，broker writes=`DISABLED`。
- Discord runtime: PASS；`💹・moomoo-trading` 仅 Owner 与 Bot 可见。
- Database revision=`20260904_0031`；新增执行表全部为空。
- OpenD connectivity: BLOCKED — `127.0.0.1:11111` 未监听；未伪造账户、订单、成交或持仓验证。
- 因外部 E2E 未完成，feature、DRY_RUN accepted gate、REAL environment 与 LIVE write gate 均未启用。
