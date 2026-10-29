# Install

`rdc-tool` GA artifacts are self-contained Windows x64 packages. Users should not install Python, create a virtual environment, or run a package manager before using the CLI.

## Install or Upgrade

RDC-Agent users may simply extract the zip and select the contained `rdc-tool` folder in Settings → Tools, then verify and apply. No PATH change or system Python installation is required. Detection uses the existing default installation `%LOCALAPPDATA%\Programs\rdc-tool`.

Extract `rdc-tool-<version>-windows-x64.zip`, then run:

```powershell
./install.cmd -Action install -InstallDir "$env:LOCALAPPDATA\Programs\rdc-tool" -AddToPath
./install.cmd -Action upgrade -InstallDir "$env:LOCALAPPDATA\Programs\rdc-tool" -AddToPath
```

Use `-DryRun` to inspect the file and PATH actions first.

## Doctor

```powershell
./install.cmd -Action doctor -InstallDir "$env:LOCALAPPDATA\Programs\rdc-tool"
rdc-tool --json doctor
```

## Uninstall

```powershell
./install.cmd -Action uninstall -InstallDir "$env:LOCALAPPDATA\Programs\rdc-tool"
```

The install script only copies `rdc-tool`, updates the user PATH when requested, and refuses to remove a directory that does not contain `bin/rdc-tool.cmd`.


## Windows entrypoints and host binding

Double-click `install.cmd` to install and add this installation's `bin` directory to the user PATH. `install.cmd` accepts the installer parameters above; it never runs CLI operations. CLI users run `rdc-tool` through thin `bin/rdc-tool.cmd`, which selects the adjacent bundled Python, forwards standard streams/arguments and preserves the exit code. Missing bundled Python fails without system-Python fallback. Unix `bin/rdc-tool` is unchanged.

Upgrade removes only this installation's former root PATH entry and two replaced launcher files; unrelated installations, PATH entries and shortcuts are untouched. No old-name forwarding files remain. Installer PowerShell is confined to installation/upgrade/uninstall/doctor, never the CLI hot path.

RDC-Agent command must be the absolute `<installation>/binaries/windows/x64/python/python.exe`, paired with that installation's `cli/run_cli.py` as its sole argument prefix. Shell wrappers and cross-installation pairs are rejected. Saved invalid settings remain visible for manual correction; they do not silently migrate.

## Release identity and upgrades

正式包的 `RELEASE_MANIFEST.json` 与 `SBOM.json` 共同记录 `source_revision`；版本号、源码提交、文件哈希必须一致。打包只接受 clean Git checkout，发行门禁再次核对当前 HEAD 和完整源文件清单。安装必须从已验证的正式 ZIP 升级，不向安装目录混拷开发源码或重写发行清单。

升级只移除上一份发行清单拥有、且新清单已不存在的文件；运行数据、用户配置和未声明文件保留。RDC-Agent 继续通过同安装 Python 与 CLI 获取真实版本及 catalog，不能用包版本代替能力检查。

## Source and runtime integrity

Run `git lfs pull` after cloning. Both Windows and Android files under `binaries/` are replay runtime and must remain available. The self-contained release zip includes them; pip-installed RenderDoc is not a replacement. The default installation is `%LOCALAPPDATA%\Programs\rdc-tool`.

Installation doctor rejects an outdated layout. The installer does not discover, copy or silently run a retired installation. Configure RDC-Agent with the new installation's absolute bundled Python path and its `cli/run_cli.py`.

## 自包含主机工具

Windows 包同时携带 Python、RenderDoc 运行库、Android arm32/arm64 helper APK、ADB 36.0.2 及其 DLL、SPIRV-Tools v2026.4 的 spirv-as/spirv-dis。正常运行不要求安装系统 Python、Android SDK、RenderDoc 或 Vulkan SDK。USB/GPU 驱动及设备调试授权属于系统与设备前置条件，不能由工具存在推断已就绪。

主机工具位于 binaries/windows/x64/adb 与 binaries/windows/x64/spirv-tools；版本、上游地址、源归档哈希、构建信息和许可证位置记录于 manifest.runtime.json 的 bundled_tools。文件内容哈希纳入同一 runtime manifest 与发行清单。doctor 分别报告实际来源与捆绑文件完整性；缺少或损坏必需组件会失败，未接设备不会冒充安装损坏。

高级用户可显式设置 RDC_TOOL_ANDROID_ADB_PATH（绝对可执行文件路径）、RDC_TOOL_SPIRV_TOOLS_PATH（绝对目录）；RenderDoc 的已有显式运行库覆盖保持其原契约。显式路径无效直接报错，不再从 PATH、SDK 或其他 RenderDoc 安装静默补齐。
