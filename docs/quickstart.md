# 快速上手

`bin/rdc-tool.cmd`（Windows）与 `bin/rdc-tool`（Linux x86_64、MSYS/Cygwin）按自身位置确定安装根目录，可在任意工作目录运行。

```bat
rdc-tool --version
rdc-tool version --json
rdc-tool --json doctor
rdc-tool tools search pipeline --json
rdc-tool context status --json
rdc-tool capture open --file "C:\path\sample.rdc" --frame-index 0
rdc-tool context status --json
rdc-tool context update --key notes --value "triaged" --json
rdc-tool vfs ls --path / --format tsv
rdc-tool vfs cat --path /context --format json
rdc-tool vfs tree --path /draws --depth 2 --max-nodes 2000 --format json
rdc-tool event list --format tsv
rdc-tool pipeline show --event-id 42 --format json
rdc-tool resource list --format tsv
rdc-tool completion powershell
```

capture 打开后检查 preview：

```bat
rdc-tool session preview on
rdc-tool session preview status
rdc-tool session preview off
```

在 `context status` 的 JSON 输出中查看 `preview.display`，获取 framebuffer、窗口与适配几何。原生 preview 窗口只在 Windows 上提供；在其他主机上 `session preview on` 返回 `preview_unsupported_platform`，需要图像时使用无窗口的 `rd.session.observe`。smoke 结束时执行 `context clear` 与 `daemon stop`。

JSON 是 canonical Agent 协议。TSV 只是 `vfs ls`、`event list`、`resource list` 等列表/导航命令的表格投影；context、管线、shader、导出、像素历史与 preview 等嵌套状态保持 JSON。

需要 Agent 可见的 smoke 时运行 bash 入口，让每条 CLI 命令都显示出来：

```bash
bash scripts/smoke_cli.sh
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```

脚本在执行每条 CLI 命令前先打印它，并把输出同步写入 `intermediate/logs/smoke_cli.log`。不带 `--rdc` 时只做入口 smoke；传入显式 `.rdc` 路径才会运行 daemon capture 链路。仓库内提交的 fixture 只用于仓库测试，不进入发行包。daemon 命令超时时，脚本会打印失败的命令、daemon 状态、已知的 context 状态字段与清理结果。

只做远端的 smoke 同样走 CLI 传输。`rd.capture.open_replay` 把远端句柄绑定到会话后，留意 `remote_handle_consumed`。

任务级用法见 [rdc-tool-native agent playbook](rdc-tool-native-agent-playbook.md)，完整的生成工具清单见 [工具参考](tool-reference.md)。

纹理导出如实反映请求的精度。`file_format` 是唯一的格式参数。显式请求 HDR/EXR/DDS 而编码器无法产出该格式时，直接失败并返回结构化的格式元数据；PNG 是经过显示映射的证据，不能证明保留了 HDR 数据。
