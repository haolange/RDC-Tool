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

高级用户可显式设置 RDC_TOOL_ANDROID_ADB_PATH（绝对可执行文件路径）、RDC_TOOL_SPIRV_TOOLS_PATH（绝对目录）；RenderDoc 运行库只从本安装的主机运行目录加载，不接受覆盖。显式路径无效直接报错，不再从 PATH、SDK 或其他 RenderDoc 安装静默补齐。

## 维护者：同源构建与本地验收候选

`scripts/package_runtime.py` 在本主机上组装本主机的运行目录（`--host` 默认且只能是本主机，因为依赖由本主机的捆绑解释器安装）。运行目录由三个独立部分组成，每个输入只替换自己那部分，全部在暂存区组装、校验后整体发布：

- **原生集合**：`--source`（本库内本主机的原生暂存目录）与 `--build-receipt` 必须同时提供；receipt 配对了哪些 Android helper，就必须恰好提供对应的 `--arm32-apk`／`--arm64-apk`。receipt 的结构与校验规则见 [发布基线](release-baseline.md#原生构建回执)：`source` 必须恰好包含 `repository`、`revision`、`base_revision`、`upstream_revision` 与 `tree_sha256`，每个目标的 `inputs_sha256` 等于同一 `source.tree_sha256`。主机角色是 `native_library`／`binding_module`，Android 是 `helper_apk`；本机构建的输出路径相对 receipt 所在目录或为绝对路径，其他主机目标只核对已在运行树中的字节。主机 build 的 `runtime_files` 相对原生暂存目录，覆盖原生库、layer JSON 与 `pymodules/` 全部文件，未列入或发生漂移的输入拒绝打包。新集合完整替换旧原生文件，所有记录统一转换为包内路径。
- **捆绑 Python**：`--python-archive` 必须与 `scripts/python-runtimes.json` 中本主机的 pin（版本、来源 URL、sha256）一致，且解释器在本机实际运行出同一版本。只复制 pin 列出的条目，去掉符号链接别名、缓存、文档及 `test`、`idlelib`、`tkinter`、`ensurepip` 等运行时不用的包；第三方依赖由该解释器自身按 `scripts/runtime-dependencies.lock` 以 `--require-hashes --only-binary=:all: --no-deps` 安装到空的 site-packages，pip 本身不进入运行目录。解释器文件位置由主机布局决定，manifest 的 `bundled_python` 只记录版本、来源与 lock 摘要。
- **主机工具**：`--host-tools` 目录包含主机布局列出的全部工具文件，以及 `bundled_tools.json`（每个工具的 `version`、`source_url`、`source_sha256`、`license`、`license_path`，可附 `build` 等构建信息）。

manifest 列出运行目录内全部有归属的文件；不属于这三部分的文件直接拒绝，既不跳过也不认证。

依赖变化时由维护者重新生成依赖锁（需要访问 PyPI），测试保证 lock 的根依赖与 `pyproject.toml` 一致：

```bash
uv pip compile pyproject.toml --universal --python-version 3.14 --generate-hashes --no-header -o scripts/runtime-dependencies.lock
```

运行环境先在同卷暂存并校验，再整组换入。复制失败、原文件占用或发布失败不会保留旧文件冒充新产物；恢复失败保留原集合并明确报告恢复位置。Python 重建也在暂存集合内进行。打包结果写入全目标共享回执 `binaries/native_build.json`，关联各目标实际文件、APK 版本及 signer 证书指纹、包内原生库 SHA256 和 ELF BuildID；读取证书指纹不代表已执行密码学验签。

尚未提交的维护源码可使用 `scripts/package_release.py --candidate-dir intermediate/<task>/candidate` 创建一个完整的本地验收目录。该入口复用正式包的文件选择、许可证和 SBOM 逻辑，写入明确标注 `local_validation_candidate` 的 `CANDIDATE_MANIFEST.json`，记录基线提交、工作区 diff 摘要及随包源码摘要，不生成正式发行清单。正式 ZIP 的 clean committed source 要求保持不变。候选拒绝覆盖已有目录，也拒绝本主机目标与两个 Android helper 未通过同源 receipt 核验的运行库。

若需对未提交维护源码或独立构建运行库做本地端到端验收，可使用 `package_runtime.py --output-root intermediate/<task>/runtime` 和同一 frozen-source receipt 生成完整候选运行库，再用 `package_release.py --candidate-dir intermediate/<task>/candidate --runtime-root intermediate/<task>/runtime` 生成隔离候选。候选须包含完整配对运行库并通过 native identity 验证；它不更新仓库根 `binaries/`，也不能代替正式发布前同步、验证根运行库。两个目录必须位于本库 `intermediate/` 或 `dist/`，不得逃逸、重叠、reparse 或覆盖既有输出；source 和 receipt 参数仍以当前 Tools 根目录解析。`--runtime-root` 仅用于本地候选。

`scripts/verify_release_package.py --candidate-dir <directory> --metadata-only` 只验证文件和身份；去掉 `--metadata-only` 才额外运行隔离 CLI 检查。此验证与 GPU／Android 回放、模型效果及设备呈现分别验收。候选可通过其同安装入口运行或供 Agent 选择目录，不作为正式 ZIP 安装升级来源。

doctor 的 `renderdoc.native_build` 区分 `verified`、`unavailable` 与 `invalid`，并在 `targets` 中逐目标报告 `verified`／`absent`；本主机所需目标未列出或缺席时给出 `missing_targets`。缺少回执不会被追认为同源证明。`renderdoc.loaded_runtime` 和 worker 状态独立观察实际 Python、已导入绑定及系统加载 DLL；绑定与 DLL 均未加载时报告 `not_loaded`，只有 DLL 已加载时保留其路径并报告 `partial`，任一实际路径不同则报告 `mismatch`。观察到的磁盘哈希与嵌入提交分别记录，磁盘文件哈希不等于进程内存字节或构建源码等价证明。
