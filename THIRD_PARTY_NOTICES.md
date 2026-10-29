# Third-Party Notices

This project is licensed under Apache-2.0. The following test-only assets are included under their upstream license and are not shipped in the release package.

## rdc-cli test captures

- Source repository: `D:\Projects\Native\rdc-tool-third\rdc-cli`
- Source paths: `tests/fixtures/hello_triangle.rdc`, `tests/fixtures/vkcube.rdc`, `tests/fixtures/vkcube_validation.rdc`
- Destination paths: `tests/fixtures/hello_triangle.rdc`, `tests/fixtures/vkcube.rdc`, `tests/fixtures/vkcube_validation.rdc`
- License: MIT
- Copyright: Copyright (c) 2024 BANANASJIM
- Use in this repository: deterministic repository tests only
- Release behavior: excluded from `rdc-tool` release packages

MIT License text for these assets is available in the upstream `rdc-cli/LICENSE` file.

## 随包主机工具

- Android Platform-Tools 36.0.2：Google 官方固定版本 https://dl.google.com/android/repository/platform-tools_r36.0.2-win.zip；仅分发 ADB、AdbWinApi/AdbWinUsbApi 和原始 NOTICE/source.properties。完整上游许可与声明随 binaries/windows/x64/adb/NOTICE.txt 分发。
- SPIRV-Tools v2026.4：KhronosGroup/SPIRV-Tools 官方 tag 源归档；SPIRV-Headers revision 496543121ce6419f23d6fa5d7194ba66c36212d2。MSVC x64 Release 静态 CRT 构建 spirv-as/spirv-dis，FORCED_BUILD_VERSION_DESCRIPTION=v2026.4，关闭上游测试目标；运行产品回归与真实汇编/反汇编验证。Apache-2.0 与 Headers MIT 许可分别随 binaries/windows/x64/spirv-tools/LICENSE.txt、SPIRV-Headers-LICENSE.txt 分发。
- 源归档及分发文件 SHA256、版本与构建方式以 binaries/windows/x64/manifest.runtime.json 为准；SBOM 与 LICENSE_INVENTORY 从相同元数据生成。运行时不依赖下载来源或构建机的外部安装。
