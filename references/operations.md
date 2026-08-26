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
.\scripts\register_tasks.ps1 -DailyTime "09:15"
```

网页默认地址读取 `config/production_baseline.json`。任务注册器同时建立每日更新和登录后网页服务；任何早于08:30的时间必须被拒绝。

## 手动更新与恢复

```powershell
.\update.ps1
.\update.ps1 -Resume
```

不指定日期时，程序先取网页与SQLite共同确认的最后成功发布日期，再通过iFinD上证指数实际交易日期列出此后全部交易日，按日期升序逐日补至最新上一个完整交易日，不以周一至周五简单代替交易日历。法定休市日自动跳过；若某日失败，任务停止在该日，已成功日期仍保留并发布，下次运行从该日继续。

每个交易日只执行一轮iFinD所有权采集，按5只ETF一批取得基金份额、基金规模和直接净流入，并写入 `data/raw/ifind` 的增量结果文件；收盘价和成交额由轻量日K线接口补充。相同日期重跑时，iFinD采集器跳过已有成功结果，只重试未成功批次。`runtime/missing_sessions_plan.json` 记录本次缺口计划，`runtime/update_status.json` 记录批次总数、已完成数量和当前日期。

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
- `config/app.local.json`
- `config/secrets.local.dpapi`

升级后先执行安装校验和健康检查，再恢复自动任务。
