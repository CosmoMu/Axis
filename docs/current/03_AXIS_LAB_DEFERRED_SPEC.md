# AXIS LAB — Deferred Mentor Model Lifecycle Specification

**状态：** DEFERRED / DO NOT IMPLEMENT NOW  
**开发条件：** Core + Signal + Analysis 全部完成、全部测试通过，并且 Owner 明确要求开始 LAB 后才开发。

> 本文取代旧版 `AXIS_LAB_Mentor_Model_Lifecycle_Spec.md`。

---

# 1. Discord Channels

```text
🧪・AXIS LAB
├─ 🟢・lab-signals
├─ 🧬・mentor-status
└─ 🗂️・lab-history
```

仅 Owner + Bot 可见。

当前可以创建频道，但功能 Flag 必须保持：

```text
FEATURE_LAB_ENABLED=false
FEATURE_MODEL_AB_ENABLED=false
```

`09_OWNER_PERSONAL_MOOMOO_EXECUTION_SPEC.md` 现已授权一个严格隔离的 Owner-only Personal
Execution 例外。它不授权 Model A/B、模型扫描或会员账户连接，也不改变本文其余 Deferred 状态。
`FEATURE_LAB_ENABLED=false` 与 `FEATURE_MODEL_AB_ENABLED=false` 必须继续保持。

---

# 2. 目标

每个 Mentor 拥有独立：

```text
Data Profile
Model A
Model B
Strategy Bundle
Model Version History
Evaluation History
```

Model A 学“选什么”；Model B 学“什么时候进 / 加 / TP / SL / 退出”。

未来数据来源包括：

```text
Trade Data
Trade Events
Analysis Data
Market Snapshots
Candidate Pool Snapshots
Model Predictions
Shadow Predictions
```

---

# 3. Mentor Status

`🧬・mentor-status` 选择 Mentor 后显示：

```text
VINCENT · Mentor Status

Data
Archived Trades       126
Closed Trades         103
Active Trades           7
Analysis Records       286
Market Snapshots      1842

MODEL A
Champion              A v1.4
Training Samples       103
Top-K Accuracy          71%

MODEL B
Champion              B v1.8
Training Samples        97
Win Rate                69%
Profit Factor          2.18
Average Return        +18.7%
Max Drawdown          -14.2%

Strategy Bundle
VIN-S001
A v1.4 + B v1.8

Shadow Bundle
VIN-S002
A v1.5 + B v1.9
Samples 21

[ Generate ]
[ View Shadow ]
[ Version History ]
[ Rollback ]
```

初期数据不足时，不伪造“准确率”。例如 Model A 只有正样本时显示：

```text
Data Status: BASIC LEARNING
Candidate Pool Data: INSUFFICIENT
Selection Validation: NOT AVAILABLE
```

---

# 4. Model Version State

```text
CANDIDATE
SHADOW
CHAMPION
ARCHIVED
```

模型版本生成后 immutable。

```text
A v1.4 -> cannot overwrite
new training -> A v1.5
```

---

# 5. Generate

Generate 永远创建新版本，不覆盖 Champion。

```text
[ Generate ]
-> freeze training data
-> Dataset Snapshot
-> train / derive Candidate A and/or B
-> historical evaluation
-> save metrics
-> Candidate state
-> Champion unchanged
```

Model A / Model B 可以分别 Generate、分别 Promote。

---

# 6. Dataset Snapshot

每次 Generate 必须创建不可变 Snapshot：

```text
DS-VIN-20260829-001
Mentor: Vincent
Trades: 103
Trade Events: 286
Analysis Records: 64
Market Snapshots: 1842
Data Cutoff: 2026-08-29 16:00 ET
```

Model Version 必须绑定 Snapshot ID。

---

# 7. Champion / Challenger

当前正式版本：`Champion`。  
新 Shadow 黑盒版本：`Challenger`。

```text
Market Data
   ├─ Champion -> can publish 🟢・lab-signals
   └─ Challenger -> database only, no Discord signal
```

两套模型看完全相同的市场数据，独立产生预测。

---

# 8. Shadow

新 Candidate 默认先进入 Shadow。

比较至少：

```text
sample_count
win_rate
average_return
profit_factor
max_drawdown
entry_improvement
exit_improvement
chase_rate
correct_skip_rate
```

达到样本阈值后系统只提供建议，不自动 Promote。

---

# 9. Promote / Rollback

Promote 必须 Owner 手动确认。

```text
old Champion -> ARCHIVED
selected Challenger -> CHAMPION
```

允许：

```text
A v1.5 + B v1.8
```

也就是说 A、B 不绑定升级。

Rollback 必须能快速恢复上一稳定 Strategy Bundle，不重新训练。

旧 Model Version 永远不删除。

---

# 10. Strategy Bundle

所有 A + B 组合有独立 Bundle ID：

```text
VIN-S001
Model A: A v1.4
Model B: B v1.8
State: ARCHIVED

VIN-S002
Model A: A v1.5
Model B: B v1.8
State: CHAMPION
```

每个 Lab Signal / Prediction / Trade 保存 Bundle ID。

---

# 11. LAB LLM / Model Routing

LAB 未来也不得依赖一个全局 `LLM_MODEL`。

不同任务可使用不同模型，例如：

```text
LAB_DATA_NORMALIZATION   -> Terra
LAB_STRATEGY_SUMMARY     -> Sol or Terra by configuration
LAB_MODEL_EVALUATION     -> Sol when deeper reasoning is useful
LAB_SIGNAL_EXPLANATION   -> configurable
```

具体模型在真正开发 LAB 时重新评估，不在当前 MVP 锁死。

当前只要求现有 Trade / Analysis 记录保留：

```text
llm_model
llm_workload
prompt_version
schema_version
```

为未来 Dataset / Evaluation 提供可追溯性。

---

# 12. lab-signals

只有 Champion Strategy Bundle 可以发布。

Model A：候选 / 风格匹配。  
Model B：WATCH / ENTRY / ADD / UPDATE / TP1 / TP2 / RUNNER / SL / CLOSE / SKIP / ROLL。

这是 Owner 私人研究频道，不是会员自动交易。

---

# 13. lab-history

保存：

- 已结束 LAB 订单
- 未触发 Entry 的候选
- Skip / Cancel
- 每日收盘总结
- Strategy Bundle / Model A / B version

每天收盘自动：

```text
update Champion outcomes
update Challenger outcomes
update closed P&L
recompute model / bundle metrics
record new data counts
publish Daily Lab Summary
check shadow sample threshold
```

不自动 Promote。

---

# 14. Future Database

真正开发 LAB 时再新增：

```text
dataset_snapshots
model_versions
model_evaluations
model_deployments
strategy_bundles
model_predictions
shadow_predictions
market_snapshots
candidate_pool_snapshots
```

当前 Core / Analysis 只需要保证 Trade / Analysis 数据完整可追溯，不需要提前实现这些模型表。

---

# 15. 四条锁定原则

```text
Generate never overwrites.
New versions default to Shadow.
Champion = production; Challenger = black-box test.
Every Champion must support rollback to a stable prior bundle.
```

LAB 在当前 Codex 任务中不得实现。
