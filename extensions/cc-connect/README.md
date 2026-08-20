# CC-Connect 可选通知

公开版默认不依赖通知。需要飞书或微信日报的用户，可在 `config/app.local.json` 将
`notifications_enabled` 设为 `true`，并自行安装、登录CC-Connect。项目不保存会话ID、应用凭据或接收人信息。

通知扩展仅在网页数据校验成功后运行；缺少CC-Connect时不阻断网页发布。
