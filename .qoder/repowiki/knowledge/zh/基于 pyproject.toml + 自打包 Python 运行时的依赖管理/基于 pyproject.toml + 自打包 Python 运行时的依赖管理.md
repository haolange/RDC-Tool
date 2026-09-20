---
kind: dependency_management
name: 基于 pyproject.toml + 自打包 Python 运行时的依赖管理
category: dependency_management
scope:
    - '**'
source_files:
    - pyproject.toml
    - rdc_tool/runtime_requirements.py
    - scripts/package_runtime.py
    - scripts/package_release.py
    - binaries/windows/x64/manifest.runtime.json
    - binaries/windows/x64/pymodules/renderdoc.pyd
    - binaries/android/arm32/org.renderdoc.renderdoccmd.arm32.apk
    - binaries/android/arm64/org.renderdoc.renderdoccmd.arm64.apk
    - THIRD_PARTY_NOTICES.md
---

## 1. 使用的系统/方法

- **包声明与构建**：项目使用 PEP 621 风格的 `pyproject.toml`（`[project]` 段）声明包名 `rdc-tools`、版本 `1.0.0`、Python 最低版本 `>=3.11`，并通过 `setuptools.build_meta` 作为构建后端。依赖集中在 `[project].dependencies` 中，仅包含运行时依赖：`aiofiles>=23.0`、`jinja2>=3.1`、`numpy>=1.24`、`Pillow>=10.0`、`pydantic>=2.0`；开发依赖通过 `[project.optional-dependencies].dev = ["pytest>=9.0"]` 提供。
- **入口点**：通过 `[project.scripts] rdc-tool = "rdc_tool.cli:main"` 暴露 `rdc` CLI 命令。
- **无 pip 锁文件**：仓库根目录不存在 `requirements.txt`、`poetry.lock`、`Pipfile`、`uv.lock` 等锁定文件；依赖版本以宽松上限（`>=`）在 `pyproject.toml` 中声明。
- **无 vendoring / 私有注册表**：未发现 `vendor/`、`third_party/` 或 `pip.conf`/`pip.ini`/`PYPIRC` 配置；也没有 `GOFLAGS -insecure`、`GOPRIVATE` 等 Go 风格私有源配置。
- **平台二进制与 Python 运行时捆绑**：`binaries/windows/x64/python/` 内嵌完整 CPython 解释器（含 `python.exe`、`python3.dll`、`DLLs/*.pyd`、`Lib/*`），以及 `pymodules/renderdoc.pyd`、`d3dcompiler_47.dll` 等原生模块；Android 端则提供 `org.renderdoc.renderdoccmd.arm32.apk`、`arm64.apk`。这些二进制由脚本生成并受 `manifest.runtime.json` 校验。

## 2. 关键文件

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | 唯一依赖清单（PEP 621）、构建后端、CLI entrypoint、pytest 配置 |
| `rdc_tool/runtime_requirements.py` | 运行时依赖探测与 site-packages 白名单过滤逻辑 |
| `scripts/package_runtime.py` | 将外部 CPython home 与 site-packages 拷贝进 `binaries/windows/x64/python/`，生成 `manifest.runtime.json` |
| `scripts/package_release.py` | 从源码树复制发布工件，生成 `RELEASE_MANIFEST.json`、`LICENSE_INVENTORY.json`、`SBOM.json` 及 zip 包 |
| `binaries/windows/x64/manifest.runtime.json` | 已打包运行时文件的 SHA256 清单（含 python/Lib、DLLs、pymodules 下全部文件） |
| `binaries/windows/x64/pymodules/renderdoc.pyd` | RenderDoc 的 Python 扩展模块（C/C++ 编译产物） |
| `binaries/android/arm32` / `binaries/android/arm64` | Android 平台 APK 二进制 |
| `THIRD_PARTY_NOTICES.md` | 第三方许可证声明（由发布脚本扫描 site-packages 的 `*.dist-info/METADATA` 生成 SBOM） |

## 3. 架构与约定

### 3.1 依赖来源分层

1. **纯 Python 运行时依赖**：由 `pyproject.toml` 声明，安装到用户环境的 site-packages；同时被 `package_runtime.py` 通过 `--site-packages-source`（默认 `.venv/Lib/site-packages`）拷贝进发行包的 `binaries/windows/x64/python/Lib/site-packages`。
2. **平台原生依赖**：RenderDoc 的 `renderdoc.dll`、`dbghelp.dll`、`d3dcompiler_47.dll`、`symsrv.dll` 以及 `pymodules/renderdoc.pyd` 直接以二进制形式提交到 `binaries/windows/x64/`；Android 端以 APK 形式提交。
3. **Python 标准库**：通过捆绑完整 CPython 解释器（`python/Lib`、`DLLs`）解决目标机器缺少 Python 的问题，而非依赖系统 Python。

### 3.2 运行时依赖检查

`rdc_tool/runtime_requirements.py` 维护一份 `REQUIRED_DEPENDENCIES = [(dist_name, import_name), ...]`，并在启动时通过 `importlib.util.find_spec` 检测缺失依赖，返回 `missing_dependencies()` 列表。该模块还定义了 `EXCLUDED_BUNDLED_SITE_PACKAGE_PREFIXES`，用于在打包时排除测试/构建工具（`pytest`、`pip`、`setuptools`、`wheel`、`pluggy`、`iniconfig`、`pygments`、`adodbapi`、`isapi`、`pythonwin`、`rdc_tool-` 等），确保最终发布的 Python 运行时尽可能精简。

### 3.3 打包与签名链

- `package_runtime.py` 遍历允许后缀（`*.dll`、`*.json`、`pymodules/*.pyd`、`*.dll`），跳过 `.pdb/.lib/.exp/.ilk/.h` 等调试符号，生成 `manifest.runtime.json`，记录每个文件的 `path`、`size`、`sha256`。
- `package_release.py` 再基于源码树生成发布包，输出 `RELEASE_MANIFEST.json`（含 `file_count`、`files`、`entrypoints`）、`LICENSE_INVENTORY.json`（逐条列出 site-packages 中每个 dist-info 的 name/version/license/path）和 `SBOM.json`（schema `rdc-tools.sbom.v1`），并对最终 zip 计算 `SHA256SUMS`。
- 发布脚本会拒绝版本不匹配（`args.version != TOOL_VERSION` 返回 2），从而强制版本号与 `__version__` 一致。

### 3.4 版本策略

- 所有依赖使用 `>=` 宽松下限，没有固定上限或锁定文件，因此升级依赖时不会自动产生冲突——但这也意味着可重现性依赖于对 `manifest.runtime.json` 中二进制文件的 SHA256 校验。
- 包自身版本集中定义于 `pyproject.toml` 的 `[project].version`，由 `package_release.py` 通过 `from rdc import __version__ as TOOL_VERSION` 读取并写入发布元数据。

## 4. 约定与约束

- **依赖声明位置**：所有第三方 Python 依赖必须出现在 `pyproject.toml` 的 `[project].dependencies` 中；新增依赖后需同步更新 `rdc_tool/runtime_requirements.py` 的 `REQUIRED_DEPENDENCIES` 列表，否则运行时无法发现。
- **禁止进入发布包的前缀**：`EXCLUDED_BUNDLED_SITE_PACKAGE_PREFIXES` 中的包不会被拷贝进发行包的 site-packages；若某依赖需要进入发布包，应将其前缀从该列表中移除，并确保它不是测试/构建工具。
- **二进制产物受清单约束**：`binaries/windows/x64/` 下的每个文件都应在 `manifest.runtime.json` 中有对应条目；发布流程会遍历该目录生成清单，任何未纳入 allowlist 的文件会被跳过。
- **Python 版本锁定**：通过捆绑特定版本的 CPython（当前为 3.14，见 `python314._pth`、`python314.dll`）保证运行时行为一致；`package_runtime.py` 会探测 `python_home` 的版本并写入 `_pth` 与 manifest。
- **测试环境隔离**：pytest 标记（`unit`、`contract`、`fixture_integration`、`gpu_live`）与 `testpaths = ["tests"]`、`norecursedirs = ["intermediate", "binaries"]` 表明测试不应触发真实 GPU 或渲染捕获，避免引入额外依赖耦合。
- **无全局 pip 配置**：仓库未包含 `setup.cfg`、`requirements.txt`、`pip.conf`、`.env` 等，依赖解析完全依赖 `pyproject.toml` 与调用方环境（`pip install .` 或 `python -m build`）。