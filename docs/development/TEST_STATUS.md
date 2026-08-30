# AXIS Test Status

**日期：** 2026-08-29  
**结果：** 42 passed  
**Lint：** Ruff passed  
**Config validation：** YAML / JSON Schema load passed

覆盖：

- Discord Blueprint 精确结构、权限、unknown-resource safety 和 rename opt-in。
- Workload Router、Analysis-only override、无效 workload。
- OpenAI Structured Output、图片输入、reasoning effort 和安全错误。
- Source / Attachment / Draft 幂等。
- 默认仓位阶梯和 fourth-add safety。
- 成功/失败 `llm_invocations`。
- Card Review Public DTO、防泄漏、并发和审核条件。
- Database metadata、constraints 和 guild seed 幂等。
- 品牌锁与正式 Logo。
- `docs/config-reference/` 与 `config/` byte equality。

Live validation：

- PostgreSQL revision `20260829_0004`。
- 迁移前后 Source=1、Draft=1，数据未丢失。
- Discord final dry-run：`REUSE=26 / CREATE=0 / UPDATE=0 / BLOCK=0`。
- LaunchAgent `com.axis.bot` 已重新部署。

已知唯一 warning：discord.py 间接依赖 `audioop`，与 AXIS 业务测试无关。
