# AXIS Daily Market Summaries

## Current Scope

AXIS BOT 在每个美股交易日 `16:15 ET` 只向以下频道发送 Daily Summary：

- `〽️・swing`
- `♾️・leaps`

每条消息包含该类别的今日关闭与当前持仓。`⚡・short-term` 不发送 Daily Summary；已停止
追踪的 Short-Term 只进入 `AXIS DAILY RESULTS`。Daily Results 先进入
`📋・results-review`，不再由 Daily Summary job 直接发布；完整流程见
`docs/operations/daily-results-review.md`。Active 收益只使用 Massive 对应期权合约在该交易日的
正式 Daily OHLC `close`，不使用盘后实时价、Bid、Ask、Mid 或最后 snapshot。

## Required Runtime

```text
FEATURE_DAILY_SUMMARY_ENABLED=true
MASSIVE_API_KEY=<secret in .env only>
DAILY_SUMMARY_TIME_ET=16:15
```

`MASSIVE_API_KEY` 只从 `.env` / Secret Manager 读取，不写入源码、日志或 Git。

## Safety Rules

- 只调用 Massive Options Daily Aggregate OHLC 只读端点。
- 期权代码由 Ticker、到期日、行权价与 Call/Put 确定性生成。
- 不调用账户、资金、持仓、订单、unlock 或交易接口。
- 不显示 Market、Bid 或 Ask；会员只看到正式收盘价及其相对最近持仓成本的收益。
- Trading Calendar 决定交易日；绝不拿其他日期的 bar 代替当日收盘价。
- Massive 鉴权或限流失败时不发布不完整总结，Bot 每分钟重试。
- 单个合约当日没有合格成交 bar 时只标记为收盘行情暂不可用，不猜测价格。

## Idempotency

数据库唯一键为 `guild_id + category + session_date`，每条消息还有确定性的
`EOD-SW/LP-YYYYMMDD` marker。Bot 在发送前扫描频道 marker；即使 Discord 发送成功后
数据库 finalize 前崩溃，重启也只会认领原消息，不会重复发布。

## Health Check

```bash
.venv/bin/python scripts/verify_database.py
launchctl print gui/$(id -u)/com.axis.bot
```

正常数据库 revision 为 `20260830_0022`。`market_quote_snapshots` 与
`daily_summary_publications` 在第一个真实交易日、且存在相关 Trade 后才会出现行数。
