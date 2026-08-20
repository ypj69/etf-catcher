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

不指定日期时，程序先通过iFinD返回的上证指数实际交易日期确认最新上一个完整交易日，不以周一至周五简单代替交易日历。法定休市日会自动回退；若日历确认失败，任务必须停止并保留上次成功发布结果。仅在诊断或回填并且用户明确指定时才使用 `-TargetDate YYYY-MM-DD`。程序拒绝未来日期和当日日期。

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
