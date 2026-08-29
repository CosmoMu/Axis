# AXIS — Codex 开发入口

本目录是 AXIS 收费 Discord 的初版开发规格。请先完整阅读：

1. `docs/AXIS_MVP_SPEC.md`
2. `config/discord_blueprint.yaml`
3. `config/llm_trade_schema.json`
4. `config/.env.example`

## Codex 执行要求

请以 **Python 3.12 + discord.py 2.x + PostgreSQL + SQLAlchemy 2 + Alembic** 实现。

### 必须遵守

- 主品牌、Discord Server 名称和所有面向用户的品牌文案统一使用 `AXIS`；私人模型模块
  保持 `AXIS LAB`，Bot 保持 `AXIS BOT`，不增加正式中文品牌名。
- Discord Category 与 Channel 名称使用英文 + Emoji；卡片、频道说明和用户交互使用中文；
  代码、枚举、数据库字段使用英文。
- 不得把 Bot Token、LLM Key、数据库密码或任何 Secret 写入源码、日志、测试快照或提交记录。
- 只允许从环境变量或 Secret Manager 读取 Secret。
- 首次连接 Discord 后，先执行只读盘点与 `dry-run`，输出将创建或复用的 Role、Category、Channel 和权限差异。
- 未显式启用 `APPLY_CHANGES=true` 前，不得修改服务器。
- Bootstrap 必须幂等：重复运行不得创建重复频道、重复 Role 或重复面板消息。
- 不得自动删除、重命名或移动任何不属于本项目的现有频道和 Role。
- 所有公开会员卡片必须经过管理员确认；LLM 不允许直接发布。
- 公开卡片只能使用 Public DTO 白名单，不得包含 Mentor、提交人、来源消息、原图、解析置信度或内部备注。
- 会员没有自动交易功能。Moomoo 和 Model A/B 在首版仅保留接口与 Feature Flag，不实现会员交易。
- `查看当前订单` 必须使用长期有效按钮；Bot 重启后仍可点击。
- 所有管理员写操作必须记录审计日志。

## 推荐实施顺序

1. 创建项目结构、配置读取、数据库和迁移。
2. 实现 Discord 只读盘点与幂等 Bootstrap。
3. 创建 Role、Category、Channel 和权限覆盖。
4. 实现交易领域模型、仓位规则和卡片生成器。
5. 实现 `信号输入 → LLM 草稿 → 卡片审核 → 确认发布`。
6. 实现每张卡片下方的 `查看当前订单`。
7. 实现导师管理和会员管理。
8. 实现官方战绩与定时任务。
9. 添加测试、Docker、日志和部署说明。
10. 最后只创建 AXIS LAB 的两个频道和接口占位，默认禁用。

## 交付前必须输出

- 项目目录树。
- 所有环境变量说明。
- Discord 所需权限和 Intent 清单。
- Bootstrap dry-run 结果。
- 数据库迁移文件。
- 自动化测试结果。
- 手动验收步骤。
- 已知限制和下一阶段建议。
