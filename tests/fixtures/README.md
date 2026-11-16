# `tests/fixtures/`

本目录存放仅供仓库测试使用的小型公开 `.rdc` capture。

当前 fixture：

| 文件 | 大小（字节） | SHA256 | 来源 |
| --- | ---: | --- | --- |
| `vkcube.rdc` | 75478 | `00797a27e6316a0cf4369327f9db30a21635fa757673b3f9712af07989145ba8` | 上游 rdc-cli 项目 `tests/fixtures/vkcube.rdc` |
| `vkcube_validation.rdc` | 65913 | `c50cd1e7c29241c64fd33faf07cb35e802f9dc85692a8512aa36db01c956b385` | 上游 rdc-cli 项目 `tests/fixtures/vkcube_validation.rdc` |

规则：

- 只允许来源与许可证明确的小型公开 capture。
- 不要把开发者本地、私有、客户或大体积的 `.rdc` 文件复制进本仓库。
- 不要在源码、文档、测试或发行元数据中写入开发者机器上的 capture 绝对路径。
- 这些 fixture 只用于测试，不得进入发行包。
- 复制的 MIT 资产的署名记录在 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。

用途：

- 确定性的仓库测试。
- 需显式开启的真实回放测试：经被测安装自己的 launcher 打开这两个 capture，读取 action tree 与管线，执行无窗口观察后关闭回放，并清理 context 与 daemon。`--fixture-root` 默认是当前仓库；未开启时测试跳过，开启后安装无法本地回放即判为失败。

```bash
python -m pytest tests/test_fixture_integration.py --fixture-integration --fixture-root <installation>
```

有真实 RenderDoc 运行库或设备时，完整的本地或 Android 远端 smoke 仍可以向 CLI smoke 命令传入显式的外部 capture 路径：

```bash
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```
