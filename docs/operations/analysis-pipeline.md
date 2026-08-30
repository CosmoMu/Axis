# AXIS Analysis Pipeline Runbook

Analysis 与 Signal 是两个独立 Domain。`source_messages.source_kind` 只负责共享不可变 Raw
入口；两个 worker 互相忽略对方的 Source，Trade / Analysis 的 Draft、归档和发布表不复用。

## 数据流

```text
analysis-input
  -> immutable SourceMessage / checksum attachments
  -> ANALYSIS_PARSE
  -> manager thesis / why-now + current AXIS Stock Analyst context
  -> ordered input route/levels rendered as text
  -> AnalysisDraft
  -> Mentor select / edit / rewrite revision
  -> archive-only OR immutable MentorAnalysis + Public Snapshot
  -> member-lounge (no thread)
```

新 Source 永远创建新的 `analysis_id`。即使 Mentor 和 symbol 相同，也不会更新旧 Analysis。

`analysis-input` 支持直接文字/图片，也支持 Discord Forward。Forward 的 message snapshot
正文与附件会合并为本次不可变 Raw Source；转发人仍必须是 Owner 或 Manager。Discord 图片
发生 `.webp` 文件名与 PNG MIME 不一致时，以真实图片签名归一化，非真实图片仍拒绝。

Ticker Analysis 只在恰好识别出一个 symbol 时调用 AXIS Stock Analyst。引擎通过本机
Moomoo OpenD 读取日 K，不 import 或启动 Cosmos。Manager 的原始观点、方向、周期和
`why_now` 优先保留；AXIS 的趋势、板块相对强度、OHLCV 资金流代理、结构价位与情景权重
作为补充依据。Stock Analyst 不可用时保留用户观点并加入安全
warning，只使用 LLM 对原始 input 的忠实整理，不让整条 Analysis 失败。

当前审核与发布只使用文字卡，不生成、上传或转发 Analysis 图片。Source 原图只作为 LLM
解析证据；图中明确画出的未来路线会按顺序转换为“预测路径（文字）”，数字只复制明确可读
的输入点位。Stock Analyst 成功时把当前主情景写成文字结构观察；失败时不补造行情、路径或
点位。未来接入 Massive API 时再通过独立 provider/renderer 扩展图片，不改变 Draft、审核、
归档和发布流程。

归档把输入原因写入 `why_now_json` / `WHY_NOW` points，把输入与引擎关键位分别标记为
`INPUT` / `AXIS_STOCK_ANALYST`。引擎观察保存为 `ENGINE_OBSERVATION`，方便未来 Model A
直接区分老师观点与确定性行情特征。

如果外部 API 曾失败并生成 `PARSE_FAILED` 草稿，修复原因后可对原 Discord Message ID
运行 `scripts/retry_failed_analysis.py`。它保留原 Source、失败 invocation、审计记录和 Draft ID，
新增一次带追踪的 revision，并将成功结果恢复为 `PENDING_REVIEW`。

## 审核规则

- 必须选择 Active Mentor 才能归档。
- Type 只允许 MARKET / TICKER / SECTOR / MACRO。
- Stance 只允许 BULLISH / BEARISH / NEUTRAL / WATCH。
- Horizon 只允许 INTRADAY / SHORT_TERM / SWING / LONG_TERM / UNSPECIFIED。
- 没有明确价格时输入 `path_points.price` / `key_levels.price=null`；不能由 LLM 根据常识或
  行情补值。形状节点的最终显示价格由确定性的 AXIS 渲染器映射。
- Rewrite 创建新 revision 和新 LLM invocation，不覆盖 Raw Source。
- Archive-only 不创建 Public Snapshot 或 Publication。
- Public Card 由 whitelist DTO 生成，不含 Mentor、Source 元数据、AI/LLM、confidence；
  当前只发布文字卡。

Manager-facing 输入编号独立递增：Signal 使用 `S-00001`，Analysis 使用 `A-00001`。UUID
只作为数据库主键和 Discord component 内部标识，不再出现在卡片页脚。

## 发布恢复

Discord 发送失败时，Mentor Analysis 和 Public Snapshot 已安全归档，Draft 转为
`PUBLISH_FAILED`。管理员使用 persistent `重试发布`；marker 扫描和唯一约束避免重复卡片。

## Feature Gate

Owner 已对 `analysis-input` 的 OpenAI 数据出口作出独立明确授权，当前本机为：

```text
FEATURE_ANALYSIS_ENABLED=true
FEATURE_AXIS_STOCK_ANALYST_ENABLED=true
```

该授权不影响 AXIS LAB；LAB 三个开关继续为 false。不要为了健康检查制造虚假市场观点；
用第一条真实 Manager 输入观察 intake、parse、review 和 trace。
