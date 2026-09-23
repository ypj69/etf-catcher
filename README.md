# ETF捕手

ETF捕手是一个本地运行的ETF资金流、市场情绪与宏观数据监控网页。公开版保持ETF捕手1.0的页面布局和交互，每位用户使用自己的iFinD与DeepSeek账户，数据库、配置和运行日志只保存在自己的Windows电脑。

本仓库同时是一个可安装Skill。Codex、Claude Code等agent工具安装仓库后，可以协助完成安装、配置、启动、每日更新、故障诊断和本地研究数据解读。

## 数据口径

- 本地权威历史从2025-01-01开始；网页趋势默认展示2026年以来。
- 每日任务更新的是“最新上一个完整交易日”，不会发布当日盘中未完成数据。
- 首次安装或停机多日后，程序只检查最后成功发布日期之后的真实交易日，按日期顺序补至最新上一个完整交易日；不会在普通每日任务中回扫并重采更早历史。
- 自动更新时间由用户决定，但不得早于08:30。iFinD在08:30以后才视为完成上一交易日数据更新。
- ETF每日仅执行一轮iFinD所有权查询，同时取得网页需要的基金份额、基金规模和直接净流入额。
- 收盘价和成交额优先按明确目标交易日从腾讯历史行情取得，不读取“最新报价”冒充历史日期；仅对缺失代码使用东方财富目标交易日日K线兜底。达到95%覆盖率才进入发布，涨跌幅在本地计算。
- 每次正式更新都会先检查ETF名单维护是否已满7天。新ETF分类置信度高时自动启用，待确认分类保持停用；已有ETF连续3次成功周检都消失后才停用，历史数据不会删除。
- 宏观月频数据只在发布窗口检查缺失月份，已成功月份不重复消耗额度。
- 默认每日入口只执行网页必需的采集、幂等入库、缓存构建和同步校验；量化研究清洗和开发回归测试不进入网页更新链路。通知默认关闭，仅在用户明确启用并配置自己的通知扩展后，于网页更新成功后运行。

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

例如将建议更新时间设为09:15：

```powershell
.\configure.ps1 -DailyTime "09:15"
```

任何早于08:30的时间都会被拒绝。公开版安装和配置不会自动创建Windows定时任务；由用户自己的agent按用户要求建立每日运行安排。agent保存任务时必须写入当前安装目录下 `update.ps1` 的完整绝对路径，并将当前安装目录设为工作目录；不能只保存相对路径、旧版入口或内部下游脚本。创建后应重新读取任务配置，核对绝对入口无误。DeepSeek密钥在交互提示中录入，并使用当前Windows用户的DPAPI加密；不会写入JSON、日志或Git。

如暂不使用DeepSeek：

```powershell
.\configure.ps1 -DailyTime "09:15" -SkipDeepSeek
```

公开版通知默认关闭。只有用户明确要求并完成自己的CC-Connect/消息渠道配置时，才使用 `-EnableNotifications`；未启用时每日任务不会启动任何通知程序，也不会占用相关资源。

## 使用

### 可选：MCP额度耗尽后自动切换原生Python API

每日ETF采集默认先使用iFinD MCP。若明确返回“用户使用工具已超限”“额度已用完”“额度不足”或对应额度耗尽错误，程序会自动切换到用户自己的 **iFinD原生Python数据接口（iFinDPy / THS_BD）**，继续未完成的批次。已成功批次会跳过，日期仍固定为待更新交易日。

这不是Skill里的 `call.py`（它仍然调用MCP）。原生接口需要用户另行具备有效的数据接口账号、指标权限及可用额度；MCP套餐不代表原生接口权益。切换不是绕过额度限制，Python接口也可能因账号权限、额度或数据未发布而失败。

**目前覆盖范围只有ETF基金份额、基金规模、直接净流入额三个字段。** 宏观数据、指数MCP兜底、网页详情及DeepSeek按需查询不包含在此切换中。普通网络超时、429频率限制、未登录等错误不会触发Python切换；两条通道均不可用时会报错保留既有数据，不会填0冒充更新成功。未配置原生接口不影响MCP正常采集，但额度耗尽时会提示先配置。

配置步骤（只需一次）：

1. 先运行 `setup.ps1` 建立项目 `.venv`，并安装、配置自己的iFinD MCP Skill。
2. 按[同花顺官方Windows SDK部署说明](https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/help-center/deploy.html)安装官方SDK。使用超级命令“环境设置”时，选择本项目 `.venv\Scripts\python.exe`，不要只配置全局Python。本仓库不附带商业SDK或共享账户。
3. 仅验证SDK能导入（不会登录取数）：

   ```powershell
   .\.venv\Scripts\python.exe -c "from iFinDPy import THS_BD, THS_iFinDLogin, THS_iFinDLogout; print('SDK import OK')"
   ```

   如果官方SDK没有注册到虚拟环境，也可在运行更新的进程中设置 `IFIND_SDK_DIR` 为包含 `iFinDPy.py` 的官方安装目录；依赖DLL仍需按官方说明正确部署。
4. 在项目目录执行独立配置向导，输入你自己的**数据接口账号和密码**，不是MCP密钥：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\configure-ifind.ps1
   ```

   密码隐藏输入，账号密码整体使用当前Windows用户的DPAPI加密保存到 `config/ifind-native.local.dpapi`，不会写入明文JSON或Git。此向导不登录、不查询、不创建定时任务，也不改动DeepSeek配置。程序解密只在内存中使用；不要把密码发给agent或写进命令历史。
5. 正常执行 `update.ps1` 即可，无需更换每日任务入口。后台任务必须使用完成配置的同一个Windows用户；换电脑或换Windows用户后需重新运行配置向导。

高级用法：可以由你自己的安全凭据管理器向更新进程同时注入 `IFIND_API_USERNAME` 和 `IFIND_API_PASSWORD`，环境变量优先于DPAPI。只设置其中一个会报错，不会混用两套账户。若需要停用此兜底，移除本机 `config/ifind-native.local.dpapi` 并清除这两个环境变量即可。代码升级不会覆盖该加密文件。

诊断记录：`runtime/ifind_collection_route_status.json` 显示实际通道（`ifind_mcp` / `ifind_python_api`）、是否切换、退出码和原因，不包含凭据。SDK缺失、登录失败、原生额度不足时，检查官方SDK环境及账号权益后重新运行 `update.ps1`；结果文件保留成功批次，可继续采集。不同日仍会先尝试MCP，不会永久锁定Python通道。此功能不改变08:30之后更新上一完整交易日的要求，通知仍默认关闭。

### 启动和更新

```powershell
.\start.ps1
.\update.ps1
```

默认网页地址为 `http://127.0.0.1:8766`。ETF详情优先使用Node调用iFinD；当Node不在PATH时自动改用当前Python环境中的iFinD `call.py`，不会再因找不到Node而让详情查询直接失败。

不指定日期运行更新时，程序以网页最后成功发布日期为起点，优先通过腾讯沪深300日K、失败时通过iFinD上证指数取得真实交易日，只处理此后至最新上一个完整交易日的停机缺口，不按普通工作日猜测，也不自动回扫更早历史。已达到95%完整度的日期直接复用；待补日期按顺序执行一轮iFinD所有权采集和轻量行情补充，全部处理结束后只重建一次网页。某日连续三次独立运行仍低于95%时标记为源端缺口并隔离，不填0、不估算，也不再永久阻挡后续日期；网页顶部会披露缺口天数。

程序第一次更新时会从发布基线生成 `data/etf_universe.csv`，此后每位用户的每周名单变更只写入该本地文件和SQLite，不修改Git中的 `config/etf_universe.csv`。因此升级代码不会覆盖用户已维护的ETF名单。名单维护使用公开基金列表，不消耗iFinD额度；源端异常时保留上次成功名单，不阻断当日网页更新。

agent可以通过受控只读工具解读本地数据：

```powershell
.\.venv\Scripts\python.exe .\scripts\agent_query.py status
.\.venv\Scripts\python.exe .\scripts\agent_query.py etf --code 510300 --days 60
.\.venv\Scripts\python.exe .\scripts\agent_query.py group --name "科技（半导体）" --days 60
.\.venv\Scripts\python.exe .\scripts\agent_query.py macro
```

更完整的agent操作约束见 [SKILL.md](SKILL.md)、[本地运行手册](references/operations.md)和[数据口径](references/data-model.md)。

## 隐私与安全

- `config/secrets.local.dpapi`、`config/ifind-native.local.dpapi`、`config/app.local.json`、本地SQLite、网页缓存、日志和运行状态均被Git忽略。
- 后端只使用当前Windows用户的DeepSeek密钥与iFinD Skill，不提供共享账户。
- 健康接口只返回配置状态和数据日期，不返回凭据内容。

## 数据来源与授权

数据来源及再分发风险见 [DATA_NOTICE.md](DATA_NOTICE.md)。种子数据库不进入Git普通提交，而是作为带SHA256和截止日期清单的GitHub Release资产提供。发布者和使用者应确认各数据源许可，尤其是iFinD数据的再分发权限。

## 许可证

代码采用 [MIT License](LICENSE)。数据不因代码许可证而自动获得相同授权。
