---
kind: build_system
name: RDC 工具集构建、打包与发布门禁体系
category: build_system
scope:
    - '**'
source_files:
    - pyproject.toml
    - rdc_tool/__init__.py
    - scripts/_shared.py
    - scripts/package_runtime.py
    - scripts/package_release.py
    - scripts/release_gate.py
    - scripts/smoke_cli.sh
    - scripts/verify_release_package.py
    - spec/build_catalog.py
    - spec/validate_catalog.py
    - scripts/generate_tool_reference.py
    - scripts/check_markdown_health.py
    - scripts/generate_release_checksums.py
    - scripts/cleanup_workspace.py
    - bin/rdc-tool.cmd
---

## 1. 使用的系统与工具

- **Python 包管理**：使用 `setuptools` + `wheel`（`pyproject.toml` 中声明 `build-backend = "setuptools.build_meta"`），通过 `[project.scripts]` 暴露 `rdc = rdc_tool.cli:main` 作为唯一公共命令。
- **测试框架**：pytest，配置在 `pyproject.toml` 的 `[tool.pytest.ini_options]`，测试目录为 `tests/`，并显式排除 `intermediate`、`binaries`。
- **构建产物**：无 Makefile/Dockerfile；构建由 Python 脚本驱动，输出为自包含 Windows x64 zip 包和运行时二进制树。
- **CI/门禁**：`scripts/release_gate.py` 是统一的发布门禁入口，串联源码结构检查、清单校验、Bundled Python 校验、CLI 冒烟、文档健康、catalog 一致性、包内容验证等步骤。
- **版本来源**：单一来源 `rdc_tool/__init__.py` 中的 `__version__ = "1.0.0"`，被 `package_release.py` 直接 import 用于制品命名与元数据。

## 2. 关键文件与职责

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 定义包名 `rdc-tools`、依赖、可选 dev 依赖、pytest 配置、entrypoint |
| `rdc_tool/__init__.py` | 单一版本源 `__version__` |
| `scripts/_shared.py` | 共享路径解析、子进程封装、JSON 读写、`tools_root()` 定位仓库根（支持 `RDC_TOOL_ROOT` 覆盖） |
| `scripts/package_runtime.py` | 将 RenderDoc 原生二进制与可选 CPython home 拷贝到 `binaries/windows/x64/`，生成 `manifest.runtime.json` |
| `scripts/package_release.py` | 从仓库树复制受控目录到 staging，生成 `RELEASE_MANIFEST.json`、`LICENSE_INVENTORY.json`、`SBOM.json`，压缩为 `dist/rdc-tool-{version}-windows-x64.zip` 并写 `SHA256SUMS` |
| `scripts/release_gate.py` | 统一门禁：检查必需目录/文件、manifest 完整性、bundled python 布局、用户文档不含 pip/uv/venv 引导、catalog 与代码一致、public CLI 行为、release package 存在性与内容匹配 |
| `scripts/smoke_cli.sh` | Bash 冒烟脚本，按步骤执行 `rdc-tool doctor/tools list/capture open/vfs` 等，输出 `intermediate/logs/smoke_cli.log` 与 findings |
| `scripts/verify_release_package.py` | 解压 zip 后独立验证 manifest、license inventory、SBOM、doctor、launcher、version payload、tools catalog、正/负向 CLI 契约 |
| `spec/build_catalog.py` | 从 `rdc_tool.runtime_catalog.catalog_payload()` 生成 `spec/tool_catalog.json`，支持 `--check` 模式 |
| `spec/validate_catalog.py` | 校验 catalog schema、可读性、依赖完整性（被 release gate 调用） |
| `scripts/generate_tool_reference.py` | 根据 catalog 生成 `docs/tool-reference.md`，release gate 强制其新鲜 |
| `scripts/check_markdown_health.py` | Markdown 健康检查（被 release gate 调用） |
| `scripts/generate_release_checksums.py` | 生成发布 checksums |
| `scripts/cleanup_workspace.py` | 清理中间产物 |
| `scripts/preview_geometry_smoke.py` | 预览几何冒烟脚本 |
| `bin/rdc-tool.cmd` / `bin/rdc-tool` / `cli/run_cli.py` | 三个受保护的 public entrypoints，被 manifest 与 verify 严格约束 |

## 3. 架构与约定

### 3.1 构建流水线
1. **Runtime 打包**：`python scripts/package_runtime.py --source <renderdoc-staging> [--python-home ...]` 把允许后缀（`*.dll`, `*.json`, `pymodules/*.pyd`, `*.dll`）的文件复制到 `binaries/windows/x64/`，同时可捆绑一个 CPython home（复制 `python.exe/pythonw.exe/python3.dll/vcruntime*`、`DLLs/`、`Lib/` 并过滤 `site-packages`、`test`、`idlelib` 等顶层目录），生成 `manifest.runtime.json`。
2. **Release 打包**：`python scripts/package_release.py [--out-dir dist] [--version X.Y.Z]` 仅复制白名单目录（`bin`, `binaries`, `cli`, `docs`, `policy`, `rdc`, `scripts`, `spec`）及根级文件（`.gitattributes`, `.gitignore`, `AGENTS.md`, `CHANGELOG.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `README.md`, `pyproject.toml`, `bin/rdc-tool.cmd`），跳过 `tests/`、`intermediate/`、`dist/`、`__pycache__`、`.mypy_cache`、`.ruff_cache`、`.venv` 以及 `.pyc/.pyo/.pdb/.ilk/.exp/.lib/.rdc` 等后缀。最终产出 `dist/rdc-tool-{version}-windows-x64.zip`、同目录 `SHA256SUMS` 与 `release_report.md`。
3. **Catalog 生成**：`python spec/build_catalog.py` 生成 `spec/tool_catalog.json`；`--check` 模式下若文件内容与 `catalog_payload()` 不一致则返回非零退出码。
4. **门禁**：`python scripts/release_gate.py [--require-release-package] [--require-smoke-reports] [--report intermediate/logs/release_gate_report.md]` 依次执行：
   - 必需目录/文件存在性检查
   - 禁止引用 `extensions/` 与调试框架术语的正则扫描
   - 用户文档不得出现 `uv.lock`、`uv sync`、`python -m venv`、`pip install`、`bin/rdc-tool.cmd <command>` 示例
   - `spec/tool_catalog.json` 与代码定义名称集合、fingerprint 完全一致
   - `docs/tool-reference.md` 与 `generate_tool_reference()` 输出一致
   - 禁止 `mcp/` 出现在发布表面
   - `binaries/windows/x64/manifest.runtime.json` 中每个文件的 size/sha256 与实际磁盘一致
   - Bundled Python 布局校验（`rdc_tool.python_runtime.validate_bundled_python_layout`）
   - 运行 `rdc-tool --help/--version/--json doctor/tools list/context status/list/update/clear/vfs ls` 等正向契约，并断言若干负向契约（如 `vfs tree --format tsv` 应返回 `projection_not_supported`，`call rd.session.get_context --format tsv` 应返回 `tabular_projection_missing`，已移除的 `rd.resource.rename`/`rd.shader.save_binary` 应返回 `not_found`/`operation_not_found`/`tool_not_found`/`unknown_operation`/`unsupported_operation`/`unsupported_command`）
   - 可选地要求 `intermediate/logs/smoke_cli.log` 中存在 `[smoke] PASS`
   - 可选地要求 `dist/rdc-tool-*-windows-x64.zip` 存在并通过 `verify_release_package.py`

### 3.2 产物与清单
- **Runtime manifest**：`binaries/windows/x64/manifest.runtime.json`，记录每个打包文件的 path/size/sha256，可选含 `bundled_python` 元信息（python_version、entry、pth_file 等）。
- **Release manifest**：`rdc-tools/RELEASE_MANIFEST.json`，记录 name/version/platform/public_commands/entrypoints/file_count/files。
- **License Inventory**：`rdc-tools/LICENSE_INVENTORY.json`，遍历 `binaries/windows/x64/python/Lib/site-packages/*.dist-info/METADATA` 提取组件名/版本/许可证。
- **SBOM**：`rdc-tools/SBOM.json`，schema `rdc-tools.sbom.v1`，components 来自 license inventory。
- **Checksums**：`dist/SHA256SUMS` 列出 zip 文件名与 sha256。

### 3.3 入口点约束
- 公开命令固定为 `rdc`，对应 entrypoints 列表 `bin/rdc-tool.cmd`、`bin/rdc-tool`、`cli/run_cli.py` 三者必须存在于包内且 manifest 中声明一致。
- 用户文档中禁止出现 `bin/rdc-tool.cmd <command>` 形式的命令示例，只能将其作为 launcher-file 引用。

## 4. 约定与约束

- **版本单一来源**：所有制品版本号来自 `rdc_tool/__init__.py.__version__`；`package_release.py` 在启动时比对 `--version` 参数与导入值，不一致即返回 2。
- **受控复制白名单**：`package_release.py` 的 `RELEASE_DIRS`、`RELEASE_ROOT_FILES`、`EXCLUDE_DIRS`、`EXCLUDE_FILE_SUFFIXES` 与 `package_runtime.py` 的 `ALLOW_PATTERNS`、`DENY_SUFFIXES`、`SKIP_STDLIB_TOP_LEVEL`、`PYTHON_BASE_FILES` 共同构成严格的打包白名单/黑名单。
- **Manifest 强校验**：`release_gate.py` 对 runtime manifest 中每个条目校验 path 存在、size 相等、sha256 相等；对 release package 的 `RELEASE_MANIFEST.json` 校验 public_commands、entrypoints、files 与源码树一一对应。
- **Catalog 代码即真相**：`spec/tool_catalog.json` 必须由 `spec/build_catalog.py` 生成，release gate 用 `catalog_payload()` 计算期望集合并与之比较，任何缺失或多余 tool 都会失败。
- **文档即契约**：`docs/tool-reference.md` 必须与 `generate_tool_reference()` 输出完全一致；用户文档不得包含 `uv.lock`、`uv sync`、`python -m venv`、`pip install`、`bin/rdc-tool.cmd <cmd>` 等文本。
- **MCP 未 GA 隔离**：`mcp/` 不得出现在发布源码表面，用户文档不得出现 `mcp/run_mcp.py`、`model context protocol`、`mcp server`、`mcp public` 标记。
- **预 GA 内容屏蔽**：`verify_release_package.py` 拒绝包含 `runtime_materializer.py`、`worker-cache` 等 pre-GA 路径，以及 `worker_materialize`、`runtime_owner`、`owner_lease`、`runtime_baton`、`active_baton`、`rehydrate_status`、`staged_handoff`、`runtime_parallelism_ceiling`、`claim_runtime_owner`、`release_runtime_owner`、`export_runtime_baton`、`rehydrate_runtime_baton` 等文本标记。
- **Smoke 日志约定**：`smoke_cli.sh` 将结果写入 `intermediate/logs/smoke_cli.log`，并在成功时输出 `[smoke] PASS`；release gate 可通过 `--require-smoke-reports` 强制要求该标记存在。
- **工作区隔离**：所有中间产物（staging、artifacts、logs、pytest 缓存、context snapshot、worker-state）统一放在 `intermediate/`，构建脚本通过 `rdc_tool.runtime_paths.intermediate_root()` 访问，避免污染源码树。
- **路径安全**：`scripts/_shared.py` 提供 `ensure_within_root()` 防止 `--source`/`--python-home` 等参数逃逸仓库根；`tools_root()` 支持通过 `RDC_TOOL_ROOT` 环境变量覆盖仓库根定位。