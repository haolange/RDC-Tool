# `tests/fixtures/`

本目录存放仅供仓库测试使用的小型公开 `.rdc` capture。

当前 fixture：

| 文件 | 大小（字节） | SHA256 | 来源 |
| --- | ---: | --- | --- |
| `vkcube.rdc` | 75478 | `00797a27e6316a0cf4369327f9db30a21635fa757673b3f9712af07989145ba8` | 上游 rdc-cli 项目 `tests/fixtures/vkcube.rdc` |
| `vkcube_validation.rdc` | 65913 | `c50cd1e7c29241c64fd33faf07cb35e802f9dc85692a8512aa36db01c956b385` | 上游 rdc-cli 项目 `tests/fixtures/vkcube_validation.rdc` |
| `vkcube_lavapipe.rdc` | 154267 | `c62edae0ac451484ca651c88741e37dc011abaddbcb18f7aded0fd284a909cb6` | Khronos Vulkan-Tools 的 `vkcube` 在 Mesa lavapipe 上运行，用本仓库钉住的 RenderDoc fork（`dde8822`）录制 |

每个 capture 只能在与录制驱动兼容的设备上回放：前两个由 NVIDIA Vulkan 驱动录制，标为 `nvidia-vulkan`；`vkcube_lavapipe.rdc` 录自 Mesa lavapipe，标为 `software-vulkan`，已在 lavapipe 与 Windows SwiftShader 上回放，其他 Vulkan 实现可能因内存要求不同而拒绝。`fixtures.json` 是机器可读清单，测试按 `device`、大小与哈希选择输入。新增 capture 时同时更新本表、`fixtures.json` 与 `THIRD_PARTY_NOTICES.md`。

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

默认选择 `nvidia-vulkan`；使用已确认兼容的软件 Vulkan 驱动时传入 `--fixture-devices software-vulkan`，只回放该类 capture。

### 重录 `vkcube_lavapipe.rdc`

在 Linux 上按 [release-baseline.md](../../docs/release-baseline.md#linux-原生构建) 构建原生库与绑定后：

1. 安装 `vulkan-tools`（提供 `vkcube`）与 Mesa lavapipe，确认 `VK_ICD_FILENAMES` 指向 lavapipe 的 ICD JSON，并 `unset VK_DRIVER_FILES`，避免系统驱动抢先。
2. 在 Xvfb 中运行（`xvfb-run -a`），用构建出的 Python 绑定执行：`renderdoc.ExecuteAndInject("/usr/bin/vkcube", <工作目录>, "--c 3000", [VK_ICD_FILENAMES=<lavapipe ICD>], <输出前缀>, CaptureOptions(), False)`，再以 `CreateTargetControl` 连接，等待约 3 秒后 `TriggerCapture(1)`，从 `NewCapture` 消息取得路径。
3. 用同一绑定回放核对：6 个 action、draw 位于 EID 11、渲染目标 500×500 `B8G8R8A8_UNORM`、中心像素可读；再按上表更新大小与 SHA256。

有真实 RenderDoc 运行库或设备时，完整的本地或 Android 远端 smoke 仍可以向 CLI smoke 命令传入显式的外部 capture 路径：

```bash
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```
