# 管理员草稿审核

LLM 生成 `trade_drafts` 后，AXIS BOT 会在 `✅・card-review` 发布一张 Manager 专用
审核卡片。卡片是幂等的：Bot 重启时会复用数据库中的 Discord Message ID；如果
发送成功但数据库回写中断，Bot 会根据 Embed Footer 中的 Draft UUID 找回已有消息，
不会重复发卡。

## 操作组件

- `选择 Mentor`：只显示当前有效 Mentor，不使用 LLM 自动分配。
- `选择订单`：只显示当前 `ACTIVE/RUNNER` 订单，用于更新类 Draft。
- `编辑卡片`：编辑操作、合约、价格、SL/TP 和仓位。
- `预览会员卡片`：仅对当前管理员显示，使用 Public DTO 白名单。
- `确认发布`：校验发布条件并将 Draft 设为 `READY`。当前阶段不会发送到会员频道。
- `删除草稿`：需要二次确认，仅软删除为 `DELETED`。

## 编辑表单

Discord Modal 最多支持 5 个输入框，因此使用 `|` 分隔组合字段。空值写为 `-`。

```text
意图 | 操作 | 阶段 | 分类
NEW_TRADE | ENTRY | NONE | SHORT_TERM

Ticker | YYYY-MM-DD | Strike | CALL/PUT
GOOGL | 2026-09-18 | 200 | CALL

入场低 | 入场高 | 操作价 | 平均成本
1.20 | 1.30 | - | -

SL | TP1 | TP2 | 当前收益%
0.80 | 1.60 | 2.00 | -

本次仓位 | 操作后持仓
1 | 1
```

仓位使用八分之一单位，也支持 `1/8`、`1/4`、`1/2`、`3/4` 和 `FULL`。

## 发布前条件

新订单需要 Mentor、人工选择的分类、Ticker、Expiry、Strike、Call/Put、入场价格
或区间以及操作后持仓。更新订单需要 Mentor、已关联订单、操作类型、价格或
明确更新内容以及操作后持仓。

全部平仓、完全触发 SL 或取消订单时，操作后持仓必须为 0。加仓不能降低已有
持仓，减仓不能增加已有持仓。

## 并发和审计

每个按钮和 Modal 都携带 Draft `version`。如果另一位 Manager 已修改卡片，旧版本提交
会被拒绝并刷新。重复点击审核通过不会产生第二条审计或公开卡片。

以下写操作都记录 `actor_user_id`、Discord Interaction ID、修改前和修改后字段：

- Draft 编辑；
- Mentor 选择；
- 订单关联；
- 审核通过；
- 软删除。
