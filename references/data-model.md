# 数据读取与解读口径

优先通过 `scripts/agent_query.py` 获取受控JSON，不让用户提供任意SQL。

## 可用查询

```powershell
.\.venv\Scripts\python.exe .\scripts\agent_query.py status
.\.venv\Scripts\python.exe .\scripts\agent_query.py etf --code 510300 --days 60
.\.venv\Scripts\python.exe .\scripts\agent_query.py market --days 60
.\.venv\Scripts\python.exe .\scripts\agent_query.py group --name "科技（半导体）" --days 60
.\.venv\Scripts\python.exe .\scripts\agent_query.py macro
```

宏观命令默认只返回最新值、截止日、来源和刷新状态；只有确需逐点复核时才加 `macro --full`，避免把完整载荷塞入agent上下文。

## 核心表

- `etf_master`：ETF代码、名称、交易所、一级/二级分类和跟踪指数。
- `etf_daily`：交易日、收盘价、本地计算涨跌幅、份额、规模、成交额、资金流及来源状态。
- `panel_group_daily`：与网页一致的分类日频汇总，分类问题优先读此表。
- `index_daily`：国内和全球指数历史。
- `macro_payload`：散户资金流、社融与PMI、海外变量的完整网页宏观载荷。

## 解释规则

- `net_flow`是ETF申赎/份额变化口径资金流，不等于交易所成交额。
- `amount`是成交金额；成交活跃不代表净申购。
- 分类结果必须使用记录自身日期，不能把旧日期数值描述成最新交易日。
- 宏观月频数据按官方发布日期更新；日频数据更新到最新上一个完整交易日。
- 空值表示源端缺失或不可比，不填0。
- 回答需标明样本起止日期、最新截止日、单位和数据源；相关性不表述为因果，状态监测不表述为交易信号。
