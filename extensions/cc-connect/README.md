# CC-Connect 可选通知

公开版默认不依赖通知，也不会启动任何通知程序。需要飞书或微信日报的用户，必须先明确选择启用，再运行 `configure.ps1 -EnableNotifications`，并由自己的agent安装、登录和配置CC-Connect。

通知扩展的本地入口为 `extensions/cc-connect/notify.ps1`。该文件属于用户本地配置，不随公开仓库提供；由用户的agent按所选渠道创建。未找到该入口时，更新程序只给出提示，不影响网页更新。

通知扩展仅在网页数据校验成功后运行；缺少CC-Connect时不阻断网页发布。
