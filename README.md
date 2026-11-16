# RDC-Tool

面向 Agent 与人工使用的 RenderDoc `.rdc` 回放 CLI。

**平台：** 已发布 Windows x64 本地回放与 Android 远端回放。Linux x64 是已支持的主机布局（运行目录 `binaries/linux/x64`，launcher `bin/rdc-tool`），正式产物随下一轮同源构建提供，目前没有发布 Linux 包。原生 preview 窗口只在 Windows 上提供；无窗口观察 `rd.session.observe` 在所有主机可用。**RenderDoc 基线：** 见 [发布基线](docs/release-baseline.md)。

发行包按主机构建，命名为 `rdc-tool-<version>-<host_target>.zip`，目前发布的是 `windows-x64`。从 [Releases](https://github.com/haolange/RDC-Tool/releases) 下载并解压，运行 `install.cmd`，打开新终端后执行：

```bat
rdc-tool --json doctor
```

源码检出需要 Git LFS，并执行 `git lfs pull`。`binaries/` 下的主机运行目录（如 `binaries/windows/x64`）、`binaries/android` 与共享回执 `binaries/native_build.json` 是回放必需的运行库，不是示例；删除它们或只留下 LFS 指针都会导致无法回放。发行包已包含这些文件。

**许可证：** [Apache-2.0](LICENSE)。另见 [安装](docs/install.md)、[稳定性](docs/stability.md) 与 [会话模型](docs/session-model.md)。

## 入口

最新发布版本为 **1.1.2**（Windows x64），包含有界的 Android 冷启动准备与设备状态校验、自包含工具链和源码提交号溯源，详见 [发布说明](docs/release-notes.md)。RDC-Agent 用户在 设置 → Tools 中选择解压出的 `rdc-tool` 目录即可，独立安装和修改 PATH 都是可选的；配对方式见 [Agent 集成](docs/agent-integration.md)。

```bat
rdc-tool --version
rdc-tool version --json
rdc-tool --json doctor
rdc-tool tools list --json
rdc-tool tools describe rd.pipeline.get_state --json
rdc-tool context status --json
rdc-tool capture open --file "C:\path\capture.rdc" --frame-index 0
rdc-tool context update --key notes --value "triaged" --json
rdc-tool vfs ls --path / --format tsv
rdc-tool event list --format tsv
rdc-tool pipeline show --event-id 42 --format json
rdc-tool resource list --format tsv
rdc-tool completion powershell
```

```bash
bash bin/rdc-tool --json doctor
```

`bin/rdc-tool.cmd`（Windows）与 `bin/rdc-tool`（Linux x86_64 运行捆绑的 python3.14；MSYS/Cygwin 运行 Windows 捆绑 Python）都按自身位置确定安装根目录，可在任意工作目录运行。launcher 没有私有 CLI 参数，只把参数原样交给同安装的捆绑 Python 与 `cli/run_cli.py`；缺少捆绑 Python 时直接失败，不回退到系统 Python。

## Smoke

Agent 平台应通过 bash 运行 smoke，让每个 CLI 步骤都显示在终端里：

```bash
bash scripts/smoke_cli.sh
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```

smoke 脚本直接调用 `bin/rdc-tool`，执行 `doctor`、轻量发现，以及传入 `--rdc` 时的 daemon capture 链路。仓库内的小型公开 `.rdc` fixture 只供测试，发行包不含；完整 smoke 需要显式传入本地或远端 capture 路径。脚本默认把日志写到 `intermediate/logs`，隔离运行目录的方式见 [配置](docs/configuration.md)。

## 安装

发行包是按主机构建的自包含 ZIP，自带 Python、RenderDoc 运行库与主机工具。见 [安装](docs/install.md)。

## 会话状态

用 `rdc-tool context status` 读取 context 状态，用 `rdc-tool context update` 更新 notes、focus 等 Agent 可见的元数据。`--daemon-context <id>` 选择持续的运行时命名空间，省略时使用 `default`。多个 daemon context 相互隔离，由调用方选择要操作的 context id。状态包含 `session_locator`、当前 capture/session ID、preview 状态与远端生命周期字段。`remote_handle_consumed` 表示远端句柄已绑定到某个回放会话，不能再当作空闲的远端连接复用。

## Preview CLI 契约

`session preview on|status|off` 经 daemon 调用 `rd.session.open_preview`。`rdc-tool context status` 报告 `rd.session.get_context.preview` 与 `preview.display`；preview 应展示完整 framebuffer，而不是按 viewport / scissor 裁剪。原生 preview 窗口只在 Windows 上提供；其他主机返回结构化错误 `preview_unsupported_platform`，`rd.core.get_capabilities` 报告 `preview_window.available=false`，需要图像时使用无窗口的 `rd.session.observe`。

## 批量只读查询

`rdc-tool --daemon-context case-1 batch queries.jsonl` 在一个客户端进程内按顺序执行预先确定的只读 catalog 操作。JSONL 每行包含 `operation` 与 `args`；每个已尝试的条目输出一个 canonical envelope，带 `meta.batch.index` 与 `operation`。遇到第一个错误即停止，不重试、不跳过，也不自动关闭 daemon。见 [playbook](docs/rdc-tool-native-agent-playbook.md)。

## 文档

- [会话模型](docs/session-model.md)
- [Agent 模型](docs/agent-model.md)
- [安装](docs/install.md)
- [配置](docs/configuration.md)
- [Agent 集成](docs/agent-integration.md)
- [稳定性](docs/stability.md)
- [发布基线](docs/release-baseline.md)
- [架构](ARCHITECTURE.md)
- [文档治理](docs/doc-governance.md)
- [工具](docs/tools.md)
- [工具参考（生成）](docs/tool-reference.md)
- [工具接口历史处置记录](docs/tool-interface-upgrade.md)
- [rdc-tool-native agent playbook](docs/rdc-tool-native-agent-playbook.md)
- [Fixture 策略](docs/fixture-strategy.md)
- [脚本](scripts/README.md)

## RenderDoc 运行库基线

当前基线、来源与升级规则只在 [发布基线](docs/release-baseline.md) 中声明。RDC-Tool 不自动跟随上游每个版本；新运行库完成同源配对打包、catalog 检查、测试与发布门禁后才成为基线。capture 格式兼容性遵循上游 RenderDoc。可用操作由 catalog 定义与 fingerprint 决定，包版本号不授权操作；与 RDC-Agent 的配对契约见 [Agent 集成](docs/agent-integration.md)。本地 PNG 导出不能证明 Android 设备已呈现画面。

## 许可证

`rdc-tool` 以 Apache-2.0 发布。仅用于测试的第三方 fixture 及随包第三方组件的署名见 [第三方声明](THIRD_PARTY_NOTICES.md)。
