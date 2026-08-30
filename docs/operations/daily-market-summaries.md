# AXIS Daily Market Summaries

## Current Scope

AXIS BOT 在每个美股交易日 `16:15 ET` 只向以下频道发送 Daily Summary：

- `〽️・swing`
- `♾️・leaps`

每条消息包含该类别的今日关闭与当前持仓。`⚡・short-term` 不发送 Daily Summary；已停止
追踪的 Short-Term 只进入 `AXIS DAILY RESULTS`。启用 Moomoo 时，Active 收盘参考来自本机
OpenD 的只读期权 snapshot；不是账户持仓或交易数据。Moomoo 未启用时，不猜测 Active 行情。

## Required Runtime

```text
FEATURE_MOOMOO_ENABLED=false
FEATURE_DAILY_SUMMARY_ENABLED=true
MOOMOO_OPEND_HOST=127.0.0.1
MOOMOO_OPEND_PORT=11111
DAILY_SUMMARY_TIME_ET=16:15
```

如需 Active 收盘报价，必须把 `FEATURE_MOOMOO_ENABLED` 改为 `true` 并重新执行完整安全验收。
OpenD 与 Python SDK 当前锁定 `10.10.7008`；启用时 OpenD 必须行情登录并监听本机端口。

## Safety Rules

- 只调用 global state、option chain 和 market snapshot。
- 期权代码由到期日、行权价与 Call/Put 精确解析并缓存。
- 不调用账户、资金、持仓、订单、unlock 或交易接口。
- 不显示 Market、Bid 或 Ask；会员只看到当前/收盘参考价与行情时间。
- SPY snapshot 日期不等于当天时视为周末/假日，不发送。
- OpenD 全局失败时不发布不完整总结，Bot 每分钟重试。
- 单个合约无法解析时只将该订单标记为行情暂不可用，不猜测价格。

## Idempotency

数据库唯一键为 `guild_id + category + session_date`，每条消息还有确定性的
`EOD-SW/LP-YYYYMMDD` marker。Bot 在发送前扫描频道 marker；即使 Discord 发送成功后
数据库 finalize 前崩溃，重启也只会认领原消息，不会重复发布。

## Health Check

```bash
.venv/bin/python scripts/verify_database.py
launchctl print gui/$(id -u)/com.axis.bot
lsof -nP -iTCP:11111 -sTCP:LISTEN
```

正常数据库 revision 为 `20260830_0019`。`market_quote_snapshots` 与
`daily_summary_publications` 在第一个真实交易日、且存在相关 Trade 后才会出现行数。
