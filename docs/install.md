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

正式包的 `RELEASE_MANIFEST.json` 与 `SBOM.json` 共同记录 `source_revision`；版本号、源码提交、文件哈希必须一致。正式打包只接受 clean committed checkout 和已验证的仓库根 `binaries/` 原生运行库，并运行源码门禁及整包验证。功能变更须先同步根运行库完整文件集、catalog、文档和 Agent 消费者；隔离 candidate 不替代这些发布输入。Release CI 通过完整 pytest、门禁及打包验证后，只上传已验证 ZIP 与 SHA256 作为 GitHub Actions artifact，不自动发布 GitHub Release。后续获授权的 Release 必须复用同一 ZIP 和校验文件，不重新打包或混拷二进制。安装必须从已验证的正式 ZIP 升级，不向安装目录混拷开发源码或重写发行清单。

升级只移除上一份发行清单拥有、且新清单已不存在的文件；运行数据、用户配置和未声明文件保留。RDC-Agent 继续通过同安装 Python 与 CLI 获取真实版本及 catalog，不能用包版本代替能力检查。

## Source and runtime integrity

Run `git lfs pull` after cloning. Both Windows and Android files under `binaries/` are replay runtime and must remain available. The self-contained release zip includes them; pip-installed RenderDoc is not a replacement. The default installation is `%LOCALAPPDATA%\Programs\rdc-tool`.

Installation doctor rejects an outdated layout. The installer does not discover, copy or silently run a retired installation. Configure RDC-Agent with the new installation's absolute bundled Python path and its `cli/run_cli.py`.

## 自包含主机工具

Windows 包同时携带 Python、RenderDoc 运行库、Android arm32/arm64 helper APK、ADB 36.0.2 及其 DLL、SPIRV-Tools v2026.4 的 spirv-as/spirv-dis。正常运行不要求安装系统 Python、Android SDK、RenderDoc 或 Vulkan SDK。USB/GPU 驱动及设备调试授权属于系统与设备前置条件，不能由工具存在推断已就绪。

主机工具位于 binaries/windows/x64/adb 与 binaries/windows/x64/spirv-tools；版本、上游地址、源归档哈希、构建信息和许可证位置记录于 manifest.runtime.json 的 bundled_tools。文件内容哈希纳入同一 runtime manifest 与发行清单。doctor 分别报告实际来源与捆绑文件完整性；缺少或损坏必需组件会失败，未接设备不会冒充安装损坏。

高级用户可显式设置 RDC_TOOL_ANDROID_ADB_PATH（绝对可执行文件路径）、RDC_TOOL_SPIRV_TOOLS_PATH（绝对目录）；RenderDoc 的已有显式运行库覆盖保持其原契约。显式路径无效直接报错，不再从 PATH、SDK 或其他 RenderDoc 安装静默补齐。

## 维护者：同源构建与本地验收候选

`scripts/package_runtime.py` 替换原生运行库时，必须同时提供 `--source`、`--arm32-apk`、`--arm64-apk` 和 `--build-receipt`。Windows source 是本库内的构建暂存目录；APK 可为绝对构建输出。三目标 receipt 的 `inputs_sha256` 必须等于同一 `source.tree_sha256`，并记录 `base_revision`、`upstream_revision`、配置、工具链和输出角色、大小、SHA256。Windows 角色是 `renderdoc_dll`／`renderdoc_pyd`，Android 是 `helper_apk`；输出输入路径相对 receipt 所在目录或为绝对开发路径。Windows build 还必须有完整的 `runtime_files` 清单，每项记录相对 Windows source 的 `path`、`size` 和 `sha256`，覆盖 DLL、JSON、PYD 和支持库，未列入或发生漂移的输入拒绝打包。新集合完整替换旧原生文件，Python 与主机工具独立保留；所有发布记录统一转换为包内路径，不成为运行依赖。

运行环境先在同卷暂存并校验，再整组换入。复制失败、原文件占用或发布失败不会保留旧文件冒充新产物；恢复失败保留原集合并明确报告恢复位置。Python 重建也在暂存集合内进行。清单的 `native_build` 关联三目标实际文件、APK 版本及 signer 证书指纹、包内原生库 SHA256 和 ELF BuildID；读取证书指纹不代表已执行密码学验签。

尚未提交的维护源码可使用 `scripts/package_release.py --candidate-dir intermediate/<task>/candidate` 创建一个完整的本地验收目录。该入口复用正式包的文件选择、许可证和 SBOM 逻辑，写入明确标注 `local_validation_candidate` 的 `CANDIDATE_MANIFEST.json`，记录基线提交、工作区 diff 摘要及随包源码摘要，不生成正式发行清单。正式 ZIP 的 clean committed source 要求保持不变。候选拒绝覆盖已有目录，也拒绝没有可核验同源三目标 receipt 的运行库。

若需对未提交维护源码或独立构建运行库做本地端到端验收，可使用 `package_runtime.py --output-root intermediate/<task>/runtime` 和同一 frozen-source receipt 生成完整候选运行库，再用 `package_release.py --candidate-dir intermediate/<task>/candidate --runtime-root intermediate/<task>/runtime` 生成隔离候选。候选须包含完整配对运行库并通过 native identity 验证；它不更新仓库根 `binaries/`，也不能代替正式发布前同步、验证根运行库。两个目录必须位于本库 `intermediate/` 或 `dist/`，不得逃逸、重叠、reparse 或覆盖既有输出；source 和 receipt 参数仍以当前 Tools 根目录解析。`--runtime-root` 仅用于本地候选。

`scripts/verify_release_package.py --candidate-dir <directory> --metadata-only` 只验证文件和身份；去掉 `--metadata-only` 才额外运行隔离 CLI 检查。此验证与 GPU／Android 回放、模型效果及设备呈现分别验收。候选可通过其同安装入口运行或供 Agent 选择目录，不作为正式 ZIP 安装升级来源。

doctor 的 `renderdoc.native_build` 区分 `verified`、`unavailable` 与 `invalid`；缺旧构建回执不会被追认为同源证明。`renderdoc.loaded_runtime` 和 worker 状态独立观察实际 Python、已导入绑定及系统加载 DLL；绑定与 DLL 均未加载时报告 `not_loaded`，只有 DLL 已加载时保留其路径并报告 `partial`，任一实际路径不同则报告 `mismatch`。观察到的磁盘哈希与嵌入提交分别记录，磁盘文件哈希不等于进程内存字节或构建源码等价证明。
