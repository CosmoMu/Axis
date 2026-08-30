# AXIS Analysis Pipeline Runbook

Analysis 与 Signal 是两个独立 Domain。`source_messages.source_kind` 只负责共享不可变 Raw
入口；两个 worker 互相忽略对方的 Source，Trade / Analysis 的 Draft、归档和发布表不复用。

## 数据流

```text
analysis-input
  -> immutable SourceMessage / checksum attachments
  -> ANALYSIS_PARSE
  -> AnalysisDraft
  -> Mentor select / edit / rewrite revision
  -> archive-only OR immutable MentorAnalysis + Public Snapshot
  -> member-lounge (no thread)
```

新 Source 永远创建新的 `analysis_id`。即使 Mentor 和 symbol 相同，也不会更新旧 Analysis。

`analysis-input` 支持直接文字/图片，也支持 Discord Forward。Forward 的 message snapshot
正文与附件会合并为本次不可变 Raw Source；转发人仍必须是 Owner 或 Manager。Discord 图片
发生 `.webp` 文件名与 PNG MIME 不一致时，以真实图片签名归一化，非真实图片仍拒绝。

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
- Public Card 由 whitelist DTO 生成，不含 Mentor、Source、AI/LLM、confidence。

## 发布恢复

Discord 发送失败时，Mentor Analysis 和 Public Snapshot 已安全归档，Draft 转为
`PUBLISH_FAILED`。管理员使用 persistent `重试发布`；marker 扫描和唯一约束避免重复卡片。

## Feature Gate

Owner 已对 `analysis-input` 的 OpenAI 数据出口作出独立明确授权，当前本机为：

```text
FEATURE_ANALYSIS_ENABLED=true
```

该授权不影响 AXIS LAB；LAB 三个开关继续为 false。不要为了健康检查制造虚假市场观点；
用第一条真实 Manager 输入观察 intake、parse、review 和 trace。
