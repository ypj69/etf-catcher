# ETF捕手

ETF捕手是一个本地运行的ETF资金流、市场情绪与宏观数据监控网页。公开版保持ETF捕手1.0的页面布局和交互，每位用户使用自己的iFinD与DeepSeek账户，数据库、配置和运行日志只保存在自己的Windows电脑。

本仓库同时是一个可安装Skill。Codex、Claude Code等agent工具安装仓库后，可以协助完成安装、配置、启动、每日更新、故障诊断和本地研究数据解读。

## 数据口径

- 本地权威历史从2025-01-01开始；网页趋势默认展示2026年以来。
- 每日任务更新的是“最新上一个完整交易日”，不会发布当日盘中未完成数据。
- 首次安装或停机多日后，程序会从本地最后成功发布日期开始，按iFinD实际交易日顺序自动补齐至最新上一个完整交易日，不跳过中间日期。
- 自动更新时间由用户决定，但不得早于08:30。iFinD在08:30以后才视为完成上一交易日数据更新。
- ETF每日仅执行一轮iFinD所有权查询，同时取得网页需要的基金份额、基金规模和直接净流入额。
- 收盘价和成交额由东方财富日K线接口轻量补充，涨跌幅在本地计算；份额变化估算继续作为直接净流入的兜底口径。
- 宏观月频数据只在发布窗口检查缺失月份，已成功月份不重复消耗额度。

## 环境要求

- Windows 10/11
- Python 3.11或更高版本
- Node.js
- 用户自己的iFinD MCP/Skill及有效账户
- DeepSeek API账户（可选；不配置时基础网页仍可使用）

## 安装

让agent安装本GitHub仓库为Skill，或者下载仓库后在PowerShell进入项目目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

安装器会创建项目本地 `.venv`，并从当前仓库最新GitHub Release自动下载、校验和导入2025年以来的种子数据。数据库已经存在时不会覆盖。

## 配置

例如将每日任务设为09:15：

```powershell
.\configure.ps1 -DailyTime "09:15"
.\scripts\register_tasks.ps1 -DailyTime "09:15"
```

任何早于08:30的时间都会被拒绝。DeepSeek密钥在交互提示中录入，并使用当前Windows用户的DPAPI加密；不会写入JSON、日志或Git。

如暂不使用DeepSeek：

```powershell
.\configure.ps1 -DailyTime "09:15" -SkipDeepSeek
```

## 使用

```powershell
.\start.ps1
.\update.ps1
```

默认网页地址为 `http://127.0.0.1:8766`。ETF详情优先使用Node调用iFinD；当Node不在PATH时自动改用当前Python环境中的iFinD `call.py`，不会再因找不到Node而让详情查询直接失败。

不指定日期运行更新时，程序通过iFinD返回的上证指数实际交易日期找出本地尚未发布的全部交易日，并按日期升序逐日补齐，不按普通工作日猜测。遇到休市日会自动跳过；某日失败时停止在该日，保留此前成功结果，下次从该日继续。iFinD所有权结果按5只ETF一批落盘，重跑只请求尚未成功的批次；不会再为ETF行情重复执行第二轮iFinD全市场扫描。

agent可以通过受控只读工具解读本地数据：

```powershell
.\.venv\Scripts\python.exe .\scripts\agent_query.py status
.\.venv\Scripts\python.exe .\scripts\agent_query.py etf --code 510300 --days 60
.\.venv\Scripts\python.exe .\scripts\agent_query.py group --name "科技（半导体）" --days 60
.\.venv\Scripts\python.exe .\scripts\agent_query.py macro
```

更完整的agent操作约束见 [SKILL.md](SKILL.md)、[本地运行手册](references/operations.md)和[数据口径](references/data-model.md)。

## 隐私与安全

- `config/secrets.local.dpapi`、`config/app.local.json`、本地SQLite、网页缓存、日志和运行状态均被Git忽略。
- 后端只使用当前Windows用户的DeepSeek密钥与iFinD Skill，不提供共享账户。
- 健康接口只返回配置状态和数据日期，不返回凭据内容。

## 数据来源与授权

数据来源及再分发风险见 [DATA_NOTICE.md](DATA_NOTICE.md)。种子数据库不进入Git普通提交，而是作为带SHA256和截止日期清单的GitHub Release资产提供。发布者和使用者应确认各数据源许可，尤其是iFinD数据的再分发权限。

## 许可证

代码采用 [MIT License](LICENSE)。数据不因代码许可证而自动获得相同授权。
