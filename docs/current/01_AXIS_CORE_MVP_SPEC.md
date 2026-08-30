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
├─ ✅・signal-review
├─ 💭・analysis-input
├─ 📝・analysis-review
├─ 🧭・mentor-control
├─ 👤・member-control
└─ 🤫・quiet-profits

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

`🤫・quiet-profits` 是 Manager 私人交流频道，Manager 可以发言和上传附件。

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
- Swing / LEAPS 卡片底部固定有 `查看当前持仓订单`；Short-Term 不显示按钮。

## Entry

```text
入场 · SW-0027

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

[ 查看当前持仓订单 ]
```

## First Add

```text
第一次加仓 · SW-0027

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

[ 查看当前持仓订单 ]
```

## Second Add

```text
第二次加仓 · SW-0027

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

[ 查看当前持仓订单 ]
```

## Third Add

```text
第三次加仓 · SW-0027

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

[ 查看当前持仓订单 ]
```

> Short-Term 的 TP、Runner、Active View、Daily Summary 与 Results 规则已由
> `05_SIGNAL_SYSTEM_TP_LOTTO_RESULTS_SPEC.md` 覆盖。本节仅继续适用于 Swing / LEAPS。

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
止盈一 · SW-0027

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

[ 查看当前持仓订单 ]
```

---

# 10. 查看当前持仓订单

Swing / LEAPS Signal Card 下方有 persistent button：

```text
查看当前持仓订单
```

按所在 Signal Channel 映射当前模式。

点击后使用 ephemeral response，只显示：

- Public Trade ID
- Contract
- 最近一次 Public Action
- 当前持仓

不允许进一步展开。

```text
当前波段订单

SW-0027
TSLA 09/16 400C
止盈一 · 当前持仓 1/4 仓位

SW-0031
NVDA 09/18 210C
入场 · 当前持仓 1/8 仓位
```

关闭 / 清仓 / Cancel 的交易不出现。

固定 `custom_id`：

```text
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
- Discord forwarded message snapshot text + images
- ENTRY / ADD / UPDATE / TP / SL / RUNNER / CLOSE / ROLL

Discord 可能把转发/粘贴图片标为 `.webp` 文件名但返回 PNG MIME。附件格式以真实文件签名
为最终依据；只有元数据互相冲突时允许安全归一化，明确伪装仍拒绝。

流程：

```text
Raw Manager Message
-> save source_messages / attachments
-> OpenAI Responses API
-> structured trade parse
-> JSON Schema validation
-> create Trade Draft
-> suggest possible existing Trade match
-> post internal review card to ✅・signal-review
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

# 13. Signal Review

内部 Draft Card 可显示：

```text
待审核订单 · S-00001

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

# 16A. Daily Post-Close Category Summaries

`⚡・short-term`、`〽️・swing`、`♾️・leaps` 每个美股交易日 `16:15 ET` 各发布一条总结：

```text
Active 收盘总结
今日 Closed 总结
```

Core 只允许通过本地 Moomoo OpenD 获取只读美股期权快照：

```text
期权代码必须由 underlying + expiry + strike + Call/Put 在 option chain 精确解析
不得手工拼接期权代码
不得读取账户、资金、持仓或订单
不得 unlock trade、下单、改单或撤单
```

会员只显示 `当前/收盘参考价`、行情时间与基于 `avg_cost` 的浮动收益；不显示
`Market / Bid / Ask`。行情不可用时显示不可用，不得猜测或沿用无时间信息的价格。

每日发布以 `guild + category + session_date` 唯一，Discord marker 与数据库状态共同防止
重启或重试时重复发送。周末、假日以及无法确认交易日时不发布。

此功能属于 AXIS Core 运维，不启用 AXIS LAB、Model A / B 或自动交易。

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
market_quote_snapshots
daily_summary_publications
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
moomoo_option_code
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

每日总结 Public DTO 同样不得包含 Mentor、Source、Parser、LLM、账户、Bid、Ask 或内部
Moomoo 合约代码。

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

---

# 21. Short-Term Automated Tracking Lock

Short-Term 是 Signal Core 的独立交易路径：

- `SHORT_TERM` 可以由结构化 Signal 自动建议，Manager 仍可在 Review 修正 Category。
- Review 使用精简表单，只保留 Ticker、Expiry、Strike、Call/Put 与 Entry Price。
- Short-Term 不选择 Mentor、不关联 Mentor Trade、不使用八分之一仓位字段。
- 发布编号使用 `ST-XXXX`，并创建独立 `short_term_tracking` 生命周期。
- 行情 Provider 当前为 Massive，Provider 边界不得写进 Review、Trade 或 Public DTO。
- 每笔 Tracking 固定保存 `price_source` 与 `tracking_policy_version`，同一订单不得混用来源。
- High / Low Watermark、固定 TP1–TP10、Fast Momentum Reversal、Tracking Protection、
  Overnight 与 Tracking Stop 必须幂等落库；Short-Term 不存在 Runner。
- Short-Term 不提供 Active View 或 Daily Summary；Daily Results 只使用 Public DTO。

代码完成不等于 Live Complete；真实期权报价、自动注册、触发卡片和重启恢复必须通过
`docs/development/LIVE_MODE_CHECKLIST.md` 才能解除 Live Gate。

---

# 22. General / Membership / Stripe Lock

## Public Identity

- 对外品牌只有 `AXIS`，Bot 为 `AXIS BOT`，匿名运营人格默认 `VALE`。
- Public Card、DTO、GENERAL 和 Stripe customer-facing copy 统一通过
  `PublicIdentityPolicy`；不得公开 Owner ID、私人联系方式、内部备注或来源。
- Stripe 法定/KYC 要求不得绕过或伪造。

## Membership Products

- 只有一个 `Member` Role，所有有效 Entitlement 获得相同频道权限。
- Free Trial：3 个 XNYS Trading Days、每个 Discord User 终身一次、需版本化风险确认。
- Day Pass：一次性付款、1 个 XNYS Trading Day。
- Monthly：Stripe 月度自动续费，不换算为交易日或固定日历天数。
- Gift、Manual、Manual Extension 与 Stripe Entitlement 可以并存；任一有效即保留 Role。
- Manager Extend 必须创建独立 `MANUAL_EXTENSION`，不得改写原 Entitlement。

## Stripe and Pricing

- `membership_prices` 是展示与收费的唯一价格目录。
- Checkout、Portal 与 Webhook 以 Discord User ID metadata 绑定身份。
- Webhook signature 和 Provider Event ID 幂等是付款 Source of Truth。
- 每次购买保存 pricing version、Stripe Price ID 与 signup amount；新价格不得自动迁移既有
  Monthly Subscription，以保证 Grandfathering。
- Live Mode 前必须完成 Test E2E、公开 HTTPS Webhook、续费/失败/取消 E2E 和人工隐私检查。

## Owner-only Operations

`system-alerts` 与 `card-testing` 只允许 Owner + AXIS BOT。Preview 不能创建正式 Trade、
Analysis、Results 或 Active Order 数据。

---

# 23. SWING / LEAPS Public Entry Plan Lock

本节只升级 SWING / LEAPS 的 ENTRY / STARTER ENTRY 公开视觉；Short-Term 保持独立且不变。

- Discord 发布顺序为确定性结构图在上、中文交易计划卡在下。
- 图只使用真实日 K；取数失败时不生成假 K 线、不臆造点位，文字卡仍可发布。
- 正股计划点位与期权 Premium 分开：Current Stock、Starter、Add Zone、Stock SL、
  Stock PT1 / PT2 / PT3 与 Fib 0.618 不得复用 option entry / option TP / option SL。
- Mentor 明确点位永远优先；AXIS Stock Analyst 只补 Mentor 缺失字段。
- 有可靠价格基准的 SWING / LEAPS ENTRY 至少显示 PT1、PT2：先选真实技术位；仅有一个目标
  时按该目标相对当前价/Starter 基准的 1.272 延展补第二目标；没有目标时必须取得真实日 K
  后才可按 ATR 生成两档目标，取数失败不得凭空生成点位。
- 自动补齐的 PT 必须沿交易方向严格递进；CALL 的 PT2/PT3 必须高于前一目标，PUT 反之。
- 系统 Fib 0.618 只在真实可识别的近期 swing range 上确定性计算；不可靠时隐藏。
- 图采用深黑背景、真实 K 线、白色预测路径、蓝色 Starter、橙色 Add Zone、红色 SL、
  绿色 PT 和低调灰色 0.618。
- 公共卡只显示短交易编号、合约、期权入场价、当前股价、PT、Add Zone、SL、状态和可选逻辑。
- 旧 P-XXXXXXXXXXXX 内部长追踪值不得出现在会员卡；新的公开引用使用短 P-0001 格式。
- 没有数据的可选字段直接隐藏，不显示 N/A。
- Signal Review 直接展示完整会员卡和预测图；Manager 可编辑正股点位与公开逻辑，并用
  「重新生成图片」按修改后的内容刷新图表。
- 「查看当前持仓订单」对 SWING / LEAPS 显示最近持仓成本；无显式均价时使用已发布入场成本。
- ADD / TP / RUNNER / CLOSE 的同风格视觉统一属于后续阶段，本轮不改变其交易逻辑。
