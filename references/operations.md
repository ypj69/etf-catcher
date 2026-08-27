# 本地运行手册

## 环境与数据边界

- Windows 10/11、Python 3.11或更高版本、Node.js。
- 用户自己的iFinD Skill，目录可由 `IFIND_SKILL_DIR` 指定；默认检查当前用户 `.codex/skills/ifind-finance-data`。
- DeepSeek可选。密钥经 `configure.ps1` 使用Windows DPAPI加密，只能由当前Windows用户解密。
- 权威数据库为 `data/etf_catcher.sqlite3`，历史从2025-01-01开始。生成的 `data/web/*.json` 是可重建网页缓存。

## 首次安装

在Skill根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

安装器创建 `.venv`，从当前GitHub仓库最新Release自动发现并校验种子包。若自动发现失败，可显式传入 `-SeedPath` 或 `-SeedUrl`。数据库已存在时，安装器不得覆盖。

若Python未加入PATH，可传入通用参数：

```powershell
.\setup.ps1 -PythonPath "D:\path\to\python.exe"
```

## 配置账户与时间

```powershell
.\configure.ps1 -DailyTime "09:15"
```

`DailyTime`由用户选择，但不得早于08:30。DeepSeek不是基础网页的强制依赖；不配置时使用 `-SkipDeepSeek`。不得在命令行传入明文DeepSeek密钥，按安全提示交互录入。

## 启动与任务

```powershell
.\start.ps1
```

网页默认地址读取 `config/production_baseline.json`。安装器和配置器不会自行创建Windows定时任务；用户要求自动运行时，由其agent按用户选定时间建立，且必须在08:30或之后。任务动作或Codex自动化提示必须保存当前Skill根目录下 `update.ps1` 的完整绝对路径，并把Skill根目录设为工作目录；禁止使用相对入口、已删除的旧版脚本或 `scripts/` 下的内部单项脚本。建立后必须读回实际配置并核验入口。网页更新口径始终是最新上一个完整交易日。

## 手动更新与恢复

```powershell
.\update.ps1
.\update.ps1 -Resume
```

不指定日期时，程序先取网页与SQLite共同确认的最后成功发布日期，只检查该日之后至最新上一个完整交易日的停机缺口，不回扫更早已发布历史。交易日优先取腾讯沪深300真实日K，腾讯不可用时使用iFinD上证指数实际交易日，不以周一至周五简单猜测。已达到95%完整度的日期直接复用，剩余日期按顺序采集；全部可用缺口处理结束后只发布一次网页。

每个待补交易日只执行一轮iFinD所有权采集，按5只ETF一批取得基金份额、基金规模和直接净流入；收盘价和成交额并发查询腾讯明确目标日的历史行情，只有缺失代码才串行调用东方财富目标日日K线。不得用腾讯最新报价替代历史目标日。回补只填空值，不覆盖已成功观测。低于95%完整度时保留旧网页并在下次运行重试；同一日期连续三次独立运行仍失败时写入 `runtime/backfill_failures.json` 并隔离，网页披露源端缺口但继续更新后续日期。

正式更新入口在缺口检查前运行ETF名单维护。首次运行从 `config/etf_universe.csv` 复制出用户本地的 `data/etf_universe.csv`；后续采集只读取本地名单，代码升级不得覆盖。维护每7天最多执行一次：高置信度新ETF自动启用，低置信度新ETF标为 `needs_review` 且不采集；已有ETF连续3次成功周检缺失才停用，重新出现时恢复。运行结果见 `runtime/etf_universe_maintenance.json`，历史事件见 `runtime/etf_universe_maintenance_history.jsonl`，日志见 `logs/etf_universe_YYYYMMDD.log`。公开源失败或返回规模异常时保留旧名单并继续每日任务。

默认每日更新到同步校验通过即结束，只运行网页必需的数据采集、入库和JSON构建。量化研究清洗层和开发回归测试不属于每日链路。消息通知默认关闭；只有用户明确选择并配置自己的通知渠道后，agent才可启用 `notifications_enabled` 和通知扩展。通知必须位于网页同步校验之后，失败不得把已准确发布的网页标记为失败。

仅在诊断单个日期且用户明确指定时使用 `-TargetDate YYYY-MM-DD`；自动补缺不需要手工逐日运行。程序拒绝未来日期和当日日期。

## 健康检查

- `GET /api/setup/status`
- `GET /api/system/health`
- `runtime/update_status.json`
- `logs/update_YYYYMMDD.log`

健康接口必须披露行情日期、资金流日期、iFinD/DeepSeek状态、最近任务结果、08:30下限和“最新上一个完整交易日”口径，但不得返回凭据内容。

## 升级

更新代码前备份用户数据库和本地配置。代码升级不得覆盖：

- `data/etf_catcher.sqlite3`
- `data/etf_universe.csv`
- `config/app.local.json`
- `config/secrets.local.dpapi`

升级后先执行安装校验和健康检查，再恢复自动任务。
