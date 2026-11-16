# Android 远端 CLI Smoke 提示

本提示用于经 CLI 传输、只走 Android 远端的 smoke。需要了解安装包整体时参考 [../README.md](../README.md)。修改此流程时，按主题检查并更新相关文档：会话生命周期 [session-model.md](session-model.md)，Agent 用法 [agent-model.md](agent-model.md)，故障恢复 [troubleshooting.md](troubleshooting.md)，文档规则 [doc-governance.md](doc-governance.md)，smoke 脚本用法 [../scripts/README.md](../scripts/README.md)。

## 核心序列

```bat
rdc-tool --json doctor
rdc-tool call rd.remote.connect --args-file intermediate\logs\remote_connect_args.json --format json
rdc-tool call rd.remote.ping --args-file intermediate\logs\remote_ping_args.json --format json
rdc-tool call rd.capture.open_file --args-file intermediate\logs\remote_open_file_args.json --format json
rdc-tool call rd.capture.open_replay --args-file intermediate\logs\remote_open_replay_args.json --format json
rdc-tool call rd.session.get_context --format json
```

- 直连 RenderDoc 远端 endpoint 时，connect 参数文件必须含 `host`，可含 `port`。
- Android 经 adb 引导时设置 `options.transport="adb_android"`；`host` 可省略，默认为本机引导 endpoint。可能连着多台 adb 设备时传 `options.device_serial`。发布 smoke 把实际使用的序列号记录在 `intermediate/logs/tool_smoke_findings.md`。
- `rd.capture.open_replay` 始终显式传 `options.remote_id`，使远端回放绝不回退到本地。本机无法本地回放 capture 的 API 时，不带 `remote_id` 的打开会返回 `local_replay_unsupported`。

Android 远端 smoke 改变 preview 行为时运行 `preview_geometry_smoke.py`。原生 preview 窗口只在 Windows 主机提供；其他主机用 `rd.session.observe` 做无窗口观察。

## 嵌入回放验收

1. 调用 `rd.session.get_replay_events`，再以新的绝对 PNG 路径和 `final_output: true` 调用 `rd.session.observe`，然后对一个画面明显不同的事件再观察一次。requested/applied/image 三个 EID、PNG 尺寸与失败诊断独立于设备呈现分别核对。
2. 用完整回放索引中的真实 ID 导航，查询一棵有界的 action 子树，关闭所属回放，再重新打开一次。
3. 复用已建立的远端连接与已确认的传输结果，不重复上传同一 capture。smoke 日志与小尺寸观察图放在 `RDC_TOOL_INTERMEDIATE_ROOT` 下，记录验收结果后删除。

## 设备呈现

配对的原生 client 与 helper 提供 `PresentReplay(event_id, texture_id)`。`remote_display.status=presented` 要求已应用的事件、所选纹理与新的原生完成序号；仅导出 PNG 不能证明已呈现。缺少原生能力报告 `unsupported`；surface 缺失或处于后台、呈现失败报告 `unavailable`。无颜色输出时清空原生 surface，返回 `unavailable`、`reason=no_color_output` 及成功的清空序号。屏幕采样独立验证实际输出的变化与恢复。不要为取得这份证明而停止或替换用户正在运行的 helper。

## 已有服务与 helper 准备

- 兼容的已有服务 smoke：connect 前记录 helper PID 与端口转发，验证 connect、Ping、disconnect、reconnect，然后断言 helper 与原有转发仍然存在。没有 helper 时让正常 connect 启动它；受控 fixture 可以创建一个空闲服务来演练借用。绝不要求用户清理进程或手动启动 RenderDoc Command。应用测试结束后只清理 fixture 自有的资源。
- 原生重建后，配对的原生 client 与 Android 服务是前提。协议不匹配与服务 busy 分开记录；不要盲目重试同一个不兼容的握手。
- 选择设备并调用 `rd.remote.connect` 即授权自动准备目标 helper，无需另行确认：未运行且缺失时用同安装 APK 安装；未运行且 versionCode 不同时保留数据升级或降级；原生握手报告 `remote_version_mismatch` 时，核对身份后停止并覆盖安装不兼容的 helper；覆盖安装遇到签名冲突时卸载重装，这会清除该包的数据（`install_mode=force_replace`、`uninstalled_existing=true`）。保留数据的升级与破坏性重装分别验证。busy 与未知归属的服务从不修复或接管；兼容服务不因 APK 字节不同被替换；正常 disconnect 保留借用的服务。
- 维护自定义原生构建时，回放验收前先构建并验证配对的 Android 组件；普通用户使用自包含的配对运行库。

## 重复观察与空闲

- 重复观察验收必须包含一个有效颜色事件、一个无颜色输出的事件，再回到原来的有效事件。中间结果必须清空图像；最后一次必须重新 readback，且 requested/applied/image 事件 ID 一致。旧 PNG 或被吞掉的 readback 错误都不算验收。
- 在回放导航与重复观察前插入超过五秒的空闲。空闲连接必须仍可用；截断的包仍须在传输 deadline 内失败。验证 close/reopen 使用已核验的设备端副本，而不是再次上传 capture。
