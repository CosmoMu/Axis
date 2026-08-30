# AXIS Test Status

**日期：** 2026-08-30

**结果：** 95 passed

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
- 输入图路径与文字有序点位转换成“预测路径（文字）”，LLM 不补数字。
- Analysis 审核和发布不生成或上传图片；Source Attachment ID 只作 provenance。
- Stock Analyst 失败时保留 LLM input 卡片并加入安全 warning。
- Signal `S-00001` / Analysis `A-00001` 分别递增且不在页脚暴露 UUID。
- `why_now`、INPUT / AXIS_STOCK_ANALYST Key Level 与 Point provenance 归档。
- AXIS Stock Analyst 结构位、情景权重、provider injection 与新股有限历史模式。
- AXIS GEX Explorer Gamma/IV fallback、Walls、Zero Gamma 与 regime。
- 数据库备份命令不在 argv 暴露密码，Docker context 排除 `.env`。
- Moomoo option chain 精确合约解析，不手工构造期权代码。
- 交易日/周末判定、三类每日总结、Active/Closed 加权收益与数据库幂等。
- 每日总结 Public DTO 不包含 Mentor、Source、Market、Bid 或 Ask。

Live validation：

- PostgreSQL revision `20260830_0011`。
- 0011 前备份 `/Users/cosmomu/Desktop/Axis/var/backups/axis-20260830T054225Z.dump`
  已通过 `pg_restore --list`，SHA-256 `e320f1a8a6cdde3e116765b01fb7184545c30ce5fc671540766ea644f6892aaf`。
- 迁移后 Signal Draft=2、Analysis Draft=2；编号为 `S-00001..2` / `A-00001..2`，两个
  counter 的 next value 均为 3。
- Discord final dry-run：`REUSE=27 / CREATE=0 / UPDATE=0 / BLOCK=0`。
- LaunchAgent `com.axis.bot` 已重新部署。
- Bot `manage_roles / send_messages / read_message_history` 权限均为 true。
- Mentor Panel ID `1543434235761791018`，重启前后不变，频道 marker count=1。
- Member Panel ID `1543434237733241001`，重启前后不变，频道 marker count=1。
- Owner 已独立授权 `analysis-input` → OpenAI；0007 代码已在
  `FEATURE_ANALYSIS_ENABLED=true` 状态部署，LaunchAgent 稳定。
- `🧪・card-testing` 已创建，ID `1543495201425723442`；Manager/Bot 可发言，Member 不可见。
- 启用后 Discord dry-run：`REUSE=27 / CREATE=0 / UPDATE=0 / BLOCK=0`，修改为 0。
- 第一条真实 Manager Analysis 已保留原 Source 和 Draft ID 完成重试：Source=`PARSED`、
  Draft=`PENDING_REVIEW`、revision=2、最新 `ANALYSIS_REWRITE` invocation 成功；Discord 原审核
  Message ID `1543473587753844822` 原地刷新到 r2，没有重复卡片。
- PostgreSQL Invocation → Draft 显式 Flush 顺序已 live 验证，外键 `23503` 不再复现。
- 修复后的 Analysis Strict Schema 已由 OpenAI 真实最小请求验证通过，模型仍为
  `gpt-5.6-terra`。
- 旧 Cosmos bridge 验证仅作为迁移前记录；0010 后不再调用该 runtime。
- AXIS Stock Analyst 真实 Moomoo 只读验证：NVDA 标准历史模式通过；SPCX 54 个交易日进入
  LIMITED HISTORY。Analysis Pipeline 当前只消费文字 context，不发布 renderer 图片。
- card-review 两条现有消息已原地刷新为 `S-00001` / `S-00002`，附件数均为 0。
- Moomoo SDK / OpenD 均为 `10.10.7008`，`127.0.0.1:11111` quote login 可用。
- SPY 公开测试期权的 option chain 解析与只读盘后 snapshot 均 PASS；未写数据库、未下单。
- 周六 live acceptance 返回 `trading_session=false`，三类频道未误发。
- LaunchAgent `com.axis.moomoo-opend` 已安装，将在下次 macOS 登录加载；当前 OpenD 进程
  已运行并监听本机端口。

已知唯一 warning：discord.py 间接依赖 `audioop`，与 AXIS 业务测试无关。
