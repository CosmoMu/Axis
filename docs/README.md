# AXIS 文档目录

docs/current/ 是当前唯一产品与技术 Source of Truth。运行时配置以 config/ 为准；
docs/config-reference/ 是只读镜像，并由测试保证与运行时配置一致。

## 目录结构

- current/ — 当前有效的核心规格和 Codex 入口。
- development/ — 当前状态、功能清单、已知问题、测试结果、下一步、Soft Open Day 1 和 Live 清单。
- operations/ — Bootstrap、数据库、部署、Daily Results Review、会员、Stripe Payment、备份与恢复手册。
- migration/ — v1 → v2 审计和迁移计划；保留实施历史。
- config-reference/ — config/ 的文档镜像。
- archive/v1/ — v1 历史规格。
- archive/superseded/ — 已吸收到当前规格的补充文档。
- archive/development/ — 已完成阶段的开发记录和历史检查表。

## 更新规则

- 正式需求变更：更新 current/，同步验收清单和相关运行时配置。
- Discord / LLM 配置变更：先更新 config/，再同步 config-reference/。
- 代码或部署状态变化：更新 development/。
- 运维行为变化：更新 operations/。
- 新想法和临时附件：先放 manually input/，吸收后分流并清理。
- 旧规格不删除；移动到 archive/，并在文件开头注明归档日期和替代文档。

Secret、生产交易附件、个人信息和带签名 URL 不得写入任何文档目录。
