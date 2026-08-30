# AXIS Analysis Pipeline Runbook

Analysis 与 Signal 是两个独立 Domain。`source_messages.source_kind` 只负责共享不可变 Raw
入口；两个 worker 互相忽略对方的 Source，Trade / Analysis 的 Draft、归档和发布表不复用。

## 数据流

```text
analysis-input
  -> immutable SourceMessage / checksum attachments
  -> ANALYSIS_PARSE
  -> manager thesis + current Cosmos Market Stock Analyst context
  -> source forecast image OR fresh Cosmos model-path chart
  -> AnalysisDraft
  -> Mentor select / edit / rewrite revision
  -> archive-only OR immutable MentorAnalysis + Public Snapshot
  -> member-lounge (no thread)
```

新 Source 永远创建新的 `analysis_id`。即使 Mentor 和 symbol 相同，也不会更新旧 Analysis。

`analysis-input` 支持直接文字/图片，也支持 Discord Forward。Forward 的 message snapshot
正文与附件会合并为本次不可变 Raw Source；转发人仍必须是 Owner 或 Manager。Discord 图片
发生 `.webp` 文件名与 PNG MIME 不一致时，以真实图片签名归一化，非真实图片仍拒绝。

Ticker Analysis 只在恰好识别出一个 symbol 时调用本机 Cosmos Market Stock Analyst。
Manager 的原始观点、方向和周期优先保留；Cosmos 的日 K 趋势、板块相对强度、OHLCV
资金流代理、结构价位与情景权重作为补充依据。Cosmos 不可用时保留用户观点并加入安全
warning，不让整条 Analysis 失败。

图片选择固定为：如果本次 Source 的某张输入图明确画了延伸到未来区域的预测路径，审核
与发布都使用这张原图；只有 K 线、指标、支撑压力线或文字目标不算预测路径。没有明确
预测路径时，才使用本次实时生成的 Cosmos Stock Analyst 图，并画出 CosmosPilot 风格的
最高权重情景线。系统不扫描 Cosmos 历史图片目录，也不按 ticker 复用旧图。

如果外部 API 曾失败并生成 `PARSE_FAILED` 草稿，修复原因后可对原 Discord Message ID
运行 `scripts/retry_failed_analysis.py`。它保留原 Source、失败 invocation、审计记录和 Draft ID，
新增一次带追踪的 revision，并将成功结果恢复为 `PENDING_REVIEW`。

## 审核规则

- 必须选择 Active Mentor 才能归档。
- Type 只允许 MARKET / TICKER / SECTOR / MACRO。
- Stance 只允许 BULLISH / BEARISH / NEUTRAL / WATCH。
- Horizon 只允许 INTRADAY / SHORT_TERM / SWING / LONG_TERM / UNSPECIFIED。
- 没有明确价格时 `key_levels.price=null`；不能根据常识或行情补值。
- Rewrite 创建新 revision 和新 LLM invocation，不覆盖 Raw Source。
- Archive-only 不创建 Public Snapshot 或 Publication。
- Public Card 由 whitelist DTO 生成，不含 Mentor、Source 元数据、AI/LLM、confidence；
  Manager 选择“归档并发布”时，同一份审核图作为已批准 Analysis visual 随卡片发布。

## 发布恢复

Discord 发送失败时，Mentor Analysis 和 Public Snapshot 已安全归档，Draft 转为
`PUBLISH_FAILED`。管理员使用 persistent `重试发布`；marker 扫描和唯一约束避免重复卡片。

## Feature Gate

Owner 已对 `analysis-input` 的 OpenAI 数据出口作出独立明确授权，当前本机为：

```text
FEATURE_ANALYSIS_ENABLED=true
FEATURE_COSMOS_STOCK_ANALYST_ENABLED=true
```

该授权不影响 AXIS LAB；LAB 三个开关继续为 false。不要为了健康检查制造虚假市场观点；
用第一条真实 Manager 输入观察 intake、parse、review 和 trace。
