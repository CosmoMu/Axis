# AXIS 文档索引

这个目录存放会进入版本控制的产品、开发和运维文档。项目入口仍然是仓库根目录的
`README_FOR_CODEX.md`。

## 当前文档

| 文件 | 用途 | 更新时机 |
|---|---|---|
| `AXIS_MVP_SPEC.md` | MVP 的产品与技术事实来源 | 需求、权限或业务规则发生变化时 |
| `../CODEX_ACCEPTANCE_CHECKLIST.md` | 交付验收清单 | 验收条件发生变化时 |
| `../README_FOR_CODEX.md` | Codex 开发入口和硬性约束 | 开发栈、执行规则或实施顺序变化时 |
| `operations/discord-bootstrap.md` | Discord 只读盘点、dry-run 和安全 apply 手册 | Bootstrap 流程或权限变化时 |
| `operations/database.md` | PostgreSQL、Alembic、初始化与回滚手册 | Schema、迁移或数据库环境变化时 |

## 后续开发文档放置规则

- 产品和技术主规格：继续更新 `docs/AXIS_MVP_SPEC.md`，不要复制出多个“最新版”。
- 阶段开发记录、实施计划：放到 `docs/development/`，文件名使用
  `YYYY-MM-DD-topic.md`。
- 部署、Bootstrap、故障处理说明：放到 `docs/operations/`。
- 重要架构取舍：放到 `docs/decisions/`，文件名使用 `ADR-0001-topic.md`。
- 已废弃但需要保留的文档：放到 `docs/archive/`，并在文件顶部标注废弃日期与替代文档。

文档中引用项目文件时使用仓库相对路径。Secret、真实 Token、数据库密码和带签名的
附件 URL 不得写入任何文档。

## 新资料入口

以后新增的想法、草稿、截图和参考资料可以先放入仓库根目录的 `manually input/`。
Codex 会按该目录内的 README 进行分流、整合和清理；正式内容仍以本页列出的 `docs/`
和 `assets/` 路径为准。
