# Discord Bootstrap 操作说明

目标 Guild：`1543309921066684567`

## 安全边界

- 默认命令只读取 Guild、Role、Category、Channel 和权限覆盖。
- `.env` 中 `APPLY_CHANGES=false`、`DRY_RUN=true` 时不允许写入。
- dry-run 报告写入本地 `var/discord/dry-run.json`；`var/` 不进入 Git。
- 脚本不删除任何资源，默认不自动改名，也不自动移动保存 ID 所指向的频道。
- `--allow-axis-renames` 只能重命名 `discord_ids.json` 已登记的 AXIS Category 与 Channel；
  未提供该参数时，名称差异仍会触发 `BLOCK`。
- 已保存 ID 优先；ID 不存在时才按目标 Category 内的完全同名和资源类型恢复。
- 同名重复、同名异类、目标 Guild 不一致、Bot managed Role 名称不一致时立即停止。
- 长期控制面板在数据库阶段创建；Message ID 入库前不创建面板。

## 首次只读盘点与 dry-run

1. 在 Discord Developer Portal 创建或选择 Bot，并把 Bot 邀请到目标服务器。
2. 只在本机仓库根目录 `.env` 填入 `DISCORD_BOT_TOKEN`。不要把 Token 发到聊天。
3. 保持：

   ```text
   DISCORD_GUILD_ID=1543309921066684567
   APPLY_CHANGES=false
   DRY_RUN=true
   ```

4. 执行：

   ```bash
   .venv/bin/python scripts/bootstrap_discord.py
   ```

5. 检查终端摘要与 `var/discord/dry-run.json`。此命令的服务器修改数必须为 `0`。

## 经人工确认后应用

只有 dry-run 中没有 `BLOCK`，且资源清单由 Owner 确认后，才把 `.env` 改为：

```text
APPLY_CHANGES=true
DRY_RUN=false
```

然后使用目标 Guild ID 二次确认：

```bash
.venv/bin/python scripts/bootstrap_discord.py \
  --apply \
  --confirm-guild-id 1543309921066684567
```

完成后立即把 `.env` 恢复为 `APPLY_CHANGES=false`、`DRY_RUN=true`，并再次运行 dry-run。
重复运行不应出现 `CREATE`；非项目资源不得出现在 `UPDATE` 或 `BLOCK` 的目标中。

## 品牌命名更新

需要更新已登记的 AXIS Category 或 Channel 名称时，先执行：

```bash
.venv/bin/python scripts/bootstrap_discord.py --allow-axis-renames
```

确认计划只包含预期的 `category_name` 与 `channel_name` 后，再临时开启写入锁并执行：

```bash
.venv/bin/python scripts/bootstrap_discord.py \
  --allow-axis-renames \
  --apply \
  --confirm-guild-id 1543309921066684567
```

完成后仍须恢复只读锁，并使用不带重命名参数的普通 dry-run 验证幂等。

## Bot 最小权限

Bootstrap 至少需要 `View Channels`、`Manage Channels`、`Manage Roles`。完整 MVP 还需要
`Send Messages`、`Manage Messages`、`Read Message History`、`Embed Links`、`Attach Files`
和 `Use Application Commands`。Bot 的 managed Role 必须位于 `管理员` 和 `会员` 上方。

管理员 Role 不得拥有服务器级 `Administrator` 或 `Manage Roles`；Bootstrap 会在已匹配的
AXIS `管理员` Role 上移除这两个权限，但不会更改任何非项目 Role。
