# AXIS 文档索引

仓库根目录的 `README_FOR_CODEX.md` 是开发入口；`docs/spec/current/` 是当前唯一产品
与技术 Source of Truth。旧版 `docs/AXIS_MVP_SPEC.md` 仅保留历史上下文，不再更新。

## 正式目录

| 路径 | 用途 | 更新时机 |
|---|---|---|
| `spec/current/` | 当前锁定的品牌、Core、Analysis、Deferred LAB 与开发 Gate | 产品范围或核心规则正式变更时 |
| `development/` | 阶段盘点、差异、实现计划和开发记录 | 每个开发阶段开始或完成时 |
| `operations/` | Bootstrap、数据库、运行、部署和故障处理 | 运维流程或实现行为变化时 |
| `decisions/` | 重要架构取舍（ADR） | 存在长期技术权衡时 |
| `archive/` | 已废弃但必须保留的历史文档 | 文档被新规范取代时 |

当前运维文档：

- `operations/discord-bootstrap.md`
- `operations/database.md`
- `operations/signal-input.md`
- `operations/llm-drafts.md`
- `operations/card-review.md`

## 文件命名

- 阶段记录：`docs/development/YYYY-MM-DD-topic.md`
- 架构决策：`docs/decisions/ADR-0001-topic.md`
- 运维手册：使用稳定主题名，不在文件名写 “final” 或 “最新版”
- 废弃文档：文件顶部必须写替代日期和新文档路径

## 新资料和图片放置

- 新想法、临时文档、截图：先放仓库根目录 `manually input/`。
- 正式 Logo / Avatar / Lockup：放 `assets/`。
- 文档截图和流程图：放 `assets/docs/`。
- UI 设计稿：放 `assets/design/`。
- 生产交易附件不进入 Git，继续由 `var/attachments/` 或部署存储管理。

Codex 会读取 `manually input/`，将有效内容并入正式路径；只有在确认信息已完整吸收且
没有唯一内容后，才删除临时副本。Secret、Token、数据库密码、个人信息和带签名 URL
不得写入任何文档或图片目录。
