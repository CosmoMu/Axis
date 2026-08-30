# AXIS Test Status

**日期：** 2026-08-29

**结果：** 69 passed

**Lint：** Ruff passed

**Config validation：** YAML / JSON Schema load passed

**Core Gate A：** PASS

**Analysis Gate B（automated）：** PASS

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
- Signal / Analysis source queue 严格隔离。
- Analysis text / image / multi-image Structured Output 与安全错误码。
- MARKET / TICKER / SECTOR / MACRO、missing data 与禁止臆造价格。
- Analysis Raw / Normalized / Public Snapshot 与 LLM revision trace。
- Archive-only、Archive + Publish、failure / retry / finalize 幂等。
- 同 Mentor / symbol 的新 Source 创建独立 Analysis，旧归档不变。
- Analysis Public DTO 不包含 Mentor、Source、AI、LLM 或 confidence。
- 数据库备份命令不在 argv 暴露密码，Docker context 排除 `.env`。

Live validation：

- PostgreSQL revision `20260829_0007`。
- 迁移前后 Source=1、Draft=1，数据未丢失。
- Analysis 新表初始行数均为 0；Core 数据保持原行数。
- Discord final dry-run：`REUSE=26 / CREATE=0 / UPDATE=0 / BLOCK=0`。
- LaunchAgent `com.axis.bot` 已重新部署。
- Bot `manage_roles / send_messages / read_message_history` 权限均为 true。
- Mentor Panel ID `1543434235761791018`，重启前后不变，频道 marker count=1。
- Member Panel ID `1543434237733241001`，重启前后不变，频道 marker count=1。
- 0007 代码已在 `FEATURE_ANALYSIS_ENABLED=false` 状态部署，LaunchAgent 稳定。
- Analysis live activation 等待 Owner 对 `analysis-input` → OpenAI 数据出口的独立明确授权。

已知唯一 warning：discord.py 间接依赖 `audioop`，与 AXIS 业务测试无关。
