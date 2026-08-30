# AXIS — Mentor Analysis Pipeline Specification

**版本：** MVP v2  
**开发优先级：** Core + Signal 全部测试通过后  
**AXIS LAB：** 仍然禁止开发

---

# 1. 目标

Analysis Pipeline 用于保存 Mentor / Manager 对市场、独立标的、板块、宏观事件的观点。

它记录的不是“做了什么”，而是：

> 某个 Mentor 在某个时间点是怎么理解市场的。

Manager 可以输入文字 / 图片，LLM 读取、理解并转换成标准化 Analysis Record 与 AXIS 风格中文卡片。内部审核后，Manager 选择 Mentor，可编辑、重新整理，然后选择“仅归档”或“归档并发布”。

发布位置：

```text
🛋️・member-lounge
```

不创建 Thread。

---

# 2. Manager Channels

```text
⚙️・MANAGER
├─ 💭・analysis-input
└─ 📝・analysis-review
```

`analysis-input` 只接收原始内容，不直接发布。

`analysis-review` 用于：

```text
选择 Mentor
编辑
重新整理
仅归档
归档并发布
删除草稿
```

---

# 3. Analysis 与 Signal 必须独立

```text
Signal   = Mentor 做了什么
Analysis = Mentor 当时为什么这么想
```

不能共用一个 Draft Object 或主表。

---

# 4. 不更新已有观点

这是强制设计规则。

**没有 `Update Existing Analysis` 功能。**

例如同一 Mentor 上午看多 NVDA，下午变成中性：

```text
AN-0018  10:12 ET  NVDA  偏多
AN-0024  14:36 ET  NVDA  中性
```

两条都永久保留。

原因：未来模型需要看到“观点发生时的状态”，而不是看到一个被后来信息覆盖的最终版本。

MVP 不需要：

```text
analysis_version
parent_analysis_id
update_existing_analysis
```

每个新观点直接创建新的 `analysis_id`。

---

# 5. 三层数据

每一条 Analysis 保存：

## Raw Source

```text
raw_text
attachments
submitted_by
source_timestamp
```

不可被覆盖。

## Normalized Analysis

机器可理解结构：

```text
analysis_type
symbols
sector
stance
time_horizon
title
summary
core_thesis
supporting_points
key_levels
invalidation
catalysts
risks
market_conditions
related_symbols
```

## Public Card Snapshot

保存当时会员实际看到的最终卡片内容，供审计 / 复盘。

---

# 6. Analysis 类型

```text
MARKET
TICKER
SECTOR
MACRO
```

会员卡片显示中文：

```text
市场观察
标的观察
板块观察
宏观观察
```

---

# 7. Stance / Horizon

内部：

```text
BULLISH
BEARISH
NEUTRAL
WATCH
```

会员：

```text
偏多
偏空
中性
观察
```

周期：

```text
INTRADAY
SHORT_TERM
SWING
LONG_TERM
UNSPECIFIED
```

原文没有明示就使用 `UNSPECIFIED`，LLM 不得猜。

---

# 8. LLM 的职责

LLM 应：

1. 理解原始内容，而不是只做摘要。
2. 提取主要对象 / Symbol / Sector。
3. 提取方向与时间周期（仅在原文支持时）。
4. 提取核心 Thesis。
5. 提取关键位置、失效条件、风险、Catalyst、Market Condition。
6. 生成统一、克制、极简的 AXIS 中文表达。
7. 返回严格 Structured Output。

LLM **不是策略生成器**。

不得自行补充原始内容中不存在的：

```text
Entry
TP
SL
价格关键位
Catalyst
方向
时间周期
```

缺失字段返回 `null`。

---

# 9. Analysis 模型路由

这里不能依赖全局单一 `LLM_MODEL`。

Analysis 是更需要语义理解和高质量重组的 workload，因此必须独立配置。

当前 MVP：

```text
ANALYSIS_PARSE   -> gpt-5.6-terra
ANALYSIS_REWRITE -> gpt-5.6-terra
```

先全部使用 Terra，减少 MVP 变量并便于统一测试。

未来可以无代码改动切换：

```text
ANALYSIS_PARSE   -> gpt-5.6-sol
ANALYSIS_REWRITE -> gpt-5.6-sol
```

Signal 仍可继续保持 Terra。

因此不要使用：

```text
LLM_MODEL=one_model_for_everything
```

改用 workload router：

```text
SIGNAL_PARSE
SIGNAL_REPAIR
ANALYSIS_PARSE
ANALYSIS_REWRITE
```

每条 Analysis 保存实际使用的：

```text
llm_model
llm_workload
prompt_version
schema_version
```

这样未来能比较：

- Terra 与 Sol 对观点整理质量的差异；
- 不同 Prompt Version 的效果；
- 哪版模型产生过哪条归档数据。

---

# 10. Review Flow

```text
Manager input
-> save Raw Source
-> OpenAI API / ANALYSIS_PARSE
-> Structured Output validation
-> Analysis Draft
-> 📝・analysis-review
-> Manager chooses Mentor
-> Manager edits / rewrites if needed
-> Archive Only OR Archive + Publish
```

Draft 示例：

```text
待审核观点 · AN-D1042

类型
标的观点

标的
NVDA

方向
偏多

观察周期
短线

Mentor
尚未选择

核心观点
趋势结构仍然偏强，但当前位置已经出现一定延伸，暂不适合追高。

关注位置
$208

失效条件
跌破 $206

市场前提
大盘整体不能明显转弱

相关标的
AMD
```

按钮：

```text
[ 选择 Mentor ]
[ 编辑 ]
[ 重新整理 ]
[ 仅归档 ]
[ 归档并发布 ]
[ 删除草稿 ]
```

不存在“更新已有观点”。

---

# 11. 重新整理

`重新整理` 生成新的 Draft Revision，不影响 Raw Source。

可选：

```text
更简洁
保留更多细节
更偏交易视角
更偏市场分析
重新识别原文
```

每次 Rewrite 记录实际模型与 prompt version。

---

# 12. Archive Only

适用于：

- 很早期观察
- 非正式想法
- 对 Model A 有训练价值但不需要发给会员

必须保存所有三层数据中的 Raw + Normalized；Public Card Snapshot 可为空。

---

# 13. Archive + Publish

必须顺序：

```text
1. 保存 Approved Analysis
2. 保存 Structured Data
3. 建立 Public Card Snapshot
4. 移除所有内部字段
5. 发布到 🛋️・member-lounge
6. 保存 Discord Message ID
```

Discord 发布失败时，已归档 Analysis 不回滚：

```text
publication_status = FAILED
```

Manager 可重试发布。

---

# 14. Public Analysis Card

会员卡片：

- 中文。
- 极简。
- 不写 Mentor。
- 不写 Source。
- 不写 AI / LLM。
- 不写 Parser Confidence。
- 不创建 Thread。
- null 字段整段不显示。

例：

```text
标的观察 · NVDA

当前观点
偏多 · 暂不追高

核心逻辑
趋势结构仍然偏强，但当前位置已经出现一定延伸。
更关注回踩后的承接，而不是直接追逐当前位置。

关注位置
$208 附近

失效条件
跌破 $206 后，当前短线观点需要重新评估。

相关观察
AMD 同期表现保持强势，半导体板块整体相对强度仍值得关注。

观察周期
短线

时间
08/29 · 14:41 ET
```

这里的 $208 / $206 仅在 Raw Source 明确存在时允许显示。

---

# 15. Database

新增独立 Analysis Domain：

```text
mentor_analyses
analysis_drafts
analysis_symbols
analysis_key_levels
analysis_points
analysis_publications
```

继续复用：

```text
source_messages
source_attachments
llm_invocations
audit_logs
```

`mentor_analyses` 至少：

```text
analysis_id
mentor_id
analysis_type
stance
time_horizon
title
summary
core_thesis
invalidation
sector
observed_at
market_snapshot_id nullable
created_at
approved_at
publication_status
llm_model
llm_workload
prompt_version
schema_version
```

未来可以通过：

```text
mentor_id + symbol + observed_at
```

重建完整观点时间线，而不是修改旧数据。

---

# 16. Future Market Snapshot Reservation

MVP 不要求接 Moomoo，但数据库预留：

```text
market_snapshot_id nullable
```

以后观点发生时保存“当时”的市场状态，不使用未来数据污染过去：

```text
Underlying Price
SPY / QQQ State
Sector State
Volume
Relative Strength
IV
Option Data
GEX
Technical Features
```

---

# 17. Analysis 验收 Gate

```text
[ ] Text Analysis -> Draft
[ ] Image Analysis -> Draft
[ ] Multiple Image Analysis -> Draft
[ ] MARKET / TICKER / SECTOR / MACRO 均可处理
[ ] 无明确方向时不会强行判断
[ ] 无明确价格时不会编价格
[ ] Manager 必须选择 Mentor 才能归档
[ ] Manager 可编辑
[ ] Manager 可 Rewrite
[ ] Archive Only 正确
[ ] Archive + Publish 正确
[ ] Public Card 不泄露 Mentor / Source / LLM
[ ] Card 发到 🛋️・member-lounge
[ ] 不创建 Thread
[ ] 同一 Mentor / Symbol 新观点创建新 analysis_id
[ ] 旧观点永不覆盖
[ ] Raw / Normalized / Public Snapshot 可追溯
[ ] Publication failure 可重试
[ ] LLM 实际 Model / Workload / Prompt Version 有记录
[ ] 所有测试通过
```

只有以上全部通过并稳定运行后，才允许进入 AXIS LAB。
