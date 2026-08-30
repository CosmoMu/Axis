# AXIS — Codex 验收清单

## Discord 结构

- [ ] Role 顺序为 AXIS BOT → Manager → Member → @everyone。
- [ ] 四个 Category 和十八个 Channel 名称完全匹配 Blueprint。
- [ ] 普通用户看不到会员区、管理区和 AXIS LAB。
- [ ] 会员只能在会员交流发言，三个信号频道只读。
- [ ] 管理员能在信号输入上传文字和图片。
- [ ] AXIS LAB 只有 Owner 和 Bot 可见，三个频道的功能均保持关闭。

## 信号工作流

- [ ] 管理员输入文字后生成 Draft。
- [ ] 管理员输入图片后生成 Draft。
- [ ] LLM 输出通过 JSON Schema 验证。
- [ ] Signal Parse / Repair 通过 workload router 选择实际模型。
- [ ] 每次 LLM 调用记录 provider、model、workload、Prompt/Schema 版本、延迟与结果。
- [ ] Mentor 必须人工选择。
- [ ] 新单和更新单都可以编辑。
- [ ] 确认前不发布。
- [ ] 重复点击确认不会重复发布。
- [ ] 公开卡片不含 Mentor、Source、提交人和内部字段。

## 卡片与仓位

- [ ] 所有卡片使用中文和 `SL`。
- [ ] 不显示 Market、Bid 或 Ask。
- [ ] 入场默认 1/8。
- [ ] 第一次加仓后默认 1/4。
- [ ] 第二次加仓后默认 1/2。
- [ ] 第三次加仓后默认 3/4。
- [ ] 本次加仓、平均成本和加仓后持仓都可编辑。
- [ ] 每张卡片下方都有 `查看当前订单`。

## 查看当前订单

- [ ] Bot 重启后旧卡片按钮仍可点击。
- [ ] 回复仅点击者可见。
- [ ] 只显示合约、最近操作和当前仓位。
- [ ] 无二次展开。
- [ ] 完全关闭或取消的订单不显示。

## 管理

- [ ] Mentor 可新增、改名、停用和恢复。
- [ ] Mentor 可重新分配且不影响会员卡片。
- [ ] 可赠送会员和设置到期时间。
- [ ] 可到期取消或立即移除。
- [ ] 手动 Role 变更会同步数据库。
- [ ] 所有关键写操作有审计记录。

## 安全与部署

- [ ] Token 和 Key 只从 Secret 读取。
- [ ] 日志不输出完整 Secret。
- [ ] Bootstrap 有 dry-run 和幂等保护。
- [ ] 不删除或修改非项目资源。
- [ ] Docker 启动成功。
- [ ] 数据库迁移成功。
- [ ] 自动化测试全部通过。

## Analysis Gate（仅 Gate A 通过后执行）

- [ ] Analysis 与 Signal 使用独立 Domain。
- [ ] 新观点总是创建新的 analysis_id，不覆盖历史观点。
- [ ] 支持仅归档、归档并发布到 🛋️・member-lounge。
- [ ] 不创建 Analysis Thread，公开卡片不泄露 Mentor、Source 或 LLM 信息。
