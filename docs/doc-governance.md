# 文档治理

本文规定 `rdc-tool` 文档的写法、真源与同步方式；长期工程规则见 [../AGENTS.md](../AGENTS.md)。

## 写法

- 本库是 CLI-only。文档描述 shell 入口 `rdc-tool` 与 canonical JSON 行为；用户文档只写 CLI 命令，Python 启动细节只出现在维护者章节。
- 全部文档用简洁直接的简体中文叙述；技术术语、标识符、命令、操作名（`rd.*`）、错误码、路径与 JSON 字段保留英文。
- 每个 `.md` 以 UTF-8 BOM 开头。`scripts/check_markdown_health.py` 检查编码、BOM、乱码、本地链接与必需文档。
- 不写开发机绝对路径；示例使用占位路径，如 `C:/path/sample.rdc`、`intermediate/<task>/...`。
- 不硬编码 tool 数量或 catalog fingerprint；二者只来自生成的 catalog。
- 安装、quickstart 等用户文档不得要求运行包管理器、创建虚拟环境或按 lock 文件恢复依赖。发行包是自包含的，依赖来源由 `pyproject.toml`、运行目录 manifest、许可证清单与 SBOM 记录。

## 生成物

`rdc_tool/operation_definitions.py` 是操作定义的唯一真源。`spec/tool_catalog.json` 与 `docs/tool-reference.md` 由它生成，不得手改，也不得叠加第二份 metadata overlay：

```bash
python -B spec/build_catalog.py [--check]
python -B scripts/generate_tool_reference.py [--check]
```

不带 `--check` 时重新生成，带 `--check` 时只校验是否最新。示例、生成参考、smoke 脚本与测试一律使用当前操作名与参数。工作流建议与专业判断写进 Agent Skill，不写进操作描述。

已删除操作的去向只记录在 [tool-interface-upgrade.md](tool-interface-upgrade.md)。它是历史记录，不是别名表；运行时从不读取它。

## 单一真源

每个主题只在一处陈述，其他文档链接过去，不复述：

| 主题 | 唯一位置 | 门禁 |
|---|---|---|
| 架构、分层、依赖方向与平台层 | [ARCHITECTURE.md](../ARCHITECTURE.md) | `tests/test_runtime_layering.py`、`tests/test_platform_boundary.py` |
| RenderDoc 基线、原生运行库身份、发布资格与交付 | [release-baseline.md](release-baseline.md) | — |
| 环境变量 | [configuration.md](configuration.md) | `tests/test_configuration_doc.py` |
| 维护者脚本 | [scripts/README.md](../scripts/README.md) | `tests/test_scripts_governance.py` |
| RDC-Agent 配对 | [agent-integration.md](agent-integration.md) | — |
| 操作契约 | [tool-reference.md](tool-reference.md)（生成） | 生成器 `--check` |
| 当前任务清单与验收事实 | [tool-convergence-tasks.md](tool-convergence-tasks.md) | — |

## preview

触及 `rd.session.open_preview` 或 preview 几何的改动，必须同步 `preview_geometry_smoke.py` 与用户 preview 文档。

## Fixture 与发布

小型公开 `.rdc` 只有在来源、大小、SHA256 与许可证都有记录时才能放进 `tests/fixtures/`，测试分层见 [fixture-strategy.md](fixture-strategy.md)。发行包排除 `.rdc` fixture 与仅供测试的资产。

只跑源码部分的 `release_gate.py` 可以跳过包校验，但不构成正式发布资格。正式打包、发布 CI 与授权发布的规则见 [release-baseline.md](release-baseline.md)。
