# AXIS Discord 初版开发规格

- **版本：** MVP v1
- **品牌：** AXIS
- **标语：** Signals without the noise.
- **主色：** 近黑色 + 米白色 + 少量薄荷绿
- **默认时区：** `America/Toronto`

---

## 1. 产品目标

AXIS 是一个极简收费 Discord。多个管理员可以把文字、截图或转发内容放入私人输入频道；系统使用 LLM 识别交易信息并生成待审核卡片。管理员选择内部 Mentor、检查并编辑卡片，确认后将不含 Mentor 和来源信息的纯交易卡片发布到对应会员信号频道。

首版只解决以下问题：

- 一个统一会员 Role 解锁全部会员内容。
- 三个信号频道：短线、波段、长期。
- 多管理员提交原始信号。
- LLM 识别文字和图片并生成结构化草稿。
- 管理员选择 Mentor、关联订单、编辑并确认发布。
- 每张会员卡片都可以点击查看该模式的当前订单。
- 后台维护 Mentor 当前订单、会员赠送和取消。
- 关闭订单进入官方战绩。
- AXIS LAB 仅预留两个私人频道和接口，最后开发。

### 1.1 首版不做

- 不为会员连接券商账户。
- 不为会员自动下单。
- 不把 Mentor 或来源显示给会员。
- 不允许 LLM 绕过管理员直接发布。
- 不实现复杂分级会员。
- 不实现公开网页仪表盘。
- 不在首版实现 Model A/B 正式训练或 Moomoo 扫描。
- 不自动删除服务器已有资源。

---

## 2. 品牌与视觉规范

### 2.1 品牌名称

```text
AXIS
```

内部研究模块统一命名为：

```text
AXIS LAB
```

### 2.2 配色

```text
Background     #0B0D0C
Primary Text   #F2F4EF
Muted Text     #9A9F9B
Accent Green   #86F7A8
Danger         #D66A6A
```

绿色仅用于：

- Logo 小段和轴线；
- Embed 左侧强调色；
- `查看当前订单` 按钮；
- 成功确认操作；
- 正收益数字。

整体视觉保持极简、专业和克制：

- 主背景使用接近纯黑或深黑；
- 主要文字使用白色或米白色；
- 强调色使用低饱和薄荷绿 / Signal Green；
- 不大面积使用绿色；
- 不使用渐变或霓虹风格。

Discord Embed 无法完全自定义背景，因此直接使用 Discord 深色主题，只控制 Embed Accent 和文案层级。

### 2.3 Logo 资产

图标版：

```text
assets/axis-icon.png
```

只包含 AXIS 图标，不包含文字，供 Discord Server Avatar 和 Bot Avatar 使用。

完整品牌版：

```text
assets/axis-brand-lockup.png
```

版式固定为：

```text
[AXIS 图标]

A X I S

Signals without the noise.
```

两种版本都保留非完全闭合圆环、中央 Axis 中轴结构、白色几何线条、少量绿色中轴或
触发点、黑色背景，以及极简、高级、专业的核心视觉语言。不得显示旧品牌名称。

首版不要在每张交易卡片中重复放 Logo，避免视觉噪音。完整品牌版主要用于服务器品牌页、
欢迎页和订阅页。

---

## 3. Role 设计

只保留一个人工管理 Role 和一个会员 Role。

```text
AXIS BOT
管理员
会员
@everyone
```

Role 顺序必须为：

```text
AXIS BOT
管理员
会员
@everyone
```

### 3.1 AXIS BOT

Bot 需要足够权限完成：

- 创建和调整频道；
- 创建和分配 Role；
- 发布、编辑和管理 Bot 消息；
- 读取管理员输入的文字和图片；
- 发送 Embed、附件和交互组件；
- 添加或移除会员 Role。

Bot Role 必须高于 `管理员` 和 `会员`。

### 3.2 管理员

管理员可以：

- 在 `信号输入` 提交文字和图片；
- 审核、编辑和发布卡片；
- 选择或更改 Mentor；
- 查看每个 Mentor 的当前订单；
- 创建、改名、停用和恢复 Mentor；
- 赠送会员、设置到期时间、取消或立即移除会员；
- 查看管理区。

管理员 Role **不授予 Discord Administrator 权限，也不直接授予 Manage Roles**。会员操作由 Bot 执行，减少误操作风险。

### 3.3 会员

只有一种会员。获得 `会员` Role 后，同时解锁：

- 短线信号；
- 波段信号；
- 长期信号；
- 会员交流。

---

## 4. Discord 频道结构

### 4.1 最终名称

```text
01｜⬛ 开始
├─ 👋・欢迎
├─ 💳・订阅
├─ 📊・官方战绩
├─ 💬・大厅
└─ 🏆・会员晒单

02｜🟢 会员
├─ ⚡・短线信号
├─ 〽️・波段信号
├─ ♾️・长期信号
└─ 💬・会员交流

90｜⚙️ 管理
├─ 📥・信号输入
├─ ✅・卡片审核
├─ 🧭・导师管理
└─ 👤・会员管理

99｜🧪 AXIS LAB
├─ 🟢・模型信号
└─ 🗂️・历史订单
```

### 4.2 频道权限

#### 开始区

| 频道 | @everyone | 会员 | 管理员 | Bot |
|---|---|---|---|---|
| 欢迎 | 查看 | 查看 | 查看 | 发布 |
| 订阅 | 查看 | 查看 | 查看 | 发布 |
| 官方战绩 | 查看 | 查看 | 查看 | 发布 |
| 大厅 | 查看/发言 | 查看/发言 | 查看/管理 | 发布/管理 |
| 会员晒单 | 仅查看 | 查看/发言/上传 | 查看/管理 | 发布/管理 |

#### 会员区

| 频道 | @everyone | 会员 | 管理员 | Bot |
|---|---|---|---|---|
| 短线信号 | 隐藏 | 只读 | 只读 | 发布/管理 |
| 波段信号 | 隐藏 | 只读 | 只读 | 发布/管理 |
| 长期信号 | 隐藏 | 只读 | 只读 | 发布/管理 |
| 会员交流 | 隐藏 | 查看/发言 | 查看/管理 | 发布/管理 |

#### 管理区

只有 `管理员`、Bot 和服务器 Owner 可见。管理员可以发言、上传附件并使用组件。

#### AXIS LAB

只有服务器 Owner 和 Bot 可见。管理员默认不可见。

---

## 5. 交易分类与编号

```text
SHORT_TERM → ST-0001
SWING      → SW-0001
LEAPS      → LP-0001
```

每种类型单独递增。编号一经发布不得复用。

会员频道映射：

```text
SHORT_TERM → ⚡・短线信号
SWING      → 〽️・波段信号
LEAPS      → ♾️・长期信号
```

LLM 可以建议分类，但管理员必须可以修改。

---

## 6. 仓位模型

数据库统一使用八分之一单位保存仓位：

```text
0 → 清仓
1 → 1/8 仓位
2 → 1/4 仓位
3 → 3/8 仓位
4 → 1/2 仓位
5 → 5/8 仓位
6 → 3/4 仓位
7 → 7/8 仓位
8 → 满仓
```

### 6.1 默认建仓阶梯

| 操作 | 本次增加 | 操作后持仓 |
|---|---:|---:|
| 首次入场 | 1/8 | 1/8 |
| 第一次加仓 | 1/8 | 1/4 |
| 第二次加仓 | 1/4 | 1/2 |
| 第三次加仓 | 1/4 | 3/4 |
| 特殊第四次加仓 | 1/4 | 满仓 |

前三次是默认流程。第四次必须由管理员手动选择。

### 6.2 校验规则

- `position_after_eighths` 必须在 0 到 8 之间。
- 加仓后的仓位不得小于加仓前仓位。
- 减仓后的仓位不得大于减仓前仓位。
- 完全平仓时必须为 0。
- 管理员可以覆盖默认阶梯，但必须记录审计日志。
- 会员卡片优先显示“本次操作仓位”和“操作后持仓”。

---

## 7. 会员公开操作名称

会员不显示后台 `ACTIVE`、`CLOSED` 等英文状态。每张卡片顶部显示本次公开操作：

```text
入场
第一次加仓
第二次加仓
第三次加仓
订单更新
止盈一
止盈二
保留尾仓
部分触发 SL
触发 SL
全部平仓
取消订单
滚仓
```

后台只保留以下简单状态：

```text
DRAFT
ACTIVE
RUNNER
CLOSED
CANCELLED
```

用途仅为系统判断订单是否出现在“当前订单”中，不向会员展示。

---

## 8. 会员卡片模板

所有会员卡片必须：

- 使用中文；
- 使用 `SL`，不要写 `Stop` 或“止损价”；
- 不显示 `Market`、Bid、Ask；
- 不显示 Mentor、来源、提交人、原始图片、内部备注或解析置信度；
- 最下方始终有 `查看当前订单` 按钮；
- 卡片发布后保存 Discord Message ID；
- 更新操作发送一张新卡片，保留完整时间线；
- 只有“纠错”才编辑已发布卡片，并记录审计日志。

### 8.1 入场

```text
入场 · ST-0027

TSLA · 09/16/2026 · 400C

入场区间
$3.20 – $3.35

当前持仓
1/8 仓位

SL
$2.55

TP1
$4.10

TP2
$5.00

[ 查看当前订单 ]
```

### 8.2 第一次加仓

```text
第一次加仓 · ST-0027

TSLA · 09/16/2026 · 400C

本次加仓价格
$3.05

本次加仓
1/8 仓位

加仓后平均成本
$3.18

加仓后持仓
1/4 仓位

当前收益
-4.1%

SL
$2.55

[ 查看当前订单 ]
```

### 8.3 第二次加仓

```text
第二次加仓 · ST-0027

TSLA · 09/16/2026 · 400C

本次加仓价格
$2.92

本次加仓
1/4 仓位

加仓后平均成本
$3.05

加仓后持仓
1/2 仓位

当前收益
-4.3%

SL
$2.45

[ 查看当前订单 ]
```

### 8.4 第三次加仓

```text
第三次加仓 · ST-0027

TSLA · 09/16/2026 · 400C

本次加仓价格
$2.80

本次加仓
1/4 仓位

加仓后平均成本
$2.97

加仓后持仓
3/4 仓位

当前收益
-5.7%

SL
$2.40

[ 查看当前订单 ]
```

### 8.5 订单更新

```text
订单更新 · ST-0027

TSLA · 09/16/2026 · 400C

SL 调整
$2.55 → $3.20

当前平均成本
$3.05

当前收益
+12.8%

当前持仓
1/2 仓位

TP1
$4.10

TP2
$5.00

[ 查看当前订单 ]
```

### 8.6 止盈一

```text
止盈一 · ST-0027

TSLA · 09/16/2026 · 400C

止盈价格
$4.10

本次卖出
1/4 仓位

当前平均成本
$3.05

本次收益
+34.4%

止盈后持仓
1/4 仓位

新 SL
$3.05

下一个目标
$5.00

[ 查看当前订单 ]
```

### 8.7 止盈二并保留尾仓

```text
止盈二 · ST-0027

TSLA · 09/16/2026 · 400C

止盈价格
$5.00

本次卖出
1/8 仓位

当前平均成本
$3.05

本次收益
+63.9%

止盈后持仓
1/8 仓位

操作
保留尾仓

新 SL
$4.40

[ 查看当前订单 ]
```

### 8.8 保留尾仓

```text
保留尾仓 · ST-0027

TSLA · 09/16/2026 · 400C

最近操作价格
$5.00

当前平均成本
$3.05

当前收益
+63.9%

当前持仓
1/8 仓位

SL
$4.40

操作
继续持有尾仓

[ 查看当前订单 ]
```

### 8.9 触发 SL

```text
触发 SL · ST-0027

TSLA · 09/16/2026 · 400C

平仓价格
$2.55

当前平均成本
$3.05

本次结果
-16.4%

本次卖出
1/2 仓位

平仓后持仓
清仓

操作
订单结束

[ 查看当前订单 ]
```

### 8.10 全部平仓

```text
全部平仓 · ST-0027

TSLA · 09/16/2026 · 400C

平仓价格
$4.72

当前平均成本
$3.05

本次结果
+54.8%

本次卖出
1/4 仓位

平仓后持仓
清仓

操作
订单结束

[ 查看当前订单 ]
```

---

## 9. 查看当前订单

每一张信号卡片下方都放同一个长期有效按钮：

```text
查看当前订单
```

按钮按频道模式读取数据库：

```text
短线信号 → SHORT_TERM
波段信号 → SWING
长期信号 → LEAPS
```

点击后使用仅点击者可见的交互回复，不在频道刷屏。

### 9.1 显示内容

只显示：

- 交易编号；
- 合约；
- 最近一次公开操作；
- 当前持仓。

不提供二次展开，也不显示 Entry、SL、TP、当前价格、Mentor 或来源。

```text
当前短线订单

ST-0027
TSLA 09/16 400C
止盈一 · 当前持仓 1/4 仓位

ST-0031
NVDA 09/18 210C
入场 · 当前持仓 1/8 仓位

ST-0036
META 09/16 800C
第二次加仓 · 当前持仓 1/2 仓位

ST-0038
SPXW 08/31 5700P
保留尾仓 · 当前持仓 1/8 仓位
```

以下订单不再出现：

```text
触发 SL 且持仓为 0
全部平仓
取消订单
```

### 9.2 技术要求

- 按钮使用固定、可恢复的 `custom_id`。
- Discord Bot 重启后按钮仍然工作。
- 示例：

```text
axis:active:short_term:v1
axis:active:swing:v1
axis:active:leaps:v1
```

- 响应必须是 ephemeral。
- 查询结果必须以数据库为准，不从旧消息反推。

---

## 10. 信号输入与 LLM 解析

### 10.1 输入来源

管理员可以在 `📥・信号输入` 中发送：

- 纯文字；
- 一张或多张图片；
- 文字加图片；
- 开仓、加仓、更新、止盈、SL、尾仓、平仓或滚仓信息。

### 10.2 处理流程

```text
管理员发送原始内容
→ 保存 Source Message 和附件元数据
→ 下载并验证附件
→ 调用 LLM 多模态解析
→ 使用严格 JSON Schema 验证
→ 生成 Trade Draft
→ 尝试匹配可能的当前订单
→ 发布到卡片审核
→ 等待管理员处理
```

### 10.3 附件限制

首版支持：

```text
PNG
JPG / JPEG
WEBP
```

建议单文件不超过 10 MB。拒绝可执行文件和未知 MIME Type。

### 10.4 LLM 原则

- 使用 Structured Output / JSON Schema。
- LLM 只能生成草稿，不能发布。
- 未识别字段必须返回 `null`，不得猜测。
- 不确定 Call/Put、到期日、Strike 或操作类型时，必须加到 `missing_fields` 或 `warnings`。
- 不允许从图片中的昵称直接自动分配 Mentor。
- `mentor_hint` 只可作为内部提示，管理员仍需明确选择。

JSON Schema 位于：

```text
config/llm_trade_schema.json
```

---

## 11. 卡片审核

LLM 解析后，Bot 在 `✅・卡片审核` 发布管理员专用 Draft：

```text
待审核订单 · D-1042

识别操作
第二次加仓

合约
TSLA 09/16/2026 400C

本次操作价格
$2.92

本次加仓
1/4 仓位

加仓后平均成本
$3.05

加仓后持仓
1/2 仓位

当前收益
-4.3%

SL
$2.45

建议分类
短线

Mentor
尚未选择

可能对应订单
ST-0027
```

### 11.1 操作组件

```text
选择 Mentor
选择订单
编辑卡片
预览会员卡片
确认发布
删除草稿
```

### 11.2 发布前条件

新订单至少需要：

- Mentor 已选择；
- 分类已选择；
- Ticker；
- Expiry；
- Strike；
- Call/Put；
- 入场价格或区间；
- 当前持仓。

更新订单至少需要：

- Mentor 已选择；
- 已关联现有 Trade ID；
- 操作类型；
- 操作价格或明确更新内容；
- 操作后持仓。

### 11.3 并发控制

- Draft 保存 `version`。
- 管理员打开编辑时带入版本号。
- 若另一管理员已修改，旧版本提交必须被拒绝并提示重新加载。
- `确认发布` 必须幂等；重复点击不得重复发卡。

---

## 12. Mentor 管理

Mentor 是内部属性，永远不进入公开卡片。

### 12.1 Mentor 数据

```text
mentor_id
name
short_code
aliases
is_active
created_at
updated_at
```

### 12.2 导师管理频道

在 `🧭・导师管理` 放置一张长期控制面板：

```text
导师管理

[ 选择 Mentor ]
[ 新增 Mentor ]
[ 编辑 Mentor ]
```

选择 Mentor 后，仅对管理员本人显示：

```text
VINCENT

当前订单

ST-0027
TSLA 09/16 400C
止盈一 · 1/4 仓位

SW-0014
GOOGL 10/16 400C
入场 · 1/8 仓位
```

管理员可以：

- 查看当前订单；
- 查看历史订单；
- 更改订单 Mentor；
- 创建 Mentor；
- 改名；
- 停用；
- 重新启用。

更改 Mentor 只影响后台归属，不修改公开会员卡片。

---

## 13. 会员管理

只有一个 `会员` Role。

在 `👤・会员管理` 放置长期控制面板：

```text
会员管理

[ 查找会员 ]
[ 赠送会员 ]
[ 延长会员 ]
[ 到期取消 ]
[ 立即移除 ]
```

### 13.1 会员记录

```text
user_id
status
source
starts_at
ends_at
cancel_at_period_end
created_by
created_at
updated_at
```

`source` 示例：

```text
MANUAL
GIFT
PAYMENT
IMPORT
```

### 13.2 操作规则

- `赠送会员`：添加 `会员` Role 并设置到期时间。
- `延长会员`：在当前到期时间基础上增加时长。
- `到期取消`：保留 Role 到 `ends_at`，到期后自动移除。
- `立即移除`：立即移除 Role 并记录原因。
- 不自动 Kick 或 Ban。
- Owner 手动添加或移除 `会员` Role 时，Bot 应同步数据库并标记为 `MANUAL`。
- 定时任务至少每 5 分钟检查一次已到期会员。

### 13.3 订阅支付

首版只提供：

- `💳・订阅` 中的外部支付链接；
- `SUBSCRIPTION_URL` 配置；
- 可插拔 `PaymentProvider` 接口。

在支付供应商未确定前，不实现特定 Stripe、Whop 或其他平台逻辑。

---

## 14. 官方战绩

完全关闭的订单自动进入 `📊・官方战绩`。

### 14.1 计算方式

后台把最大仓位标准化为 8 个单位。每次加仓和减仓都记录单位数和价格。

```text
entry_cost = Σ(entry_price × added_units)
exit_value = Σ(exit_price × sold_units)
final_return = (exit_value - entry_cost) / entry_cost
```

只有完全清仓后才计算最终收益。部分止盈时显示“本次收益”，但不把它当作整笔最终收益。

### 14.2 关闭订单卡片

```text
订单结束 · ST-0027

TSLA · 09/16/2026 · 400C

最终结果
+38.6%

最高持仓
1/2 仓位

结束方式
全部平仓
```

### 14.3 周总结

建议每周五美东时间收盘后生成：

```text
本周官方战绩

关闭订单      12
盈利订单       8
亏损订单       4
胜率         66.7%
平均盈利     +31.4%
平均亏损     -14.2%
```

首版允许通过配置关闭周总结。

---

## 15. 数据模型

建议 PostgreSQL 表：

```text
guild_config
mentors
mentor_aliases
source_messages
source_attachments
trade_drafts
trades
trade_events
public_messages
memberships
membership_events
subscriptions
audit_logs
scheduled_jobs
```

### 15.1 trades

核心字段：

```text
id
public_trade_id
category
mentor_id
ticker
expiry
strike
option_side
state
last_public_action
position_eighths
avg_cost
sl
tp1
tp2
opened_at
closed_at
created_at
updated_at
version
```

### 15.2 trade_events

每次操作单独记录：

```text
id
trade_id
action
action_stage
price
position_delta_eighths
position_after_eighths
avg_cost_after
pnl_pct
sl_before
sl_after
tp1_after
tp2_after
source_message_id
approved_by
published_message_id
created_at
```

### 15.3 Public DTO 白名单

公开卡片生成器只能接收：

```text
public_trade_id
category
action
ticker
expiry
strike
option_side
entry_low
entry_high
action_price
avg_cost
pnl_pct
position_delta_eighths
position_after_eighths
sl
tp1
tp2
```

禁止 Public DTO 出现：

```text
mentor_id
mentor_name
submitted_by
source_message_id
raw_text
attachment_url
parser_confidence
internal_notes
```

必须为此添加自动化测试。

---

## 16. 推荐项目结构

```text
axis/
├─ app/
│  ├─ bot/
│  │  ├─ client.py
│  │  ├─ intents.py
│  │  ├─ bootstrap.py
│  │  ├─ cogs/
│  │  │  ├─ signal_input.py
│  │  │  ├─ card_review.py
│  │  │  ├─ active_trades.py
│  │  │  ├─ mentor_control.py
│  │  │  ├─ member_control.py
│  │  │  └─ results.py
│  │  └─ views/
│  │     ├─ persistent_active.py
│  │     ├─ review_views.py
│  │     ├─ mentor_views.py
│  │     └─ member_views.py
│  ├─ domain/
│  │  ├─ enums.py
│  │  ├─ models.py
│  │  ├─ schemas.py
│  │  └─ services/
│  ├─ integrations/
│  │  ├─ llm/
│  │  ├─ payments/
│  │  └─ moomoo/
│  ├─ ui/
│  │  ├─ card_builder.py
│  │  └─ chinese_labels.py
│  ├─ db/
│  │  ├─ models.py
│  │  ├─ session.py
│  │  └─ repositories/
│  ├─ tasks/
│  │  ├─ membership_expiry.py
│  │  └─ weekly_results.py
│  └─ config.py
├─ migrations/
├─ scripts/
│  ├─ bootstrap_discord.py
│  ├─ reconcile_discord.py
│  └─ seed_control_panels.py
├─ tests/
├─ config/
│  ├─ discord_blueprint.yaml
│  └─ llm_trade_schema.json
├─ assets/
├─ docker-compose.yml
├─ Dockerfile
├─ pyproject.toml
└─ README.md
```

---

## 17. Discord Bootstrap

### 17.1 输入

初始只需要：

```text
DISCORD_BOT_TOKEN
DISCORD_APPLICATION_ID
DISCORD_GUILD_ID
DISCORD_OWNER_USER_ID
```

### 17.2 首次流程

```text
连接指定 Guild
→ 读取现有 Role、Category、Channel
→ 生成差异计划
→ 输出 dry-run
→ APPLY_CHANGES=true 后创建缺失资源
→ 调整 Role 顺序
→ 应用权限覆盖
→ 创建或复用长期控制面板
→ 输出生成的 ID 到 discord_ids.json
```

### 17.3 幂等要求

- 优先使用已保存的 Discord ID。
- ID 不存在时，按完全相同名称和资源类型尝试恢复。
- 名称相同但类型不同时停止并报错。
- 不删除额外频道。
- 不修改非项目 Role。
- 控制面板通过数据库保存 Message ID，避免重复创建。

---

## 18. Discord Intent 与权限

### 18.1 Intent

需要启用：

```text
Guilds
Guild Messages
Message Content
Guild Members
```

原因：

- 读取 `信号输入` 的任意文字和附件；
- 监听会员 Role 的手动增删；
- 管理到期会员；
- 读取 Guild、Channel 和 Role。

### 18.2 Bot 权限

建议使用最小权限：

```text
View Channels
Send Messages
Manage Messages
Read Message History
Embed Links
Attach Files
Use Application Commands
Manage Channels
Manage Roles
```

若 Bootstrap 还要修改服务器名称或图标，单独通过 Feature Flag 增加 `Manage Guild`，默认关闭。

---

## 19. Secret 管理

用户可能会提供 Discord ID 和 Key。Codex 必须：

- 将 Secret 写入本地 `.env` 或部署平台 Secret；
- `.env` 永远加入 `.gitignore`；
- 不在终端输出完整 Token；
- 日志最多显示末尾四位；
- 不把 Secret 放入异常追踪上下文；
- 不把 Secret 写入生成的 `discord_ids.json`；
- 若检测到源码或 Git 历史中出现 Token，立即停止并提示轮换。

公开配置和 Secret 必须分开：

```text
Discord Guild ID → 可放配置
Channel / Role ID → 可放配置
Bot Token → 只能放 Secret
LLM API Key → 只能放 Secret
Database Password → 只能放 Secret
```

---

## 20. AXIS LAB 预留

首版创建但默认禁用：

```text
99｜🧪 AXIS LAB
├─ 🟢・模型信号
└─ 🗂️・历史订单
```

环境变量：

```text
FEATURE_LAB_ENABLED=false
FEATURE_MOOMOO_ENABLED=false
FEATURE_MODEL_AB_ENABLED=false
```

### 20.1 后续模型信号

以后由 Moomoo 行情接口提供数据，Model A 按不同 Mentor 的历史策略寻找候选，Model B 判断入场点。结果只发送到 `🟢・模型信号`。

### 20.2 后续历史订单

`🗂️・历史订单` 只放：

- 已结束模型订单；
- 未触发或取消的观察信号；
- 每日收盘总结。

会员不可见，首版不实现自动下单。

---

## 21. 审计日志

所有管理员操作必须记录：

```text
actor_user_id
action_type
entity_type
entity_id
before_json
after_json
discord_interaction_id
created_at
```

最低覆盖：

- Draft 编辑；
- Mentor 选择和更改；
- 订单发布；
- 已发布卡片纠错；
- 仓位覆盖；
- 会员赠送、延期、到期取消和立即移除；
- Mentor 创建、改名、停用和恢复。

---

## 22. 错误处理

- LLM 超时：Draft 标记 `PARSE_FAILED`，允许管理员重试或手动录入。
- 图片不支持：提示管理员重新上传支持格式。
- 缺少必要字段：不允许发布，明确列出缺失字段。
- Discord 发布失败：数据库事务回滚或标记 `PUBLISH_FAILED`，允许安全重试。
- 重复点击发布：返回“该草稿已发布”。
- Bot 无权限：明确指出缺少的权限，不继续执行部分 Bootstrap。
- Discord 或数据库暂时不可用：采用有上限的指数退避，不无限重试。

---

## 23. 测试要求

### 23.1 单元测试

- 仓位八分之一格式转换。
- 默认加仓阶梯。
- 加仓、减仓、清仓校验。
- 公开卡片字段白名单。
- 各操作卡片文案。
- Active View 过滤关闭订单。
- 最终收益计算。

### 23.2 集成测试

- 文本输入生成 Draft。
- 图片输入生成 Draft。
- 管理员选择 Mentor 后发布。
- 未选择 Mentor 不允许发布。
- 更新订单正确关联 Trade ID。
- 按钮在 Bot 重启后仍可工作。
- 会员过期后移除 Role。
- 手动 Role 变更同步数据库。

### 23.3 安全测试

扫描所有公开消息内容，确保不出现：

```text
Mentor 名称
source
submitted_by
raw_text
attachment URL
API Key
Bot Token
```

---

## 24. MVP 验收标准

项目达到以下条件才算完成：

1. Bootstrap 可在指定 Guild 中幂等创建全部 Role、Category 和 Channel。
2. 权限与本规格一致，普通用户无法看到会员区、管理区和 AXIS LAB。
3. 管理员发送文字或图片后，系统生成待审核草稿。
4. 管理员可以选择 Mentor、关联订单、编辑字段和预览卡片。
5. 未确认前不会发布任何会员信号。
6. 公开卡片不含 Mentor 和来源字段。
7. 入场默认 1/8；默认加仓阶梯为 1/4、1/2、3/4。
8. 加仓卡片可以编辑本次加仓、加仓后平均成本和加仓后持仓。
9. 每张会员卡片下方都有长期有效的 `查看当前订单`。
10. Active View 只显示合约、最近操作和当前仓位，不可继续展开。
11. 清仓、全部触发 SL 或取消后从 Active View 移除。
12. Mentor 可以动态新增、改名、停用、恢复和重新分配。
13. 会员可以赠送、延期、到期取消和立即移除。
14. 关闭订单进入官方战绩并计算加权最终收益。
15. 所有关键写操作有审计记录。
16. Secret 不在源码、日志或 Git 中出现。
17. 自动化测试通过，提供 Docker 启动方式。
18. AXIS LAB 频道创建完成，但功能默认关闭。

---

## 25. 推荐开发阶段

### Phase 1 — Discord 基础

- 项目骨架；
- 数据库；
- Bootstrap；
- Role、Category、Channel、权限；
- 长期控制面板。

### Phase 2 — 交易工作流

- 信号输入；
- LLM 解析；
- Draft；
- Mentor 选择；
- 编辑与发布；
- 交易事件和卡片。

### Phase 3 — 管理功能

- 查看当前订单；
- Mentor 管理；
- 会员管理；
- 官方战绩；
- 定时任务。

### Phase 4 — 稳定性

- 幂等；
- 并发控制；
- 审计；
- 测试；
- Docker；
- 部署。

### Phase 5 — AXIS LAB

最后再实现：

- Moomoo 行情接口；
- Model A/B；
- 模型信号；
- 历史订单与每日总结；
- 用户自己的模拟或实盘自动化。

会员自动交易始终不在范围内。
