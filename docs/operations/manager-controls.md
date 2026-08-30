# AXIS Manager Controls

## Mentor Control

`🧭・mentor-control` 的长期面板包含：

- `选择 Mentor`：查看 Active / Historical Trade。
- `新增 Mentor`：填写 Name、Short Code 和可选 Aliases。
- `编辑 Mentor`：改名、修改 Code/Aliases、停用或恢复。
- Mentor 详情中的 `修改订单 Mentor`：只修改内部归属，不编辑已发布会员卡片。

面板 Message ID 保存在 `guild_config.mentor_panel_message_id`；Bot 重启先按 ID 复用，
找不到时再按 Footer marker 恢复，因此不会创建重复面板。

## Member Control

`👤・member-control` 的长期面板包含：

- `查找会员`
- `赠送会员`
- `延长会员`
- `到期取消`
- `立即移除`

Duration 支持 `7`、`30`、`90`、任意 `1..3650` 天，以及 `LIFETIME`。Lifetime
会员设置到期取消时需要填写 `YYYY-MM-DD`。

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
