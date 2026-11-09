## 1. 使用的构建系统与工具

- **打包后端**：`setuptools.build_meta`（`pyproject.toml`），依赖 `setuptools>=68`、`wheel`。
- **运行环境**：CI 使用 GitHub Actions，在 `windows-latest` 上以 Python 3.14 执行全部步骤。
- **测试框架**：pytest（通过 `pyproject.toml` 的 `[tool.pytest]` 配置），测试路径为 `tests/`，排除 `.git`、`intermediate`、`binaries`。
- **版本来源**：单一数据源位于 `rdc_tool/__init__.py` 中的 `__version__`，由 `scripts/package_release.py` 读取；PyPI 包名 `rdc-tool` 与 `pyproject.toml` 中的 `name` 保持一致。
- **发布产物**：自包含 zip（`dist/rdc-tool-*-windows-x64.zip`）、SHA256SUMS、`release_report.md`、以及 `intermediate/logs/release_package_source_gate.md` 源码门禁报告。

## 2. 关键文件与职责

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 声明包名、版本、依赖、entry point `rdc-tool = rdc_tool.cli:main`、pytest 配置 |
| `.github/workflows/ci.yml` | 三阶段 CI：contract → doctor-no-capture → release-package |
| `scripts/package_release.py` | 将仓库 checkout 打包成 Windows x64 自解压 zip，含白名单目录/文件过滤 |
| `scripts/release_gate.py` | 对已打包 zip 做完整性校验（必需目录/文件、禁止后缀、命令入口） |
| `scripts/distribution_metadata.py` | 生成可重定位的 `*.dist-info` 元数据（METADATA/WHEEL/RECORD） |
| `scripts/generate_tool_reference.py` | 从 catalog 生成文档，支持 `--check` 模式用于 CI |
| `scripts/check_identity.py` | 校验标识一致性（如 tag 与 `__version__`） |
| `scripts/check_markdown_health.py` | 文档健康检查（CI contract job 执行） |
| `scripts/smoke_cli.sh` / `bin/rdc-tool.cmd` | CLI 冒烟入口 |
| `spec/build_catalog.py` / `spec/tool_catalog.json` / `spec/validate_catalog.py` | 工具 catalog 的构建与契约校验 |

## 3. 架构与约定

### 3.1 构建流水线（CI）
`.github/workflows/ci.yml` 定义三个 job，按顺序依赖：

1. **contract**（`windows-latest`）：安装 dev 依赖后依次执行
   - `python spec/validate_catalog.py`
   - `python scripts/generate_tool_reference.py --check`
   - `python -m pytest tests -q --basetemp=intermediate/ci-tests`
   - `python scripts/check_markdown_health.py`
   - `python scripts/check_identity.py`
2. **doctor-no-capture**：调用 `bin\rdc-tool.cmd --version` 和 `--json doctor`，断言返回结构为 `rdc_tool.doctor` 且 `ok=true`。
3. **release-package**（仅在 push main 或打 `v*` tag 时触发）：
   - 若 `GITHUB_REF_TYPE == 'tag'`，断言 `GITHUB_REF_NAME == 'v' + __version__`（tag 名称必须等于 `v` + 包版本）。
   - 执行 `python scripts/package_release.py`。
   - 上传 `dist/rdc-tool-*-windows-x64.zip`、`dist/SHA256SUMS`、`dist/release_report.md`、`intermediate/logs/release_package_source_gate.md`。

并发控制通过 `concurrency.group: ci-${{ github.workflow }}-${{ github.ref }}` + `cancel-in-progress: true` 实现同分支串行化。

### 3.2 发布打包流程
`scripts/package_release.py` 的核心逻辑：

- 平台常量 `PACKAGE_PLATFORM = "windows-x64"`，包前缀 `rdc-tool`。
- 使用 `RELEASE_ROOT_FILES` 白名单决定根级保留文件（`.gitattributes`、`LICENSE`、`README.md`、`pyproject.toml`、`bin/rdc-tool.cmd`、`install.cmd` 等）。
- 使用 `RELEASE_DIRS` 白名单保留子目录（`bin`、`binaries`、`cli`、`docs`、`policy`、`rdc_tool`、`scripts`、`spec`）。
- `EXCLUDE_DIRS` / `EXCLUDE_FILE_SUFFIXES` 明确剔除 `.git`、`.venv`、`__pycache__`、`.pyc`、`.pdb`、`.lib`、`.exp`、`.ilk`、`.rdc` 等。
- 输出到 `dist/`，生成 SHA256SUMS 与 `release_report.md`。

`scripts/release_gate.py` 作为反向验证器，要求打包结果包含 `REQUIRED_DIRS`（含 `binaries/windows/x64/python`、`binaries/windows/x64/pymodules`）与 `REQUIRED_FILES`（含 `CHANGELOG.md`、`THIRD_PARTY_NOTICES.md`、`docs/rdc-tool-native-agent-playbook.md`、`docs/tool-reference.md`），并禁止 `.pdb`/`.lib`/`.exp`/`.ilk`/`.h` 等开发符号后缀。

### 3.3 运行时分发
`scripts/distribution_metadata.py` 负责在被分发的站点包中写入 `rdc_tool-<version>.dist-info`，其中 `INSTALLER` 字段固定为 `rdc-tool-runtime`，`WHEEL` 标记为 `py3-none-any`，`entry_points.txt` 注册 `rdc-tool = rdc_tool.cli:main`。该模块会清理已有同名 dist-info 但拒绝替换非 `rdc-tool-runtime` 安装的元数据目录。

### 3.4 版本策略
- 包版本由 `pyproject.toml` 的 `version` 字段声明（当前 `1.1.2`），并由 `rdc_tool.__version__` 暴露给脚本。
- Git tag 必须以 `v` 开头，且与 `__version__` 严格相等（CI 中 `assert os.environ['GITHUB_REF_NAME'] == 'v' + __version__`）。

## 4. 约定与约束

- **约束（由 CI 强制）**：push `main` 或打 `v*` tag 才会触发 release-package job；tag 名称必须等于 `v` + `rdc_tool.__version__`。
- **约束（由 packaging 脚本强制）**：发布 zip 必须包含 `binaries/windows/x64/python`、`binaries/windows/x64/pymodules`、`CHANGELOG.md`、`THIRD_PARTY_NOTRIES.md`、`docs/rdc-tool-native-agent-playbook.md`、`docs/tool-reference.md`；不得包含 `.pdb`/`.lib`/`.exp`/`.ilk`/`.h` 后缀文件。
- **约定**：所有构建/发布脚本均通过 `SCRIPT_ROOT = Path(__file__).resolve().parents[1]` 定位仓库根，再通过 `scripts/_shared.tools_root()` 获取顶层路径，避免相对路径歧义。
- **约定**：CLI 公共入口统一为 `bin/rdc-tool.cmd`（Windows）与 `rdc-tool`（console_scripts entry point），`release_gate.py` 将其列为 `EXPECTED_ENTRYPOINTS`。
- **约定**：测试与中间产物隔离——pytest 临时目录默认位于 `intermediate/ci-tests`，CI 通过 `--basetemp=` 显式指定。
- **约束（由 distribution_metadata.py 强制）**：站点包中已存在的 `*.dist-info` 若非本包生成（`INSTALLER != 'rdc-tool-runtime'`），会被拒绝覆盖。
- **约定**：工具 catalog 变更需经 `spec/validate_catalog.py` 与 `generate_tool_reference.py --check` 双重校验，否则 contract job 失败。
