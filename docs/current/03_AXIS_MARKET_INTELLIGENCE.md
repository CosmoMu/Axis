# AXIS Market Intelligence

这是 AXIS 自己拥有的市场分析层，不依赖其他本地仓库运行。

## 固定命名

- `AXIS Market Intelligence`：总模块。
- `AXIS Stock Analyst`：日 K、EMA / RSI / MACD、确认拐点、OHLCV 成交分布、资金流代理、
  板块相对强度、结构位和模型情景；当前已接 Analysis Pipeline 的文字结构观察。
- `AXIS GEX Explorer`：按到期日/行权价聚合 Gamma Exposure，计算 Net GEX、Normalized
  Net GEX、Zero Gamma、Call Wall、Put Wall、Gamma Regime 与触发位；当前只提供引擎，
  默认不建频道、不自动抓取或发布。

代码位置：

```text
app/market_intelligence/stock_analyst/
app/market_intelligence/gex_explorer/
```

## 边界

- 两个引擎不 import、启动或读取 Cosmos 仓库。
- Stock Analyst 当前行情适配器只读本机 Moomoo OpenD 日 K。
- Analysis 当前不调用 Stock Analyst 的图片 renderer；图片发布留待 Massive API 阶段。
- Stock Analyst 不可用时，Analysis 只保留 LLM 对 input 的忠实整理并照常进入审核。
- GEX Explorer 的核心计算不绑定 provider；以后启用频道时再接 Moomoo option chain。
- GEX dealer sign 是公开假设，不声称知道真实 dealer 仓位。
- OHLCV 资金流与筹码峰是代理；模型权重不是胜率。

以后提出“接 Stock Analyst 频道”或“接 GEX Explorer 频道”，均指以上 AXIS 自有模块。
