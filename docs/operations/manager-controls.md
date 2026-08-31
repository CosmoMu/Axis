# AXIS Manager Controls

## Mentor Control

`🧭・mentor-control` 的长期面板包含：

- `选择 Mentor`：查看 Active / Historical Trade。
- `新增 Mentor`：填写 Name、Short Code 和可选 Aliases。

选择 Mentor 后的详情页包含：

- `编辑`：改名及修改 Code / Aliases。
- `停用 / 恢复`。
- `修改订单 Mentor`：只修改内部归属，不编辑已发布会员卡片。
- `删除 Mentor`：二次确认后物理删除完全未使用的 Mentor。

删除前会检查 Trade Draft、Trade、Analysis Draft 和 Mentor Analysis。任何关联存在时都会拒绝
删除，提示先重新分配或保留历史；不会把正式 Trade / Analysis 设空或级联删除。成功删除会
保留 `MENTOR_DELETED` Audit，以及删除前的 Name、Short Code、Status 和 Aliases。

面板 Message ID 保存在 `guild_config.mentor_panel_message_id`；Bot 重启先按 ID 复用，
找不到时再按 Footer marker 恢复，因此不会创建重复面板。

## Member Control

`👤・member-control` 的长期面板包含：

- Discord 原生 `User Select`：可按服务器成员用户名或显示名搜索，不需要输入 User ID。

选择成员后显示：

- Discord User mention / ID
- 加入服务器时间
- Member Role 状态
- 会员状态和来源
- Entitlement 数量
- 加入会员时间
- 到期日期或 Lifetime
- 到期时取消状态

详情页操作：

- `查看信息`：重新读取当前 Discord 与数据库状态。
- `赠送会员`：7 / 30 / 90 天或 Lifetime，并同步 Member Role。
- `移除会员`：填写原因后立即撤销有效 Entitlement、处理 Monthly cancellation 并移除 Role。

赠送 Duration 支持 `7`、`30`、`90`、任意 `1..3650` 天，以及 `LIFETIME`。底层延期与到期
取消服务继续用于 Stripe / scheduled lifecycle，但不再是主面板按钮。

赠送和延期写入 Membership Event、Audit Log 及唯一 Scheduled Expiry Job。到期后 Bot
将 Membership 标记为 `EXPIRED` 并移除 Member Role；立即移除不会 Kick 或 Ban 用户。

Owner 在 Discord 手工添加或移除 Member Role 时，Bot 会同步数据库。Bot 自己执行的 Role
变更带有预期标记，不会被误判为 Owner 手工操作。

## Official Results

订单完全关闭后，Bot 从全部 Trade Event 计算：

```text
entry_cost = sum(entry/add price * added units)
exit_value = sum(exit price * sold units)
final_return = (exit_value - entry_cost) / entry_cost
```

结果自动发到 `📊・results`。Footer 使用 Public Trade ID 作为恢复 marker，数据库保存
Result Message ID；Bot 重启或数据库短暂回写失败不会发布第二张结果卡。
