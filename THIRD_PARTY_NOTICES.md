# 第三方声明

本项目以 Apache-2.0 发布。下列第三方内容随仓库或发行包分发，各自遵循其许可证；发行包内的 `SBOM.json` 与 `LICENSE_INVENTORY.json` 逐项列出实际随包的组件。

## RenderDoc 原生运行库

- RenderDoc（MIT），源码 fork `https://github.com/haolange/renderdoc`，当前基线与配对规则见 [docs/release-baseline.md](docs/release-baseline.md)。随包产物：Windows `renderdoc.dll`、`pymodules/renderdoc.pyd` 与 Vulkan layer 清单 `renderdoc.json`，以及 Android arm32/arm64 helper APK；Linux `lib/librenderdoc.so` 与 `pymodules/renderdoc.so` 随下一轮同源构建加入。
- Windows 运行目录中随 RenderDoc 分发的 `d3dcompiler_47.dll`、`dbghelp.dll`、`symsrv.dll` 是 Microsoft 可再发行组件，遵循其各自的 Microsoft 许可。

## 捆绑 Python

- CPython（Python Software Foundation License Version 2）。Windows 使用官方 NuGet `python` 3.14.3 包，其中 `vcruntime140.dll`、`vcruntime140_1.dll` 为 Microsoft Visual C++ 运行库可再发行组件；Linux 使用 python-build-standalone 3.14.6（`install_only_stripped`）。来源、哈希与复制规则见 `scripts/python-runtimes.json`，许可证文本随解释器分发（Windows `python/LICENSE.txt`，Linux `python/lib/python3.14/LICENSE.txt`）。
- 第三方 Python 包按 `scripts/runtime-dependencies.lock` 安装；每个包的版本与许可证由发行包内 `LICENSE_INVENTORY.json` 从其 distribution metadata 生成。

## 随包主机工具

- Android Platform-Tools 36.0.2：Google 官方固定版本，Windows `platform-tools_r36.0.2-win.zip`（分发 ADB、AdbWinApi/AdbWinUsbApi 与原始 NOTICE、source.properties），Linux `platform-tools_r36.0.2-linux.zip`（分发 ADB 与原始 NOTICE、source.properties）。完整上游许可与声明随 `adb/NOTICE.txt` 分发。
- SPIRV-Tools v2026.4 与 SPIRV-Headers（revision `496543121ce6419f23d6fa5d7194ba66c36212d2`）：只构建 `spirv-as` 与 `spirv-dis`，关闭上游测试目标。Windows 为 MSVC x64 Release 静态 CRT 构建（源为官方 tag 归档）；Linux 为 GCC x86-64 Release 构建并静态链接 libstdc++/libgcc（源为 Git 提交 `ef96ed763b43b59b33b31b362f09a02b729fa1c9`）。Apache-2.0 与 Headers MIT 许可分别随 `spirv-tools/LICENSE.txt`、`spirv-tools/SPIRV-Headers-LICENSE.txt` 分发。
- 每个工具的来源、源摘要、版本与构建方式记录在对应主机运行目录 `manifest.runtime.json` 的 `bundled_tools` 中；运行时不依赖下载来源或构建机上的外部安装。

## 测试 capture（不随发行包分发）

- 来源：上游 `rdc-cli` 项目的 `tests/fixtures/vkcube.rdc` 与 `tests/fixtures/vkcube_validation.rdc`，复制到本仓库相同路径。
- 许可证：MIT，Copyright (c) 2024 BANANASJIM；许可证全文见上游 `rdc-cli/LICENSE`。
- 用途：仅用于本仓库的确定性测试与 `fixture_integration` 真实回放测试。
- 发行行为：不随 `rdc-tool` 发行包分发。

- 来源：`tests/fixtures/vkcube_lavapipe.rdc` 是 Khronos Vulkan-Tools 的 `vkcube` 示例（Apache-2.0，Copyright The Khronos Group Inc. 等，见 Vulkan-Tools `LICENSE.txt`）在 Mesa lavapipe 上运行时，由本仓库钉住的 RenderDoc fork 录制的一帧。
- 许可证：录制内容来自 Apache-2.0 的 `vkcube`；RenderDoc 为 MIT。
- 用途与发行行为同上：仅用于测试，不随 `rdc-tool` 发行包分发。
