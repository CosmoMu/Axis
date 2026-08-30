# AXIS 信号输入操作说明

`📥・signal-input` 是 Manager 提交原始交易信息的唯一入口。当前运行链路完成可靠收件、
附件验证、数据库保存、`SIGNAL_PARSE` 和 `✅・card-review`；仍不会绕过 Manager
审核向会员频道发布卡片。

## 输入与权限

允许服务器 Owner、`.env` 中的 `DISCORD_OWNER_USER_ID` 和 `Manager` Role 提交：

- 纯文字；
- 一张或多张 PNG、JPG/JPEG、WEBP 图片；
- 文字加图片。

单张附件上限由 `MAX_ATTACHMENT_BYTES` 控制，默认 10 MB。附件必须同时通过扩展名、Discord
MIME Type 和文件头验证；可执行文件、未知类型及伪装图片会被拒绝。

## 保存与幂等

每条消息以 `(guild_id, discord_message_id)` 作为数据库唯一键。Discord 重放同一事件时只返回
已有结果，不会重复创建 `source_messages`、`source_attachments` 或 `audit_logs`。

附件使用以下生成式路径保存，不使用用户文件名构造磁盘路径：

```text
var/attachments/<guild_id>/<message_id>/<attachment_id>.<validated-extension>
```

数据库保存 SHA-256、验证后的 MIME、大小和相对存储键。审计记录不包含原始文字、附件内容、
Token、数据库连接或 Discord 附件 URL。

## 环境配置

在本机 `.env` 中配置，不要把真实值提交 Git：

```text
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=1543309921066684567
DISCORD_OWNER_USER_ID=<owner-user-id>
DATABASE_URL=postgresql+asyncpg://axis_user:<password>@localhost:5432/axis
ATTACHMENT_STORAGE_PATH=var/attachments
MAX_ATTACHMENT_BYTES=10485760
```

先执行数据库初始化：

```bash
.venv/bin/python scripts/init_database.py
```

然后启动 Bot：

```bash
.venv/bin/python scripts/run_bot.py
```

macOS 本机开发环境可以安装登录后自动启动的后台服务：

```bash
.venv/bin/python scripts/install_axis_bot_service.py
```

LaunchAgent 名称为 `com.axis.bot`，配置文件位于当前用户的 `Library/LaunchAgents`。为避免
macOS 阻止后台进程读取 Desktop，安装脚本会把仅运行所需的文件部署到
`~/Library/Application Support/AXIS`；运行日志和信号附件也保存在该运行目录的 `var/` 下。
服务配置本身不包含 Token 或数据库连接，运行时仍只从权限为 `0600` 的 `.env` 读取。

## Discord Developer Portal

AXIS BOT 需要以下 Intent：

```text
Guilds
Guild Messages
Message Content
Guild Members
```

其中 `Message Content Intent` 和 `Server Members Intent` 需要在 Discord Developer Portal 的
Bot 页面启用。缺少时运行脚本会安全停止，不会打印 Token。

## 手动验收

1. 用无 `Manager` Role 的账号确认无法看到 `📥・signal-input`。
2. 用 Manager 账号发送纯文字，Bot 应先回复已接收，随后生成结构化 Draft。
3. 发送合法 PNG/JPEG/WEBP，确认数据库有一条来源消息、一条附件记录和一条审计记录。
4. 重放同一 Discord Message ID，确认三张表都没有重复记录。
5. 上传伪装成 PNG 的非图片文件，确认被拒绝且磁盘没有生成附件。
6. 确认 `✅・card-review` 只出现一张对应审核卡片，会员信号频道没有新卡片。

## 当前边界

- 不解析交易字段；
- 不生成 Trade Draft；
- 解析失败时创建安全的 `PARSE_FAILED` Draft，允许 Manager 手动处理；
- 未经确认不发布会员卡片；
- 不启用 AXIS LAB、Model A/B 或 Moomoo。
