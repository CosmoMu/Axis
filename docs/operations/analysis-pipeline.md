# AXIS Analysis Pipeline Runbook

Analysis 与 Signal 是两个独立 Domain。`source_messages.source_kind` 只负责共享不可变 Raw
入口；两个 worker 互相忽略对方的 Source，Trade / Analysis 的 Draft、归档和发布表不复用。

## 数据流

```text
analysis-input
  -> immutable SourceMessage / checksum attachments
  -> ANALYSIS_PARSE
  -> Normalized Mentor View
  -> current AXIS Stock Analyst snapshot
  -> Mentor-first / AXIS-fill-missing fusion
  -> AnalysisDraft
  -> Final Fused Preview / source-aware Manager review
  -> archive-only OR immutable Final Analysis + Public Snapshot
  -> member-lounge (no thread)
```

新 Source 永远创建新的 `analysis_id`。即使 Mentor 和 symbol 相同，也不会更新旧 Analysis。

`analysis-input` 支持直接文字/图片，也支持 Discord Forward。Forward 的 message snapshot
正文与附件会合并为本次不可变 Raw Source；转发人仍必须是 Owner 或 Manager。Discord 图片
发生 `.webp` 文件名与 PNG MIME 不一致时，以真实图片签名归一化，非真实图片仍拒绝。

Ticker Analysis 只在恰好识别出一个 symbol 时调用 AXIS Stock Analyst。引擎通过本机
Moomoo OpenD 读取日 K，不 import 或启动 Cosmos。Mentor 明确表达的观点、点位、目标、失效和
指标是 Source of Truth；AXIS 只补同角色缺失的结构、资金流代理、板块相对强度、指标和情景。
Stock Analyst 不可用时保留 Mentor View 并加入安全
warning，只使用 LLM 对原始 input 的忠实整理，不让整条 Analysis 失败。

Source 原图只作为 LLM 解析证据，公开文字不得依赖“图中/箭头/颜色”等引用。后台保留 2–3
个模型情景，公开只使用 Top Scenario；Top weight 小于 50%，或 Top1 与 Top2 差小于 10%，
不显示强方向路径。通过门槛后，确定性 PIL renderer 使用与卡片相同的 `prediction_path`
生成单一结构路径 PNG，不画未来 K 线。Renderer 失败不阻止文字归档，可在 Review 重试。

归档同时保存 Raw Source、Normalized Mentor View、Stock Analyst Snapshot、Final Fused
Analysis 与 Public Card Snapshot。点位、指标分别标记 `MENTOR_INPUT` / `STOCK_ANALYST`；
同角色冲突写入 `conflicts_json`，Manager Review 可见，Public Card 永不显示来源。

如果外部 API 曾失败并生成 `PARSE_FAILED` 草稿，修复原因后可对原 Discord Message ID
运行 `scripts/retry_failed_analysis.py`。它保留原 Source、失败 invocation、审计记录和 Draft ID，
新增一次带追踪的 revision，并将成功结果恢复为 `PENDING_REVIEW`。

## 审核规则

- 必须选择 Active Mentor 才能归档。
- Type 只允许 MARKET / TICKER / SECTOR / MACRO。
- Stance 只允许 BULLISH / BEARISH / NEUTRAL / WATCH。
- Horizon 仍可在内部保存，但 Public Card 不显示。
- 没有明确价格时输入 `path_points.price` / `key_levels.price=null`；不能由 LLM 根据常识或
  行情补值。形状节点的最终显示价格由确定性的 AXIS 渲染器映射。
- Rewrite 创建新 revision 和新 LLM invocation，不覆盖 Raw Source。
- Archive-only 不创建 Public Snapshot 或 Publication。
- Public Card 由 whitelist DTO 生成，不含 Mentor、来源标签、AI/LLM、confidence、观察周期；
  无有效数据的 Section 整段省略。

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
