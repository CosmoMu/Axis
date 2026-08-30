# AXIS Backup / Restore Runbook

## 创建并验证备份

```bash
.venv/bin/python scripts/backup_database.py
```

备份默认写入 Git 忽略的 `var/backups/`，权限为 `0600`。脚本使用 PostgreSQL custom
format，并立即执行 `pg_restore --list` 与 SHA-256 校验。数据库密码只通过子进程环境传递，
不会进入 argv 或输出。

生产环境应把验证后的备份复制到加密的 off-host storage，并配置保留策略；本机文件不是
完整灾备。

## 恢复前检查

1. 停止 Bot，避免恢复时写入。
2. 保存当前数据库的新备份。
3. 在隔离数据库运行 `pg_restore --list` 并完成恢复演练。
4. 核对目标 Guild ID 与目标数据库。

## 恢复

恢复会清理并覆盖当前数据库对象，必须显式提供两项确认：

```bash
.venv/bin/python scripts/restore_database.py var/backups/<backup>.dump \
  --confirm-guild-id 1543309921066684567 \
  --confirm-restore RESTORE_AXIS_DATABASE
```

恢复完成后依次执行：

```bash
.venv/bin/python scripts/init_database.py
.venv/bin/python scripts/verify_database.py
```

确认 revision、行数与 Panel Message ID 后再启动 Bot。不要在当前生产数据库上为了测试而
执行 restore。
