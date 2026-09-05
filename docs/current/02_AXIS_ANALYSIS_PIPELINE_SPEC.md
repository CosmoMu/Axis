# AXIS — Analysis Fusion Pipeline Specification

**版本：** 2026-09-04 Pilot-style Chart / Concise Card Lock

**状态：** 当前有效 Analysis 规格

本规格定义 Mentor-first、AXIS-fill-missing 的单一最终 Analysis。与旧 Analysis Card、Mentor
Analysis、Stock Analyst、关键点位、指标、Scenario、Prediction Path 或 Chart 设计冲突时，
以本文件为准。

## 2026-09-04 Analysis UX Lock

本节是当前 Analysis 图片、文案与 Review 的最新覆盖规则；与本文后续旧示例冲突时，以本节
为准。

- Prediction Chart 采用 AXIS 自有的 Cosmos Pilot-style 确定性绘图方法：黑色背景、真实日 K、
  HLX 25 / 90 High-Low EMA 通道、蓝色起点、黄色关注区、红色失效线、绿色突破/目标线，以及
  右侧白色结构预测路径。实现代码已复制并收口到 AXIS，不在运行时 import、调用或启动 Cosmos。
- 历史区域只画 Provider 返回的真实 Daily OHLC；白色路径位于最后一根真实 K 线右侧，不画
  未来蜡烛。无需使用独立的有底色预测面板或硬分隔线。
- 所有明确数值严格 Mentor First。导师给出的 Support、Resistance、Key Zone、Breakout、
  Target 与 Invalidation 不得被 AXIS 推导值替换；AXIS 只补缺失角色，并可在导师点位之间生成
  不带新价格标签的结构回踩形状。
- `analysis-review` 在 Mentor 下拉菜单之后固定显示关键点位下拉菜单。Manager 可逐项选择既有
  点位并单独编辑类型、价格、区间上限和简短说明，也可新增或删除点位。经 Manager 编辑的点位
  记为 `MENTOR_INPUT`，保存后立即用同一份最终点位重绘图片。
- Review 与 Public Card 使用简短中文：标题、单句摘要、最多三句条件式核心逻辑、关键点位、
  预测路径与最多两条主要风险。筹码峰、资金分布代理和指标仍保存于后台，但不再默认堆叠在
  Public Card。

## Current Market Intelligence Boundary

- `AXIS Market Intelligence` 是 AXIS 自有分析层，不依赖其他本地仓库运行。
- `AXIS Stock Analyst` 提供只读日 K、EMA / RSI / MACD、结构位、成交分布代理、板块相对
  强度和 Scenario，当前只在单 Ticker Analysis 中补 Mentor 缺失字段。
- `AXIS GEX Explorer` 不属于 Analysis Fusion；其 Owner-only `🧪・card-testing` Phase 1 入口、
  Provider、缓存、热力图和安全门以 `10_GEX_EXPLORER_PHASE1_SPEC.md` 为准。
- Stock Analyst 当前行情适配器只读本机 Moomoo OpenD；失败时保留 LLM 对输入的忠实整理。
- 输入图片只作为内部证据与点位/方向提取来源，绝不直接转发到 Review 或会员频道。若输入
  含明确预测路径，AXIS 使用其中可追溯的点位与方向确定性重绘；否则预测图来自 Final Fused
  `prediction_path`。两者均不使用生成图片模型、不画未来 K 线；失败不阻止文字归档。
- Dealer sign、资金流与筹码峰均是公开假设或代理，Scenario weight 不是胜率。

---

请基于当前 AXIS repo 修改 Analysis Pipeline。

这是一份新的 Analysis Fusion Specification。

如果本消息与之前关于：

Analysis Card
Mentor Analysis
Stock Analyst
关键点位
指标分析
Scenario
Prediction Path
Analysis Chart

的设计冲突，以本消息为准。


==================================================
1. ANALYSIS 的最终目标
==================================================

Analysis 不再把：

Mentor Analysis

和：

AXIS Stock Analyst

分成两套内容并排展示。


最终必须融合成：

ONE FINAL AXIS ANALYSIS


会员端只看到：

AXIS Analysis


不显示：

Mentor Analysis
AXIS Supplement
Mentor Level
System Level
Mentor Indicator
System Indicator


这些来源信息只保存在后台数据库。


==================================================
2. 核心融合原则
==================================================

每一个 Analysis 字段采用：

MENTOR FIRST
AXIS FILL MISSING


规则：

Mentor 有明确内容
→ 优先使用 Mentor


Mentor 没有提供
→ 使用 AXIS Stock Analyst 补充


不要让 Stock Analyst
覆盖 Mentor 已经明确表达的内容。


==================================================
3. 关键点位优先级
==================================================

所有：

Support
Resistance
Watch Level
Breakout Level
Target
Invalidation
Key Zone


优先级统一：

1. Mentor Input
2. AXIS Stock Analyst
3. 无数据则不显示


例如：

Mentor 明确说：

370
400


则最终 Analysis 必须优先使用：

370
400


即使 Stock Analyst 算出：

362.8
382.4
405.2


也不要把这些点位全部塞进公开 Card
造成两套互相冲突的结构。


==================================================
4. Mentor 点位不能被 AXIS 替换
==================================================

Example：

Mentor：

突破 $145
目标 $152


Stock Analyst：

Resistance $144.71
Resistance $145.72
Target $151.95


最终公开 Analysis：

关键突破
$145.00

目标
$152.00


不要偷偷改成：

$145.72
$151.95


Mentor 的明确点位优先。


==================================================
5. AXIS 只补缺失点位
==================================================

Example：

Mentor：

突破 $145
目标 $152


Mentor 没给：

Support
Invalidation


Stock Analyst：

Support $131.18
Secondary Support $125.48


则最终可以变成：

关键支撑
$131.18
$125.48

关键突破
$145.00

目标
$152.00

失效
$131.18


这属于：

AXIS Fill Missing


==================================================
6. 点位来源后台必须保存
==================================================

虽然 Public Card 不显示来源，

数据库必须保存：

level_source


enum：

MENTOR_INPUT

STOCK_ANALYST


例如：

$145
source = MENTOR_INPUT


$131.18
source = STOCK_ANALYST


未来需要能够追溯：

哪个点位来自 Mentor
哪个点位是 AXIS 补充。


==================================================
7. 指标优先级
==================================================

指标同样使用：

Mentor First
AXIS Fill Missing


如果 Mentor 明确提到：

ZCZL
MACD
Volume


则公开指标分析优先展示：

ZCZL
MACD
Volume


不要强行固定展示：

HLX
ZCZL
MACD
RSI
Structure
Money Flow
Sector RS

全部七个指标。


==================================================
8. Mentor 提到的指标优先展示
==================================================

Example Mentor Input：

这里 ZCZL 很漂亮，
MACD 开始重新翻多，
如果量能跟上可能继续走。


最终指标分析：

指标分析

ZCZL
多头结构保持完整

MACD
动能正在重新改善

成交量
量能表现值得继续关注


然后如果需要补充：

Structure
82 / 100

Money Flow Proxy
64 / 100


不要让系统指标盖过 Mentor 的重点。


==================================================
9. Mentor 没提指标时
==================================================

如果 Mentor 完全没有提技术指标，

则使用 AXIS Stock Analyst 输出。


例如：

指标分析

HLX                84
ZCZL               91
MACD               78
RSI14              66
Structure          88
Money Flow Proxy   71
Sector RS          64


只显示：

Stock Analyst 当前真正有意义的指标。


不要为了格式固定
永远输出所有指标。


==================================================
10. 指标来源后台保存
==================================================

数据库保存：

indicator_name

indicator_value

indicator_interpretation

indicator_source


indicator_source：

MENTOR_INPUT

STOCK_ANALYST


Public Card 不显示 source。


==================================================
11. 核心逻辑必须去第一人称
==================================================

公开 Analysis 不允许出现：

我认为
我觉得
我关注
我们认为
Mentor 认为
大哥认为


统一转成：

价格目前……
当前结构……
该区域……
市场表现……
这一结构更倾向于……


==================================================
12. Example
==================================================

原文：

我认为 TSLA 自 101 低点走出了完整 5 浪，
现在 Golden Zone 里横盘，
我觉得后面还有一波。


公开改成：

核心逻辑

TSLA 自前期低点完成一轮完整上行结构后进入横盘整理。

当前价格仍处于主要整理区域内，
结构更接近上涨后的消化阶段。

若关键压力被有效突破，
当前整理有机会重新进入向上扩张。


==================================================
13. 删除观察周期
==================================================

Public Analysis Card 删除：

观察周期


不要显示：

未指定
短线
波段
长期


除非以后我重新要求。


数据库内部仍然可以保留：

time_horizon


但 Public Card 不展示。


==================================================
14. 图片输入处理
==================================================

Manager / Mentor Input 可以包含：

截图
K线图
标注图片
手绘区域
箭头
文字截图


LLM 可以读取图片。


但是 Public Analysis 绝对不能依赖图片才能理解。


禁止公开出现：

图中
如图所示
上图
下图
红线
蓝线
箭头
框内
圈出的区域
图里的 Golden Zone


==================================================
15. 图片信息必须转换成独立文字
==================================================

如果图片中能可靠识别：

Golden Zone = $352 – $360


则公开写：

关键支撑区
$352 – $360


不要写：

图中的 Golden Zone


如果无法可靠提取数字：

不要猜测。


可以使用 Stock Analyst
补充可量化位置。


==================================================
16. Support / Resistance 角色归一化
==================================================

Stock Analyst 输出的关键点位
必须统一成：

SUPPORT

RESISTANCE

PIVOT


不要出现：

支撑区域里写“阻力”

例如：

短期 / 长期支撑

$131.18 · 强度 58 · ZCZL 3 阻力


这是错误的。


如果原本是阻力突破后变成支撑：

可以写：

$131.18 · 强度 58 · ZCZL 3 · 阻力转支撑


==================================================
17. AXIS 结构观察
==================================================

公开 Analysis 可以保留：

AXIS 结构观察


但这里显示的是：

最终融合后的结构


不是：

Mentor Structure

vs

AXIS Structure


推荐：

AXIS 结构观察

关键支撑

$131.18 · 强度 58
$125.48 · 强度 68
$119.70 · 强度 68


关键压力

$145.72 · 强度 82


如果 Mentor 给出明确点位：

优先用 Mentor 数字。


==================================================
18. 点位说明可以保留，但不要暴露来源
==================================================

例如：

$145.00 · 关键突破位置

$152.00 · 上方目标

$131.18 · 主要结构支撑


不要写：

Mentor Level
AXIS Level
Stock Analyst Level


==================================================
19. 筹码峰与资金分布
==================================================

如果 Stock Analyst 有数据，

可以继续展示：

筹码峰与资金分布


例如：

POC
$104.28


70% Value Area
$87.95 – $118.09


资金流向代理
ACCUMULATION · 64/100


签名成交量比
+0.23


==================================================
20. OHLCV 说明简化
==================================================

不要每一张 Card 都放很长技术免责声明。


可以用短版：

OHLCV 资金流为价格与成交量代理，
不代表逐笔主动买卖或真实机构持仓。


如果会让 Card 太长：

放到固定 Analysis Notice 中。


==================================================
21. Scenario Engine 内部仍然计算 2–3 种路径
==================================================

后台 Scenario Engine
仍然可以生成：

Scenario A
Scenario B
Scenario C


例如：

A
多头延续
68%


B
回踩再涨
24%


C
转弱
8%


但是：

Public Card 不同时展示三种路径。


==================================================
22. Public 只展示最高权重路径
==================================================

最终：

只展示：

Top Scenario


例如：

主要预测路径 · 68%


当前
→ 突破 $145
→ 向 $152 扩张


失效
$131.18


不要公开展示：

Scenario 2
Scenario 3


==================================================
23. 预测权重命名
==================================================

不要叫：

真实概率
成功率
胜率
上涨概率


统一：

模型情景权重


标题：

主要预测路径 · 68%


Footer / Risk：

模型情景权重用于表达当前结构下的相对路径，
不代表经过历史校准的真实概率。


==================================================
24. Top Scenario 必须有优势才公开
==================================================

不要因为：

42%
37%
21%


就画一个非常确定的方向预测。


增加：

ScenarioConfidencePolicy


建议第一版：

如果：

Top Scenario Weight < 50%

或者：

Top1 Weight - Top2 Weight < 10%


则：

不生成强方向 Prediction Path。


Public 可以显示：

当前路径不明确


或者：

只展示关键结构位置，
不画明显未来方向线。


==================================================
25. 单一预测路径
==================================================

如果 Top Scenario 达到标准：

只生成一条预测路径。


例如：

Current
$138


Key Breakout
$145


Target
$152


Invalidation
$131.18


Prediction Path：

CURRENT
→ $145
→ $152


同时标记：

Invalidation
$131.18


==================================================
26. Prediction Chart 只画一条路径
==================================================

不要同时画：

Bull
Neutral
Bear

三条线。


只画：

Top Scenario


视觉：

AXIS Black Background

Historical Daily Candles
使用 Stock Analyst 取得的真实日 K OHLC；日 K 占左侧历史区

Current Price
White

Prediction Path
AXIS Green

Target Nodes
Green

Support / Invalidation
Muted Gray

Minimal Text

预测路径必须从最后一根真实日 K 右侧开始；关键支撑、压力、突破、目标和失效位使用水平线
贯穿图表，并标注价格。历史 K 线在最后一个真实交易日结束，右侧只出现白色结构路径；不要求
额外的有底色预测框或硬分隔线。


==================================================
27. 不画未来假 K 线
==================================================

Prediction Chart：

左侧是截至 `market_as_of` 的真实日 K，右侧是结构预测区；不是未来 Candlestick Forecast。


不要生成：

假未来 K 线

假蜡烛走势

AI 预测具体每根 K 线


未来区域只画：

STRUCTURAL PATH


即：

当前点
→ 关键结构点
→ 目标

真实日 K 取数失败时不生成图片，不得用合成 OHLC 或假蜡烛补齐；文字 Analysis 仍可继续审核和
归档。


==================================================
28. Prediction Chart 不使用 Image Generation Model
==================================================

不要让 LLM / Image Model
自由生成走势图。


必须用：

Structured Scenario Data

↓

Deterministic Chart Renderer

↓

PNG


例如：

Matplotlib
SVG Renderer
Canvas Renderer


这样：

Card 数据
和
Prediction Chart

使用同一套价格。


==================================================
29. Prediction Chart 数据结构
==================================================

建议：

prediction_path

current_price

scenario_weight

path_points

invalidation_level


path_points：

type
price
label
sequence


例如：

CURRENT
138.00

BREAKOUT
145.00

TARGET
152.00


Invalidation：

131.18


==================================================
30. Public Analysis Card 最终结构
==================================================

标的观察 · TSLA

TSLA：整理结构中的多头突破观察


当前观点

偏多


核心逻辑

TSLA 在前期上涨后进入横盘整理，
当前结构仍保持在主要支撑上方。

上方 $145.00 是重新打开空间的关键位置。
若能够有效突破并保持，
价格有机会进一步向 $152.00 区域扩张。


AXIS 结构观察

关键支撑

$131.18 · 强度 58
$125.48 · 强度 68


关键压力

$145.00 · 关键突破位置
$152.00 · 上方目标


筹码峰与资金分布

POC
$104.28

70% Value Area
$87.95 – $118.09

资金流向代理
ACCUMULATION · 64/100


指标分析

ZCZL
多头结构保持完整

MACD
动能正在重新改善

Structure
82 / 100

Money Flow Proxy
64 / 100


主要预测路径 · 68%

当前结构
→ 突破 $145.00
→ 向 $152.00 扩张

失效
$131.18


主要风险

• 当前仍处于整理阶段，突破尚未确认。
• 若关键支撑失守，当前结构需要重新评估。
• 模型情景权重用于表达当前结构下的相对路径，并非历史校准后的真实概率。


行情截至
08/30 · 13:36 ET

AXIS Analysis · AN-XXXX


==================================================
31. 删除“依据”
==================================================

Scenario 不再显示：

依据


不要：

70% 多头延续

触发
...

目标
...

失效
...

依据
...


改成：

主要预测路径 · 70%

触发
...

目标
...

失效
...


或者进一步简化成：

当前
→ Breakout
→ Target

失效
...


==================================================
32. Public Section 有数据才显示
==================================================

如果某 Section 无有效数据：

整个 Section 不显示。


不要出现：

观察周期：未指定

Catalyst：无

指标：NULL

目标：N/A

失效：Unknown


保持极简。


==================================================
33. 数据必须保留来源
==================================================

虽然会员只看到融合后的 Final Analysis，

数据库必须能区分：

Raw Mentor Input

Normalized Mentor View

Stock Analyst Output

Final Fused Analysis

Public Card Snapshot


建议至少保留：

raw_source

normalized_mentor_analysis

stock_analyst_snapshot

final_fused_analysis

public_card_snapshot


==================================================
34. Final Analysis Level Provenance
==================================================

每一个 Final Level 保存：

price

role

strength

description

source


source：

MENTOR_INPUT

STOCK_ANALYST


Public 不显示 source。


==================================================
35. Final Analysis Indicator Provenance
==================================================

每一个 Indicator 保存：

indicator_name

value

interpretation

source


source：

MENTOR_INPUT

STOCK_ANALYST


Public 不显示。


==================================================
36. Mentor 数据不能被 Stock Analyst 修改
==================================================

非常重要：

Mentor Input 是 Source of Truth
for explicit Mentor statements.


LLM 可以：

normalize
rewrite
remove first-person
convert image references to standalone text


LLM / Stock Analyst 不允许：

改变 Mentor 明确数字

替换 Mentor 明确目标

重新解释成完全相反观点

偷偷调整 Mentor 的失效位


==================================================
37. Stock Analyst 是补全层
==================================================

Stock Analyst 的职责：

补 Mentor 没提供的：

Support
Resistance
Structure
Money Flow
Sector RS
Indicators
Invalidation
Scenario Features


不是：

覆盖 Mentor。


==================================================
38. 如果 Mentor 与 Stock Analyst 冲突
==================================================

如果 Mentor 明确说：

Support = $130


Stock Analyst 认为：

Support = $125


公开：

优先使用 $130。


后台记录：

conflict_detected = true


可以在 Manager Review 内部显示：

Data Conflict

Mentor Support
$130

Stock Analyst Support
$125


让 Manager 决定是否编辑。


Public Card：

不能同时展示冲突数据
除非 Manager 明确保留。


==================================================
39. Manager Review
==================================================

Analysis Review 需要显示：

FINAL FUSED PREVIEW


Manager 可以编辑最终：

Title
Current View
Core Logic
Support
Resistance
Indicators
Scenario
Invalidation
Risk


Manager 不需要分别编辑：

Mentor Card

AXIS Card


最终只编辑一份：

Final Analysis。


==================================================
40. Manager 内部可以看到来源
==================================================

虽然 Public 不显示，

Analysis Review 可以让 Manager 看：

Mentor

AXIS


例如内部 Level：

$145.00
MENTOR

$131.18
AXIS


这样 Manager 知道哪里来自哪里。


但是：

Publish 后全部去掉来源标签。


==================================================
41. 图片引用测试
==================================================

必须测试：

[ ] 输入图片后 Public 不出现“图中”

[ ] Public 不出现“如图所示”

[ ] Public 不出现“箭头”

[ ] Public 不出现“红线 / 蓝线”

[ ] 图片点位可可靠读取时转换为数字

[ ] 图片点位无法可靠读取时不编造

[ ] Stock Analyst 可以补缺失结构


==================================================
42. 点位优先级测试
==================================================

必须测试：

[ ] Mentor Support 覆盖 Stock Analyst Support

[ ] Mentor Resistance 覆盖 Stock Analyst Resistance

[ ] Mentor Target 覆盖 Stock Analyst Target

[ ] Mentor Invalidation 覆盖 Stock Analyst Invalidation

[ ] Mentor 缺失 Support 时 AXIS 补充

[ ] Mentor 缺失 Target 时 AXIS 补充

[ ] Public 不显示来源标签

[ ] Database 保存来源


==================================================
43. Indicator 优先级测试
==================================================

必须测试：

[ ] Mentor 提 ZCZL → 优先展示 ZCZL

[ ] Mentor 提 MACD → 优先展示 MACD

[ ] Mentor 没提 RSI → AXIS 可补 RSI

[ ] Mentor 没提任何指标 → Stock Analyst 生成指标集合

[ ] Public 不显示 MENTOR / AXIS source

[ ] Internal Review 可以查看 source


==================================================
44. Scenario Tests
==================================================

必须测试：

[ ] 后台可以生成 2–3 Scenario

[ ] Public 只显示 Top Scenario

[ ] Top Scenario Weight 正确

[ ] Top < 50% 时不生成强方向图

[ ] Top1 - Top2 < 10% 时不生成强方向图

[ ] Public 不显示 Scenario 2 / 3

[ ] Prediction Chart 与 Top Scenario 使用同一数据


==================================================
45. Chart Tests
==================================================

必须测试：

[ ] Chart 只有一个 Future Path

[ ] 不生成 Future Candlesticks

[ ] Current Price 正确

[ ] Target Price 正确

[ ] Invalidation 正确

[ ] Mentor 点位优先

[ ] Stock Analyst 只补缺失

[ ] Chart PNG 可以发送 Discord

[ ] Chart Render Failure 不阻止 Analysis Archive

[ ] Chart Render Failure 可以 Retry


==================================================
46. Analysis Card 风格
==================================================

继续 AXIS：

Minimal
Black
White
Signal Green


卡片：

中文为主


保留英文：

Ticker
HLX
ZCZL
MACD
RSI
POC
Value Area
Money Flow Proxy
Sector RS
AXIS


不要过多 Emoji。


==================================================
47. Analysis 最终原则
==================================================

MENTOR PROVIDES THE VIEW

AXIS COMPLETES THE STRUCTURE

LLM FUSES THE CONTENT

MEMBER SEES ONE AXIS ANALYSIS


Mentor 有明确内容：

优先 Mentor。


Mentor 缺失：

AXIS Stock Analyst 补。


最终：

不保留两套分析。


Scenario Engine：

内部可以考虑多种可能。


Public：

只展示最高权重且足够明确的一条路径。


==================================================
48. 本轮完成后
==================================================

完成后：

Run Analysis Regression Tests


确保没有破坏：

Signal
Short-Term
Swing
LEAPS
Membership
Stripe
Results
Mentor
Member Control


然后停止。


不要开始 AXIS LAB。
