# AXIS Test Status

**日期：** 2026-08-29

**结果：** 50 passed

**Lint：** Ruff passed

**Config validation：** YAML / JSON Schema load passed

**Core Gate A：** PASS

覆盖：

- Discord Blueprint 精确结构、权限、unknown-resource safety 和 rename opt-in。
- Workload Router、Analysis-only override、无效 workload。
- OpenAI Structured Output、图片输入、reasoning effort 和安全错误。
- Source / Attachment / Draft 幂等。
- 默认仓位阶梯和 fourth-add safety。
- 成功/失败 `llm_invocations`。
- Card Review Public DTO、防泄漏、并发和审核条件。
- Publication claim / retry / finalize 幂等和单 Draft 单 Event 约束。
- Entry / Add / Close 状态流转与关闭订单 Active View 排除。
- 三种固定 `查看当前订单` custom_id 和 persistent View。
- Mentor create/edit/toggle/reassign 与审计。
- Membership gift/extend/cancel/remove/manual Role sync/Scheduled expiry。
- 加权 Results 计算、Public DTO 防泄漏和幂等 Message ID。
- Mentor / Member 控制面板固定 persistent custom_id。
- Database metadata、constraints 和 guild seed 幂等。
- 品牌锁与正式 Logo。
- `docs/config-reference/` 与 `config/` byte equality。

Live validation：

- PostgreSQL revision `20260829_0006`。
- 迁移前后 Source=1、Draft=1，数据未丢失。
- Discord final dry-run：`REUSE=26 / CREATE=0 / UPDATE=0 / BLOCK=0`。
- LaunchAgent `com.axis.bot` 已重新部署。
- Bot `manage_roles / send_messages / read_message_history` 权限均为 true。
- Mentor Panel ID `1543434235761791018`，重启前后不变，频道 marker count=1。
- Member Panel ID `1543434237733241001`，重启前后不变，频道 marker count=1。

已知唯一 warning：discord.py 间接依赖 `audioop`，与 AXIS 业务测试无关。
