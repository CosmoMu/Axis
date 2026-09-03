# Signal Review 管理员审核

LLM 生成 `trade_drafts` 后，AXIS BOT 会在 `✅・signal-review` 发布一张 Manager 专用
审核卡片。卡片是幂等的：Bot 重启时会复用数据库中的 Discord Message ID；如果
发送成功但数据库回写中断，Bot 会根据 Embed Footer 中的 Draft UUID 找回已有消息，
不会重复发卡。

Review 主卡片发布后保留在频道并显示终态，不做定时删除。操作产生的 `Only you can see
this` 成功提示会在 4 秒后删除，错误提示在 12 秒后删除；Preview 和确认菜单按各自的
短期 timeout 删除。Ephemeral interaction 不属于频道历史，不能用频道消息扫描清理。

## 操作组件

- `Select Category`：LLM 根据持有周期、到期日和输入语境预选短线、波段或长期；
  Manager 只需在判断不正确时直接用卡片顶部的下拉框修改。
- `Select Mentor`：只用于 LEAPS 与 Legacy Swing；新 Simple Swing 和 Short-Term 不显示。
- `Link Order`：卡片内固定下拉菜单，只显示当前 `ACTIVE/RUNNER` 订单，用于更新类 Draft。
  暂无可选项时下拉框会禁用，不再弹出额外的临时菜单。
- `完整编辑`：LEAPS / Legacy Swing 编辑操作、合约、价格、SL/TP 和仓位；Simple Swing 使用
  精简的合约与 Entry Price 编辑。
- `重新生成图片`：只按当前已编辑的 LEAPS / Legacy Swing 内容重建确定性交易计划图。
- `LOTTO · YES/NO`：三种 Category 都可切换；只影响公开显示，不改变业务逻辑。
- `确认发布`：校验发布条件、预约幂等 Publication，并发送到对应会员频道。
- `删除`：需要二次确认，仅软删除为 `DELETED`。

审核卡片使用紧凑布局，把合约、价格/风控、仓位和审核状态合并显示。Category、Mentor
和关联订单三个下拉框与操作按钮都在同一张 persistent message 上；Bot 重启或草稿更新
时原地刷新，不会额外发送一组控制面板。

操作成功回执会在约 4 秒后自动删除，错误提示约 12 秒后删除，会员预览最多保留 60 秒。
Discord 不允许新的 Interaction 批量删除此前已经发送的 ephemeral 消息，因此升级前残留的
旧提示需要管理员点一次 `Dismiss message`；升级后的操作不会继续堆积。

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

LEAPS 与 Legacy Swing 新订单需要 Mentor、已确认的分类、Ticker、Expiry、Strike、Call/Put、
入场价格或区间以及操作后持仓。更新订单需要 Mentor、已关联订单、操作类型、价格或
明确更新内容以及操作后持仓。

Short-Term 只需要 Category、Ticker、Expiry、Strike、Call/Put 与 Entry Price，不选择
Mentor、不关联订单、不填写仓位。

新 Simple Swing 与 Short-Term 相同，只需要 Category、Ticker、明确 Expiry、Strike、Call/Put 与
Entry Price，并可切换 LOTTO。Close 可用 SW ID 或完整合约匹配 active Simple Swing，必须经过
Review/Publish 才停止追踪；详情见 `trading/SWING_TRACKING.md`。

全部平仓、完全触发 SL 或取消订单时，操作后持仓必须为 0。加仓不能降低已有
持仓，减仓不能增加已有持仓。任何改变仓位的更新都必须填写本次操作价格。

## 并发和审计

每个按钮和 Modal 都携带 Draft `version`。如果另一位 Manager 已修改卡片，旧版本提交
会被拒绝并刷新。重复点击审核通过不会产生第二条审计或公开卡片。

以下写操作都记录 `actor_user_id`、Discord Interaction ID、修改前和修改后字段：

- Draft 编辑；
- Category 修改；
- Mentor 选择；
- 订单关联；
- LOTTO 切换；
- 审核通过；
- 会员发布预约、失败与完成；
- 软删除。

发布后会创建或更新 Trade 并写入唯一 Trade Event。Simple/Legacy Swing 与 LEAPS 卡片附加
persistent `查看当前持仓订单`；Short-Term 不附加按钮。发送后数据库回写中断时，Bot 使用 Public
Footer marker 恢复原消息，不会重复发卡。
