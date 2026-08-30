# AXIS Test Status

**Date:** 2026-08-30

## Summary

- Full pytest suite: PASS — 169 passed、0 failed、0 skipped
- Ruff: PASS
- Python compileall: PASS
- Static type checker: NOT CONFIGURED
- Core Gate A automated checks: PASS
- Analysis Gate B automated checks: PASS
- Database verifier: PASS
- Discord runtime verifier: PASS
- Analysis Fusion verifier: PASS
- Stripe Test setup verifier: PASS
- Stripe Test external E2E verifier: PASS
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

没有在 pyproject.toml 或 CI 配置中发现 mypy / pyright，因此没有把未运行的 type check 标记为 PASS。

## Automated coverage

Core / Discord:

- Blueprint 精确结构、权限矩阵、unknown-resource safety、受控 rename 和 Bootstrap 幂等。
- Persistent View、Manager 控制面板、Message ID marker 和 Bot restart recovery。
- Public / Member / Manager / Owner / Bot persona。
- GENERAL Guide、Owner test commands 和 Public Identity Policy。

Signal / Trade:

- Text、image、multi-image、Discord forward、真实文件签名和拒绝输入审计。
- Structured Output、router、invocation trace、missing fields 和 failure draft。
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

Membership / Stripe:

- Free Trial、Day Pass、Monthly、Gift、Manual Extension、多 Entitlement 与 Role reconciliation。
- XNYS 交易日、风险确认、终身一次 Trial 和 scheduled expiry。
- Checkout / Portal、webhook signature、dedup、Price snapshot / Grandfathering。
- renewal、failure、cancel-at-period-end、PAST_DUE 与 provider event ordering。

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

- revision=20260830_0020
- source_messages=19
- trade_drafts=10
- trades=3
- trade_events=3
- trade_publications=3
- analysis_drafts=8
- mentor_analyses=4
- analysis_publications=4
- membership_entitlements=3
- payment_events=3
- system_alerts=3

Feature flags:

- FEATURE_ANALYSIS_ENABLED=true
- FEATURE_AXIS_STOCK_ANALYST_ENABLED=true
- FEATURE_DAILY_SUMMARY_ENABLED=true
- FEATURE_SHORT_TERM_TRACKING_ENABLED=true
- FEATURE_LAB_ENABLED=false
- FEATURE_MODEL_AB_ENABLED=false
- FEATURE_MOOMOO_ENABLED=false

Discord:

- discord_runtime=PASS
- personas=public, member, manager, owner, bot
- GENERAL guides=idempotent
- owner test commands=12

Analysis Fusion:

- draft_layers=8/8
- archive_layers=4/4
- 当前历史归档 indicators/scenarios/path_points 均为 0；结构与回归测试 PASS，但仍需新的真实
  Mentor Fusion / Chart UX 验收。

Stripe Test:

- setup=PASS
- Product=AXIS Membership
- Day Pass=USD 9.99 one-time
- Monthly=USD 99.99 monthly auto-renew
- local webhook=LISTENING
- external E2E=PASS
- Day Pass entitlement=ACTIVE
- Monthly entitlement=ACTIVE，auto-renew=ENABLED，invoice.paid=PROCESSED
- Discord Member Role=PRESENT

## Explicit failed / pending Live gate

Short-Term verifier evidence:

- short_term_tracking=1
- short_term_tracking_events=1（Entry）
- short_term_daily_snapshots=0
- daily_results_publications=0
- market_quote_snapshots=0

ST-0001 Published Active Entry 已完成幂等 tracking 补注册。真实 Massive quote、TP / Protection
trigger、Discord event、Daily Results 和 restart recovery 必须完成后，Short-Term Live E2E
才能标记 PASS。

## Warnings

- discord.py 间接依赖 audioop，Python 3.13 将移除该模块。
- discord.ui modal 的 label API 有 deprecation warning；当前不影响 169 项测试结果。
