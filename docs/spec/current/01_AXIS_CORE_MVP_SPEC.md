# AXIS — Discord Core & Signal MVP Specification

**版本：** MVP v2  
**品牌：** AXIS  
**默认时区：** `America/Toronto`  
**开发优先级：** 第一阶段

---

# 1. 产品目标

AXIS 是一个极简收费 Discord。多个 `Manager` 可以把交易文字、截图或图片输入私人频道。系统使用 OpenAI API 将原始内容结构化成 Trade Draft，发送到 Manager 审核区；Manager 选择内部 Mentor、编辑并确认后，系统发布不带 Mentor / Source 的统一中文交易卡片到会员信号频道。

会员只有一种 Membership，获得 `Member` Role 后可访问全部会员内容。

自动交易仅为未来 Owner 自己的 AXIS LAB 设计，不向会员提供自动跟单。

---

# 2. 品牌

```text
AXIS
Signals without the noise.
```

视觉：近黑色、米白色、少量 Signal Green。

```text
Background     #0B0D0C
Primary Text   #F2F4EF
Muted Text     #9A9F9B
Accent Green   #86F7A8
Danger         #D66A6A
```

Logo 使用 `assets/axis-logo.png`。

---

# 3. Discord Role

只保留：

```text
AXIS BOT
Manager
Member
@everyone
```

Role hierarchy：

```text
AXIS BOT
Manager
Member
@everyone
```

`Manager` 不直接授予 Discord `Administrator` 或 `Manage Roles`；业务操作由 Bot 执行。

---

# 4. Discord Category / Channel

所有 Category / Channel 使用 **Emoji + English**。

```text
⬛・GENERAL
├─ 👋・welcome
├─ 💳・subscriptions
├─ 📊・results
├─ 💬・lobby
└─ 🏆・member-wins

🟢・MEMBERS
├─ ⚡・short-term
├─ 〽️・swing
├─ ♾️・leaps
└─ 🛋️・member-lounge

⚙️・MANAGER
├─ 📥・signal-input
├─ ✅・card-review
├─ 💭・analysis-input
├─ 📝・analysis-review
├─ 🧭・mentor-control
└─ 👤・member-control

🧪・AXIS LAB
├─ 🟢・lab-signals
├─ 🧬・mentor-status
└─ 🗂️・lab-history
```

`AXIS LAB` 功能现在不开发，只创建私人频道并保持 Owner-only。

---

# 5. Channel Permissions

## GENERAL

- `welcome`：所有人只读，Bot 发布。
- `subscriptions`：所有人只读，Bot 发布收费链接 / 管理订阅入口。
- `results`：所有人只读，Bot 发布官方战绩。
- `lobby`：所有人可聊天。
- `member-wins`：默认所有人可查看；只有 Member 可发言 / 上传，Manager 可管理。

## MEMBERS

只有 `Member`、`Manager`、Owner、Bot 可见。

- `short-term / swing / leaps`：会员只读，Bot 发布。
- `member-lounge`：Member 可正常聊天；Analysis Card 也发到这里。

## MANAGER

只有 `Manager`、Owner、Bot 可见。

## AXIS LAB

只有 Owner 与 Bot 可见。Manager 默认不可见。

---

# 6. Signal 分类

```text
SHORT_TERM -> ST-0001 -> ⚡・short-term
SWING      -> SW-0001 -> 〽️・swing
LEAPS      -> LP-0001 -> ♾️・leaps
```

LLM 可建议分类，但 Manager 可以修改。

---

# 7. 仓位体系

数据库使用八分之一单位：

```text
0 = 清仓
1 = 1/8 仓位
2 = 1/4 仓位
3 = 3/8 仓位
4 = 1/2 仓位
5 = 5/8 仓位
6 = 3/4 仓位
7 = 7/8 仓位
8 = 满仓
```

默认建仓阶梯：

```text
首次入场        -> 1/8
第一次加仓后    -> 1/4
第二次加仓后    -> 1/2
第三次加仓后    -> 3/4
特殊第四次加仓  -> 满仓（仅 Manager 手动选择）
```

所有实际仓位均可由 Manager 编辑；默认阶梯只是自动建议。

---

# 8. Public Action 与内部 Trade State

会员卡片顶部显示本次动作，不显示后台 State。

公开动作：

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

后台只需：

```text
DRAFT
ACTIVE
RUNNER
CLOSED
CANCELLED
```

`trade_state` 仅用于业务判断；`last_public_action` 用于 Active View。

---

# 9. 会员交易卡片规则

所有 Public Signal Card：

- 正文中文。
- 使用 `SL`，不写 `Stop`。
- 不显示 Market / Bid / Ask。
- 不显示 Mentor。
- 不显示 Source / Submitted By / Raw Input / Parser Confidence。
- 更新发送新卡片，形成完整时间线。
- 只有纠错才编辑旧卡片，并写 Audit Log。
- 每张卡片底部固定有 `查看当前订单`。

## Entry

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

## First Add

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

## Second Add

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

## Third Add

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

## TP / Runner / SL / Close

必须显示尽可能适用的：

```text
本次操作价格
当前平均成本
本次操作仓位
操作后持仓
当前收益 / 本次收益
SL
下一个目标
操作说明
```

例如：

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

---

# 10. 查看当前订单

每张 Signal Card 下方都有 persistent button：

```text
查看当前订单
```

按所在 Signal Channel 映射当前模式。

点击后使用 ephemeral response，只显示：

- Public Trade ID
- Contract
- 最近一次 Public Action
- 当前持仓

不允许进一步展开。

```text
当前短线订单

ST-0027
TSLA 09/16 400C
止盈一 · 当前持仓 1/4 仓位

ST-0031
NVDA 09/18 210C
入场 · 当前持仓 1/8 仓位
```

关闭 / 清仓 / Cancel 的交易不出现。

固定 `custom_id`：

```text
axis:active:short_term:v1
axis:active:swing:v1
axis:active:leaps:v1
```

Bot 重启后仍必须可用。

---

# 11. Signal Input Pipeline

`📥・signal-input` 支持：

- text
- PNG/JPG/JPEG/WEBP
- text + image
- multiple images
- ENTRY / ADD / UPDATE / TP / SL / RUNNER / CLOSE / ROLL

流程：

```text
Raw Manager Message
-> save source_messages / attachments
-> OpenAI Responses API
-> structured trade parse
-> JSON Schema validation
-> create Trade Draft
-> suggest possible existing Trade match
-> post internal review card to ✅・card-review
-> wait for Manager action
```

LLM 只能生成 Draft，绝不直接发布。

缺失字段返回 `null` / `missing_fields`，不能猜。

Mentor 必须由 Manager 明确选择。

---

# 12. LLM Workload Routing

Signal Parse 不使用全局单一 `LLM_MODEL`。

当前：

```text
SIGNAL_PARSE  -> gpt-5.6-terra
SIGNAL_REPAIR -> gpt-5.6-terra
```

理由：Signal 主要是识别与严格结构化，优先成本 / 延迟 / 稳定性平衡。

业务代码调用：

```text
llm_router.execute(workload="SIGNAL_PARSE", ...)
```

而不是：

```text
client.responses.create(model="hard-coded-model", ...)
```

模型 ID 来自 `config/model_routing.yaml` / environment overrides。

每个 Trade Draft 保存：

```text
llm_provider
llm_model
llm_workload
prompt_version
schema_version
parse_latency_ms
```

---

# 13. Card Review

内部 Draft Card 可显示：

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

组件：

```text
选择 Mentor
选择订单
编辑卡片
预览会员卡片
确认发布
删除草稿
```

发布必须幂等，重复点击不能重复发卡。

---

# 14. Mentor Registry / Control

Mentor 动态维护：

```text
mentor_id
name
short_code
aliases
is_active
created_at
updated_at
```

`🧭・mentor-control` 中放长期控制面板：

```text
[ 选择 Mentor ]
[ 新增 Mentor ]
[ 编辑 Mentor ]
```

Manager 可以查看该 Mentor 当前 / 历史订单、修改订单 Mentor、创建 / 改名 / 停用 / 恢复 Mentor。

Mentor 改动只影响内部数据，不修改 Public Card。

---

# 15. Member Control

只有一种 Membership / `Member` Role。

`👤・member-control`：

```text
[ 查找会员 ]
[ 赠送会员 ]
[ 延长会员 ]
[ 到期取消 ]
[ 立即移除 ]
```

支持：

```text
7 Days
30 Days
90 Days
Lifetime
Custom
```

Owner 手工添加 / 移除 `Member` Role 时，Bot 同步数据库。

不自动 Kick / Ban。

支付 Provider 首版只预留接口；`subscriptions` 使用外部链接。

---

# 16. Results

全部清仓的订单进入 `📊・results`。

收益按仓位事件加权计算，不允许用最后价格简单替代整笔结果。

数据库记录每次：

```text
position_delta_eighths
position_after_eighths
price
```

最终：

```text
entry_cost = sum(entry/add price * added units)
exit_value = sum(exit price * sold units)
final_return = (exit_value - entry_cost) / entry_cost
```

官方 Results 不能选择性删除亏损交易。

---

# 17. Data Domain

核心表：

```text
guild_config
mentors
mentor_aliases
source_messages
source_attachments
trade_drafts
trades
trade_events
trade_publications
memberships
membership_events
subscriptions
audit_logs
scheduled_jobs
llm_invocations
```

`trades` 至少：

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

`trade_events` 至少：

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

---

# 18. Public DTO Security Boundary

Public Card Builder 只能接收白名单字段。

禁止 Public DTO 包含：

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

必须有自动化测试保证 Mentor / Source 不可能泄漏。

---

# 19. Secret / Bootstrap

Codex 首先执行只读 Guild inventory + dry-run。

不得自动删除、改名、移动不属于 AXIS 的现有资源。

Secret：

- 只放 `.env` / deployment secret store。
- 不写源码。
- 不写 Git。
- 不在日志输出完整值。

Bootstrap 必须幂等。

---

# 20. Core 验收 Gate

Core + Signal 必须全部通过后才能开始 Analysis Pipeline：

```text
[ ] Channel / Role / Permission 正确
[ ] Bootstrap 重复运行无重复资源
[ ] Text Signal -> Draft
[ ] Image Signal -> Draft
[ ] Multiple Image Signal -> Draft
[ ] Manager 可选择 Mentor
[ ] Manager 可关联现有 Trade
[ ] Manager 可编辑仓位 / 成本 / SL / TP
[ ] 未确认绝不发布
[ ] Public Card 不泄露 Mentor / Source
[ ] Active button Bot 重启后可用
[ ] Active View 内容正确
[ ] Member gift / expiry / revoke 正确
[ ] Mentor create / rename / deactivate / reactivate 正确
[ ] Results 加权收益正确
[ ] Audit Log 完整
[ ] Secret scan 通过
[ ] 单元 / 集成 / 安全测试通过
```

通过后才进入 `02_AXIS_ANALYSIS_PIPELINE_SPEC.md`。
