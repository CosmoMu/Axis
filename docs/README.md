# AXIS 文档目录

`docs/current/` 是当前唯一产品与技术 Source of Truth。运行时配置的正式文件仍在
`config/`；`docs/config-reference/` 是只读镜像，并由测试保证与运行时配置一致。

```text
docs/
├─ current/                 当前 v2 产品与技术规格
├─ config-reference/        运行时配置的文档镜像
├─ migration/               v1 → v2 审计与实施计划
├─ archive/v1/              旧版规格，只用于历史参考
├─ development/             当前进度、功能、问题与测试状态
└─ operations/              Bootstrap、数据库、会员与生产运行手册
```

更新规则：

- 正式需求变更：更新 `docs/current/`，并同步验收清单与运行时配置。
- Discord / LLM 配置变更：先更新 `config/`，再同步 `docs/config-reference/`。
- 阶段进度：更新 `docs/development/`。
- 运维行为：更新 `docs/operations/`。
- 新想法和临时附件：先放 `manually input/`，吸收后分流并清理。
- 旧规格不删除，只移动到 `docs/archive/v1/` 并标明替代文档。

Secret、生产交易附件、个人信息和带签名 URL 不得写入任何文档目录。
