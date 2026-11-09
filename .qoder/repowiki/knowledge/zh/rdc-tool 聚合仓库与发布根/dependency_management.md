## 1. 使用的系统与工具

仓库是一个 Python 聚合包（`rdc-tool`），采用 **PEP 621** 风格，把构建后端固定为 `setuptools.build_meta`，通过 `pyproject.toml` 中的 `[project]` 元数据声明依赖，不使用 `requirements.txt`/`Pipfile`/`poetry.lock` 等锁定文件。

- 构建后端：`setuptools>=68` + `wheel`
- Python 版本门槛：`requires-python = ">=3.11"`
- 发布入口：`[project.scripts] rdc-tool = "rdc_tool.cli:main"`
- 开发可选依赖：`[project.optional-dependencies] dev = ["pytest>=9.0"]`
- 运行时核心依赖：`aiofiles`, `jinja2`, `numpy`, `Pillow`, `pydantic`（均为 `>=X.Y` 宽松下界）

没有发现 Go (`go.mod`)、Node (`package.json`) 或 Rust (`Cargo.toml`) 的依赖声明；也没有 `vendor/`、GOPRIVATE、私有 registry 配置。Go 仅在 CI 中作为脚本语言被调用，不管理 Go 依赖。

## 2. 关键文件

| 路径 | 作用 |
|---|---|
| `pyproject.toml` | PEP 621 依赖声明、构建后端、entry point、pytest 配置 |
| `rdc_tool/runtime_requirements.py` | 运行时可导入依赖清单、site-packages 打包白名单过滤规则 |
| `binaries/windows/x64/manifest.runtime.json` | 预构建的二进制产物（含内嵌 Python、DLL、ADB、SPIRV-tools 等）的 SHA-256 清单 |
| `scripts/package_runtime.py` | 从宿主 Python 环境拷贝 site-packages 并生成 manifest 的打包脚本 |
| `scripts/distribution_metadata.py` | 生成 SBOM / LICENSE_INVENTORY / CANDIDATE_MANIFEST 等发布元数据 |
| `THIRD_PARTY_NOTICES.md` | 第三方许可证清单（发布物配套） |
| `.gitattributes` | 排除 `intermediate/`、`binaries/`、`.pytest_cache/` 等目录 |

## 3. 架构与约定

### 3.1 依赖分层

仓库区分了三层依赖：

1. **构建期依赖**：`setuptools`、`wheel`（在 `[build-system].requires`）。
2. **运行期依赖**：`pydantic`、`numpy`、`Pillow`、`jinja2`、`aiofiles`（`[project].dependencies`）。这些名称同时出现在 `rdc_tool/runtime_requirements.REQUIRED_DEPENDENCIES` 中，用于在目标设备上检测缺失依赖。
3. **开发期依赖**：`pytest`（`[project.optional-dependencies] dev`），仅进入测试环境，不会被打入分发产物。

### 3.2 运行时依赖探测

`rdc_tool/runtime_requirements.module_available()` 使用 `importlib.util.find_spec` 探测模块是否存在，`missing_dependencies()` 遍历 `REQUIRED_DEPENDENCIES` 返回缺失包名列表。该 API 供服务端/CLI 在启动时报告环境缺口。

### 3.3 二进制制品与 site-packages 裁剪

`scripts.package_runtime.py` 负责把宿主环境的 site-packages 复制到 `binaries/windows/x64/python/Lib/site-packages`，并通过 `should_bundle_site_package()` 做白名单过滤：

- 显式排除前缀包括 `_pytest`、`pytest`、`pluggy`、`iniconfig`、`pygments`、`pip`、`pyarrow`、`setuptools`、`wheel`、`adodbapi`、`isapi`、`pythonwin`、`rdc_tool-` 等。
- 拒绝 `.pyc`、`.pth` 以及 Markdown/RST 文档。
- 顶层跳过 `site-packages`、`test`、`tests`、`idlelib`、`turtledemo`、`ensurepip`、`venv`、`__pycache__`。

这样保证分发的 Python 运行时只包含运行所需的库，不含测试和构建工具。

### 3.4 制品清单与校验

`binaries/windows/x64/manifest.runtime.json` 记录每个文件的相对路径、大小与 SHA-256，由 `package_runtime.py` 生成。CI 通过 `scripts/release_gate.py`、`scripts/verify_release_package.py` 对清单进行一致性检查。

### 3.5 发布元数据

`scripts/distribution_metadata.py` 会生成以下 JSON（见 `intermediate/native-replay/candidate-delivery/rdc-tool/`）：

- `SBOM.json` — 软件物料清单
- `LICENSE_INVENTORY.json` — 许可证清单
- `CANDIDATE_MANIFEST.json` — 候选发布清单

`THIRD_PARTY_NOTICES.md` 是面向最终用户的第三方许可证汇总。

## 4. 约定与约束

- **依赖声明来源**：所有 Python 依赖统一写在 `pyproject.toml` 的 `[project].dependencies` 中；运行时探测清单同步维护在 `rdc_tool/runtime_requirements.REQUIRED_DEPENDENCIES`，两者保持手动同步。
- **版本范围策略**：所有运行时依赖均使用 `>=` 宽松下界，未使用 lockfile 锁定具体版本。
- **构建后端锁定**：`[build-system].requires` 固定 `setuptools>=68`、`wheel`，禁止切换其他构建后端。
- **Python 版本门控**：`requires-python = ">=3.11"`，安装器必须满足此要求。
- **运行时依赖检测**：服务端/CLI 启动时应调用 `missing_dependencies()` 并在缺少依赖时失败（由 `runtime_requirements.py` 提供 API）。
- **site-packages 裁剪规则**：打包时必须经过 `should_bundle_site_package()` 过滤，不得直接复制整个 site-packages（由 `package_runtime.py` 强制执行）。
- **二进制产物不可编辑**：`binaries/` 与 `intermediate/` 被 `.gitattributes` 排除出 git diff（`.gitattributes` 中列出排除模式），确保制品由构建流程再生成而非手工修改。
- **无私有源/VCS 依赖**：未发现 `setup.cfg`、`pip.conf`、`pip.ini`、`PYPI_MIRROR`、`GOPRIVATE` 等私有注册表或 VCS 依赖配置；所有依赖来自 PyPI。
- **无锁文件**：仓库中没有 `requirements.txt`、`poetry.lock`、`uv.lock`、`Pipfile.lock` 等同步文件，版本可滚动至任意大于等于声明下界的版本。

## 5. 适用范围说明

本仓库是 Python 聚合包，依赖管理系统围绕 `pyproject.toml` + `setuptools` 构建；非 Python 平台二进制（adb、spirv-tools、RenderDoc pyd 等）以预编译形式随 `binaries/` 分发，并由 `manifest.runtime.json` 做完整性校验，不属于传统“包管理器”范畴。