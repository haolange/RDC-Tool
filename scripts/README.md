# scripts

`scripts/` 是维护者工具：发布、运行库打包、文档生成与 smoke。用户安装与使用不需要其中任何脚本（安装器 `rdc_tool_install.ps1` 除外，它由 `install.cmd` 调用）。

## 门禁与生成物

| 脚本 | 作用 |
|---|---|
| `generate_tool_reference.py` | 从 `rdc_tool/operation_definitions.py` 生成 `docs/tool-reference.md`；`--check` 只校验是否最新 |
| `check_markdown_health.py` | 检查 Markdown 编码、BOM、乱码与必需文档 |
| `check_identity.py` | 检查产品名、命令名与历史身份残留 |
| `release_gate.py` | 发布前的源码、仓库运行库与公开 CLI 门禁；`--require-smoke-reports`、`--require-release-package` 用于正式发布 |
| `release_runtime.py` | 发布校验专用的隔离运行状态与进程清理（被 `release_gate.py`、`verify_release_package.py` 使用） |

## 运行库与发布

| 脚本 / 数据 | 作用 |
|---|---|
| `package_runtime.py` | 在本主机组装本主机运行目录：原生集合（`--source` + `--build-receipt`）、捆绑 Python（`--python-archive`）、主机工具（`--host-tools`），规则见 [docs/install.md](../docs/install.md) |
| `python-runtimes.json` | 每个主机布局钉住的官方 Python 归档（版本、来源、sha256、复制条目） |
| `runtime-dependencies.lock` | 捆绑 Python 的第三方依赖哈希锁（`uv pip compile` 生成） |
| `native_source_digest.py` | 计算原生构建回执的 `tree_sha256`（按 Git 提交内容），定义见 [docs/release-baseline.md](../docs/release-baseline.md) |
| `distribution_metadata.py` | 为捆绑 Python 写入 `rdc-tool` 的 distribution metadata |
| `package_release.py` | 构建本主机发行包（`rdc-tool-<版本>-<主机>.zip`）；`--candidate-dir` 生成隔离的本地验收候选 |
| `verify_release_package.py` | 校验发行包或候选的文件、身份与公开 CLI 行为；`--metadata-only` 只校验文件与身份 |
| `rdc_tool_install.ps1` | Windows 安装、升级、卸载与 doctor；升级只替换字节不同的文件，只删除上一版清单拥有且新版不再包含的文件 |
| `cleanup_workspace.py` | 清理本库自有的运行与测试残留，按进程身份停止自有进程 |
| `_shared.py` | 脚本共用的路径与子进程辅助 |

## Smoke

smoke 经 bash 运行，每条 CLI 调用都可见：

```bash
bash scripts/smoke_cli.sh
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```

`smoke_cli.sh` 直接调用 `bin/rdc-tool` 执行 doctor、工具发现，以及传入 `--rdc` 时的 capture/session 链路，日志写入 `intermediate/logs/smoke_cli.log`。`preview_geometry_smoke.py` 经公开 launcher 验证 preview 窗口几何，preview 行为变化时与 CLI 文档同步。需要可清理的独立输出根时，先设置 `RDC_TOOL_INTERMEDIATE_ROOT`。

正式发布要求干净的已提交检出；发行清单与 SBOM 记录完整的 `source_revision`，门禁按 HEAD 核对该提交与每个随包源码文件。
