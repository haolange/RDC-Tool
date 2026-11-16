# Capture Fixture 策略

`tests/fixtures/` 可以存放小型公开 `.rdc`，供仓库测试使用；发行包不含任何 `.rdc`。

## 测试分层

- **单元与契约测试**：在每台主机上针对 fake renderdoc binding 运行（`tests/fakes/renderdoc.py`，经 `fake_renderdoc` fixture 注入 `sys.modules`），配合 mock payload、schema 与 catalog 校验。它们不加载真实 RenderDoc，也不证明真实回放。
- **`fixture_integration`**：经某个安装自己的 launcher 真实回放已提交的 capture，需显式开启：

  ```bash
  python -m pytest tests/test_fixture_integration.py --fixture-integration --fixture-root <installation>
  ```

  `--fixture-root` 默认是当前检出，也可以指向本地候选等其他安装。测试对每个 fixture 打开 capture、读取 action tree 与管线、执行无窗口 `rd.session.observe` 并关闭回放，最后清理 context 与 daemon。未开启时跳过；一旦开启，安装无法本地回放即判为失败而不是跳过。软件驱动缺少的能力必须以 `capability` 类错误出现，不能崩溃。
- **本地完整 smoke**：有真实 RenderDoc 运行库时，用 `bash scripts/smoke_cli.sh --rdc <path>` 传入显式的桌面 capture。
- **Android 远端 smoke**：经 CLI 传输，用显式 capture 路径执行 `rd.remote.connect`、`rd.remote.ping` 与 `rd.capture.open_replay`，流程见 [android-remote-cli-smoke-prompt.md](android-remote-cli-smoke-prompt.md)。

真实 GPU、设备与远端验收依赖外部环境，不是干净检出的默认门禁。

## Capture 规则

- 只有来源与许可证清楚的小型公开 capture 才能放进 `tests/fixtures/`；当前集合与哈希见 `tests/fixtures/README.md`。
- 不把本地、私有、客户或大型 capture 拷进本仓库。
- 不在源码、文档、测试或发布元数据中写开发机绝对路径。
- 在 `tests/fixtures/README.md` 与 `THIRD_PARTY_NOTICES.md` 记录 fixture 文件名、大小、SHA256、来源与许可证。
- 不保留重复字节：`hello_triangle.rdc` 与 `vkcube.rdc` 字节完全相同，已删除。
- Android 设备序列号与发行包 SHA256 属于发布验证时，记录在 `intermediate/logs/tool_smoke_findings.md`。
- capture 暴露产品缺陷或环境阻塞时，保留证据日志并开一个聚焦的后续任务，不弱化发布门禁。

## 与发布的关系

- `bash scripts/smoke_cli.sh` 不带 `--rdc` 只做入口 smoke；带 `--rdc <path>` 时执行经 daemon 的 capture 链路。
- `python scripts/release_gate.py --require-smoke-reports` 只检查 `intermediate/logs/smoke_cli.log` 含 `[smoke] PASS`。
- `scripts/package_release.py` 与 `scripts/verify_release_package.py` 把 `.rdc` 与 `tests/` 排除在发行包之外。

脚本用法见 [../scripts/README.md](../scripts/README.md)，发布资格见 [release-baseline.md](release-baseline.md)。
