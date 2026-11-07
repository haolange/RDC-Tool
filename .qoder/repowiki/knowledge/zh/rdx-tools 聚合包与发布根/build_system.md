## 1. 使用的系统

仓库采用 **纯 Python + setuptools** 的轻量构建体系，没有 Makefile / Dockerfile / CI pipeline。核心装配点为根目录 `pyproject.toml`，使用 `setuptools.build_meta`（要求 `setuptools>=68`、`wheel`），将 `rdc_tool` 作为可安装 Python 包分发，并通过 `[project.scripts]` 暴露 `rdc-tool` 命令行入口。

构建产物由 `scripts/` 下的自研 Python 脚本驱动：
- `package_runtime.py` — 把 CPython 运行时、RenderDoc 原生二进制、Android APK 组装进 `binaries/windows/x64/python` 和 `binaries/android/{arm32,arm64}`，并生成 `manifest.runtime.json`。
- `package_release.py` — 从源码树复制受控文件集，生成 `dist/rdc-tool-<version>-windows-x64.zip`、`SBOM.json`、`LICENSE_INVENTORY.json`、`RELEASE_MANIFEST.json` 及 `SHA256SUMS`。
- `release_gate.py` — 发布门禁，校验结构、清单、公共命令行为、文档与包完整性。
- `release_runtime.py` — 隔离运行期上下文，在门禁中清理 daemon 状态。
- `generate_release_checksums.py`、`distribution_metadata.py`、`verify_release_package.py`、`check_markdown_health.py` 等辅助脚本。

测试通过 `pytest`（`[tool.pytest.ini_options]`），标记了 `unit` / `contract` / `fixture_integration` / `gpu_live` 四类；CI 仅存在于 `.github/workflows/ci.yml`（本次未读取其内容）。

## 2. 关键文件

| 路径 | 作用 |
|---|---|
| `pyproject.toml` | 包名 `rdc-tool`、版本 `1.1.2`、依赖、`rdc-tool` 入口、pytest 配置 |
| `scripts/_shared.py` | `tools_root()`、`task_directory()`、`ensure_within_root()`、`run_subprocess()` 等共享工具 |
| `scripts/package_runtime.py` | 捆绑 CPython stdlib/site-packages、校验 RenderDoc 原生 build receipt、写入 `manifest.runtime.json` |
| `scripts/package_release.py` | 白名单复制源码、计算 SHA256、写 SBOM/License Inventory、压缩 zip |
| `scripts/release_gate.py` | 结构化门禁检查 + 对 `rdc-tool` 子命令的行为断言 |
| `scripts/release_runtime.py` | `isolated_release_runtime()` 隔离 `RDC_TOOL_INTERMEDIATE_ROOT` 并回收 daemon |
| `scripts/smoke_cli.sh` | bash 冒烟脚本，被 gate 消费日志 |
| `spec/build_catalog.py` / `spec/validate_catalog.py` / `spec/tool_catalog.json` | 工具契约目录与验证器 |
| `intermediate/` | 构建/测试中间产物输出目录 |
| `binaries/` | 平台二进制与捆绑 Python 运行时 |
| `bin/rdc-tool.cmd` | Windows 启动器 |

## 3. 架构与约定

### 3.1 版本来源
版本号只维护在 `pyproject.toml` 的 `[project].version = "1.1.2"`；`package_release.py` 通过 `from rdc_tool import __version__ as TOOL_VERSION` 读取，并在 `main()` 中强制校验 `--version` 参数是否匹配，不匹配直接返回 2。

### 3.2 双阶段产出
- **Runtime 阶段**：`python scripts/package_runtime.py --source ... --python-home ... [--output-root intermediate/runtime/...]` 产出 `binaries/` 或临时 staging 目录，生成 `manifest.runtime.json`，记录每个文件的 size+sha256，以及可选的 `bundled_python`、`native_build`、`bundled_tools`。
- **Release 阶段**：`python scripts/package_release.py [--out-dir dist] [--candidate-dir intermediate/...]` 在白名单内复制源码、跳过 `tests/`、`.git*`、`intermediate/`、`binaries/`（除非传入 `--runtime-root`）、`*.pyc/.pdb/*.lib` 等后缀，生成 zip 后再次运行 source-gate 并比较打包前后 sha256。

### 3.3 任务目录约束
`_shared.task_directory()` 强制所有构建/测试输出必须位于 `intermediate/` 或 `dist/` 下，且不能是 symlink/junction、不能越出仓库根、`new=True` 时拒绝覆盖已有目录。该规则被 `package_runtime.py`、`package_release.py` 等多处调用。

### 3.4 不可变输入校验
- `package_runtime.py` 通过 `build_receipt` JSON 精确比对 RenderDoc 原生输出的 size/sha256，不允许新增/缺失文件，也不允许生成 `manifest.runtime.json` 由外部提供。
- `package_release.py` 在 zip 创建前与创建后两次扫描源文件，若任何非 `binaries/` 且非生成清单的文件 size/sha256 变化则抛出异常。
- `_source_revision()` 要求 `git status --porcelain` 干净，否则拒绝打包。

### 3.5 发布门禁 (`release_gate.py`)
门禁包含以下强制性检查：
- 存在 `REQUIRED_DIRS`（`rdc_tool`、`bin`、`cli`、`spec`、`policy`、`docs`、`tests`、`binaries/windows/x64/python`、`binaries/windows/x64/pymodules`）与 `REQUIRED_FILES`（`pyproject.toml`、`CHANGELOG.md`、`THIRD_PARTY_NOTICES.md`、`docs/rdc-tool-native-agent-playbook.md`、`docs/tool-reference.md`）。
- CHANGELOG 必须包含当前版本的标题行 `## <TOOL_VERSION>`。
- 禁止引用 `extensions/` 路径、`debug-agent|RDC-Agent-Frameworks` 字符串。
- 用户文档不得出现 `uv.lock`、`uv sync`、`python -m venv`、`pip install` 等引导命令。
- 工具参考文档必须新鲜（`generate_tool_reference.py` 重新生成并与 `docs/tool-reference.md` 比对）。
- 禁止 MCP 公开入口。
- 清单完整性、配对 native manifest、bundled host tools、bundled python layout 均通过代码校验。
- 实际执行 `rdc-tool --help/--version/tools list/context status/list/update/clear/vfs ls/call/diff/assert` 等子命令，并对错误码做负向断言（如 `session_required`、`projection_not_supported`、已移除的 `rd.resource.rename`、`rd.shader.save_binary` 应返回 `not_found`/`unknown_operation` 等）。
- 运行 `spec/validate_catalog.py` 与 `scripts/check_markdown_health.py`。
- 支持 `--require-smoke-reports` 与 `--require-release-package` 使报告整体 FAIL。

### 3.6 运行时隔离
`release_runtime.isolated_release_runtime()` 通过设置 `RDC_TOOL_INTERMEDIATE_ROOT` 与 `RDC_TOOL_ROOT` 环境变量，在临时目录中运行 gate，并在 finally 中调用 `context clear` + `daemon stop` 清理 owned daemon；即使清理失败也保留临时目录并附带 recovery note。

### 3.7 平台与分发
- 目标平台常量 `PACKAGE_PLATFORM = "windows-x64"`，zip 命名格式 `rdc-tool-<version>-windows-x64.zip`。
- Windows 启动器为 `bin/rdc-tool.cmd`，同时保留 `cli/run_cli.py` 与 `install.cmd` 作为 entrypoints。
- Android 辅助 APK 通过 `binaries/android/arm32` 与 `binaries/android/arm64` 分别放置。
- 捆绑的 Python 运行时来自独立 CPython home，std lib 经 `_copy_tree_filtered` 过滤掉 `site-packages/test/tests/idlelib/turtledemo/ensurepip/venv/__pycache__` 等顶层目录，仅拷贝 `*.dll`、`*.json` 以及 `pymodules/` 下的 `*.pyd`/`*.dll`/`*.json`。

## 4. 约定与约束（描述性 + 显式规则）

- **版本单一来源**：`pyproject.toml` 中的 `version` 是唯一权威值；`package_release.main()` 用 `if str(args.version) != TOOL_VERSION: return 2` 强制执行。
- **构建输出位置**：所有 task 输出必须在 `intermediate/` 或 `dist/` 下，由 `_shared.task_directory()` 以 `ValueError` 强制。
- **源码树不可链接**：`package_runtime._reject_links()` 与 `package_release._copy_release_tree()` 遇到 symlink/junction 即抛 `RuntimeError`。
- **Release 打包必须干净 checkout**：`package_release._source_revision()` 调用 `git status --porcelain`，非空即 `RuntimeError`。
- **Release zip 不允许覆盖**：若 `dist/rdc-tool-<version>-windows-x64.zip` 已存在，`package_release.main()` 抛 `FileExistsError`。
- **Native 输入与 receipt 强一致**：`package_runtime._windows_runtime_inputs()` 与 `_native_build_receipt()` 要求 input file set 完全相等且每个文件 sha256 不变，否则 `ValueError`。
- **Public command 契约**：`release_gate.py` 硬编码 `EXPECTED_PUBLIC_COMMANDS = ["rdc-tool"]` 与 `EXPECTED_ENTRYPOINTS`，并通过实际子进程执行验证。
- **Removed operations 必须报错**：`REMOVED_CATALOG_TOOLS = {"rd.resource.rename", "rd.shader.save_binary"}` 配合 `_run_public_command_expect_error(... expected_codes={...})` 强制它们返回 `not_found`/`operation_not_found`/`tool_not_found`/`unknown_operation`/`unsupported_operation`/`unsupported_command`。
- **User docs 禁止第三方安装引导**：`USER_PATH_FORBIDDEN_RULES` 正则禁止 `uv.lock`、`uv sync`、`python -m venv`、`pip install`。
- **Smoke 日志位置**：`BASH_SMOKE_LOG = "intermediate/logs/smoke_cli.log"`，gate 仅在 `--require-smoke-reports` 时将其视为必需。
- **Report 输出**：gate 默认写入 `intermediate/logs/release_gate_report.md`，末尾 `Overall: PASS|FAIL` 决定退出码。

## 5. 适用性说明

本仓库没有 Makefile/Dockerfile/GitHub Actions 工作流定义（`.github/workflows/ci.yml` 存在但未读取），构建与发布完全由 Python 脚本 + `pyproject.toml` 驱动，属于中等复杂度的纯 Python 发布系统，证据充分，置信度为 high。