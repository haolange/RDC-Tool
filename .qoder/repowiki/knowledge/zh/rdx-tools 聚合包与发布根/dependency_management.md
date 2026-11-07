# 依赖管理：rdx-tools 聚合包

## 1. 使用的系统/方法

- **Python 包依赖**：使用 `pyproject.toml`（PEP 621）+ `setuptools.build_meta` 构建后端声明依赖，无 `requirements.txt`、`poetry.lock`、`pipenv` 或 `uv.lock`。
- **构建依赖**：通过 `[build-system].requires = ["setuptools>=68", "wheel"]` 锁定最小版本。
- **运行时依赖**：集中在 `[project].dependencies`，仅声明顶层运行时库；测试依赖走 `[project.optional-dependencies] dev`。
- **平台二进制产物**：Windows x64 与 Android 原生工具以预编译二进制形式随仓库分发（`binaries/windows/x64/`、`binaries/android/`），不在构建时下载。
- **许可证合规**：第三方组件清单位于根目录 `THIRD_PARTY_NOTICES.md`，由 `scripts/distribution_metadata.py`、`scripts/release_runtime.py`、`scripts/generate_release_checksums.py` 等脚本驱动生成。

## 2. 关键文件

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | 唯一 Python 依赖声明入口（运行时 + 开发依赖 + 构建后端） |
| `THIRD_PARTY_NOTICES.md` | 所有第三方组件（Python 包、Android Platform-Tools、SPIRV-Tools、测试 fixture）的许可证与来源声明 |
| `binaries/windows/x64/manifest.runtime.json` | 平台运行时二进制元数据（SHA256、版本、构建方式），是 SBOM 与 LICENSE_INVENTORY 的唯一真实来源 |
| `binaries/windows/x64/spirv-tools/LICENSE.txt` / `SPIRV-Headers-LICENSE.txt` | SPIRV-Tools 上游许可随包分发 |
| `binaries/windows/x64/adb/source.properties` | ADB 版本标识 |
| `scripts/distribution_metadata.py` | 从 manifest 生成发行元数据 |
| `scripts/release_runtime.py` / `scripts/package_runtime.py` | 打包运行时二进制与校验和 |
| `scripts/release_gate.py` | 发布门禁脚本（含依赖/身份校验） |
| `spec/tool_catalog.json` + `spec/build_catalog.py` + `spec/validate_catalog.py` | 工具清单与构建目录契约，约束分发结构 |

## 3. 架构与约定

### Python 依赖
- 运行时代码仅依赖 5 个第三方包：`aiofiles`、`jinja2`、`numpy`、`Pillow`、`pydantic`，全部采用 `>=X.Y` 宽松下限。
- 测试依赖 `pytest>=9.0` 作为可选依赖组 `dev`，不进入生产安装。
- `requires-python = ">=3.11"` 在包级别约束解释器。
- 未使用虚拟环境管理器（无 `.python-version`、`poetry.lock`、`uv.lock`），依赖解析完全交由 `pip` / `setuptools`。

### 平台二进制产物
- Windows 端：`binaries/windows/x64/` 包含 Python 3.14 运行时 (`python/Lib/...`)、SPIRV-Tools (`spirv-tools/`)、ADB (`adb/`) 及 RenderDoc 相关 JSON 配置。
- Android 端：`binaries/android/arm32/`、`binaries/android/arm64/` 提供 ARM 原生工具。
- 这些二进制**直接提交到仓库**（见 `.gitignore` 排除 `intermediate/`、`binaries/windows/binaries/windows/...` 等中间路径），不属于 `rdc-tool` 发布包。
- `binaries/windows/x64/manifest.runtime.json` 记录每个二进制的 SHA256、上游版本与构建参数，SBOM 与许可证清单从此文件生成。

### 许可证与审计
- `THIRD_PARTY_NOTICES.md` 维护三类资产：
  1. rdc-cli 测试捕获（`.rdc` 文件，MIT，仅用于 `tests/fixtures/`，不参与发布）。
  2. Android Platform-Tools 36.0.2（Google 官方 zip，固定版本）。
  3. SPIRV-Tools v2026.4（KhronosGroup tag，Apache-2.0 + Headers MIT）。
- 发布脚本（`scripts/release_runtime.py`、`scripts/generate_release_checksums.py`）根据 manifest 校验 SHA256 并生成 SBOM。

## 4. 约定与约束

- **Python 依赖只通过 `pyproject.toml` 声明**：代码中未发现 `requirements.txt`、`setup.py` 或 `Pipfile`；`[build-system].requires` 同时约束构建期依赖。
- **运行时依赖保持最小化**：仅 5 个第三方包，其余为 stdlib；测试依赖隔离在 optional-dependency group `dev`。
- **平台二进制固定版本**：Android Platform-Tools 固定为 `36.0.2`，SPIRV-Tools 固定为 `v2026.4`（Header revision `496543121ce6419f23d6fa5d7194ba612d2`），变更需同步更新 `THIRD_PARTY_NOTICES.md` 与 `manifest.runtime.json`。
- **二进制不可变且带完整性校验**：`manifest.runtime.json` 中的 SHA256 由发布流程校验，禁止手动替换。
- **测试 fixture 与产品代码解耦**：`.rdc` 测试捕获明确标记“仅用于确定性仓库测试”、“不包含在 `rdc-tool` 发布包”，由发布脚本排除。
- **SBOM 与许可证清单由 manifest 自动生成**：`distribution_metadata.py`、`release_runtime.py` 是生成者，`manifest.runtime.json` 是唯一人工编辑源，避免手写清单漂移。
- **CI 门禁**：`scripts/release_gate.py` 与 `spec/validate_catalog.py` 在发布前验证工具清单与运行时元数据一致性，确保依赖声明与分发产物一致。