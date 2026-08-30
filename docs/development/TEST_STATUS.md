# AXIS Test Status

**日期：** 2026-08-30

**结果：** 87 passed

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
- Discord Forward snapshot 正文/附件合并、附件 ID 去重与 forwarded-only 输入。
- Discord `.webp` 文件名 / PNG MIME 转换兼容、真实签名归一化与伪装拒绝。
- 被拒绝 Source 的保留审计重试，不删除原始拒绝记录。
- Strict Schema 清洗保留名为 `title` 的业务字段，Required 与 Properties 完全一致。
- MARKET / TICKER / SECTOR / MACRO、missing data 与禁止臆造价格。
- Analysis Raw / Normalized / Public Snapshot 与 LLM revision trace。
- Archive-only、Archive + Publish、failure / retry / finalize 幂等。
- 同 Mentor / symbol 的新 Source 创建独立 Analysis，旧归档不变。
- Analysis Public DTO 不包含 Mentor、Source、AI、LLM 或 confidence。
- 明确 Source 预测路径优先于 Cosmos 生成图；没有预测路径时保存新生成 Cosmos 图。
- 审核/发布 media 使用 checksum 验证，Source Attachment ID 精确绑定，不按 ticker 扫旧图。
- Cosmos-generated Draft rewrite 使用 revision-scoped storage key，可安全替换图片而不覆盖旧文件。
- 数据库备份命令不在 argv 暴露密码，Docker context 排除 `.env`。
- Moomoo option chain 精确合约解析，不手工构造期权代码。
- 交易日/周末判定、三类每日总结、Active/Closed 加权收益与数据库幂等。
- 每日总结 Public DTO 不包含 Mentor、Source、Market、Bid 或 Ask。

Live validation：

- PostgreSQL revision `20260830_0009`。
- 迁移前后 Source=1、Draft=1，数据未丢失。
- Analysis 新表初始行数均为 0；Core 数据保持原行数。
- Discord final dry-run：`REUSE=26 / CREATE=0 / UPDATE=0 / BLOCK=0`。
- LaunchAgent `com.axis.bot` 已重新部署。
- Bot `manage_roles / send_messages / read_message_history` 权限均为 true。
- Mentor Panel ID `1543434235761791018`，重启前后不变，频道 marker count=1。
- Member Panel ID `1543434237733241001`，重启前后不变，频道 marker count=1。
- Owner 已独立授权 `analysis-input` → OpenAI；0007 代码已在
  `FEATURE_ANALYSIS_ENABLED=true` 状态部署，LaunchAgent 稳定。
- 启用后 Discord dry-run：`REUSE=26 / CREATE=0 / UPDATE=0 / BLOCK=0`，修改为 0。
- 第一条真实 Manager Analysis 已保留原 Source 和 Draft ID 完成重试：Source=`PARSED`、
  Draft=`PENDING_REVIEW`、revision=2、最新 `ANALYSIS_REWRITE` invocation 成功；Discord 原审核
  Message ID `1543473587753844822` 原地刷新到 r2，没有重复卡片。
- PostgreSQL Invocation → Draft 显式 Flush 顺序已 live 验证，外键 `23503` 不再复现。
- 修复后的 Analysis Strict Schema 已由 OpenAI 真实最小请求验证通过，模型仍为
  `gpt-5.6-terra`。
- Cosmos AAPL 真实 bridge 验证：数据截至 2026-08-28，生成 73,746-byte 模型路径图；
  Cosmos renderer unit tests PASS。
- Source 路线 no-chart 真实验证：`chart_is_none=True`、Cosmos 新增图片数 `0`。
- 第二条真实 Analysis 已在原 Draft/Review Message 上刷新为 r2，LLM 判定 `chart_source=SOURCE`；
  Discord API 返回同一 footer 且 embed image 为 `cdn.discordapp.com/.../axis-analysis.png`。
- Moomoo SDK / OpenD 均为 `10.10.7008`，`127.0.0.1:11111` quote login 可用。
- SPY 公开测试期权的 option chain 解析与只读盘后 snapshot 均 PASS；未写数据库、未下单。
- 周六 live acceptance 返回 `trading_session=false`，三类频道未误发。
- LaunchAgent `com.axis.moomoo-opend` 已安装，将在下次 macOS 登录加载；当前 OpenD 进程
  已运行并监听本机端口。

已知唯一 warning：discord.py 间接依赖 `audioop`，与 AXIS 业务测试无关。
