# 当前 Task 清单

本页只记录当前一轮工作的任务、依赖、状态与阻塞；已发布版本的事实见 [CHANGELOG](../CHANGELOG.md) 与 [发布说明](release-notes.md)，稳定规则见 [AGENTS.md](../AGENTS.md) 与 [ARCHITECTURE.md](../ARCHITECTURE.md)。状态取值：`待执行 / 执行中 / 待验证 / 通过 / 阻塞`。

## 本轮目标：跨平台收敛与架构升级

把外部 Linux 适配 PR 引出的问题一次性收敛为单一实现：`rdc_tool/platform/` 平台层、Linux x64 作为与 Windows 同策略的主机布局（本轮代码与工具链，正式产物下一轮）、运行时与 catalog 单一真源、`server_runtime.py` 按领域拆分、遗留与文档债务清零，并用测试门禁锁住。Windows 只经 CI（`workflow_dispatch`）验证，不开 PR、不打 tag、不发布。

| 任务 | 依赖 | 状态 | 交付与验收 |
|---|---|---|---|
| C 预备 | — | 通过 | LFS filter 只对捆绑 Python 的 `.pyd`/`.exe` 关闭，blob 不变；`requires-python >=3.14`；删除未使用的 `gpu_live` marker |
| P 平台层 | C | 通过 | host/locks/process/ipc/native/preview 契约与 Windows/POSIX 原语；daemon HMAC 先于解码、IPC key 经 stdin、`endpoint` 取代 `pipe_name`；平台边界门禁与真实后端契约测试；CI 新增 ubuntu job |
| L 遗留清洗 | P | 通过 | 删除死模块与无读取配置；CLI 单入口；重复实现收一；删除 S3 模式与 encoding 静默回退 |
| R 拆分运行时 | L | 执行中 | R1 catalog 单源、R3–R9 拆入 `rdc_tool/runtime/` 与分层门禁已通过；R2 envelope 收敛为类型化 `Success`/`Failure` 执行中，完成条件：`dispatch` 只接受类型化结果、删除 JSON 字符串往返与形状嗅探、全量测试与两 OS CI 通过 |
| I 运行库身份 | R | 通过 | `HOST_LAYOUTS`（windows-x64、linux-x64）；共享回执 `binaries/native_build.json`（`source.repository/revision`）；`local_replay_unsupported` |
| K 打包工具链 | I | 通过 | `package_runtime` 跨平台、钉住解释器与哈希锁依赖；按主机选择解释器的 launcher；按主机打包与校验 |
| T 测试分层 | K | 通过 | 单元测试用 fake renderdoc 在任意主机运行；`fixture_integration` 显式开启才运行，开启后不可回放即失败 |
| X Linux 候选 | T | 阻塞 | 已用 fork `haolange/renderdoc@dde8822`（加 GCC 编译补丁）构建 `librenderdoc.so` 与 binding，带 adb r36.0.2 与源码构建的 SPIRV-Tools v2026.4，组装并校验候选包；候选实际加载 1.48 / dde8822。真实回放阻塞，见下文 |
| G RDC-Agent 对齐 | R | 通过 | 分支 `claude/happy-einstein-n9rvui`：daemon 注册名 `rdc_tool_cli`，不再传 `RDC_TOOL_ROOT`，guide catalog 快照按新 fingerprint 刷新，其门禁通过 |
| D1 仓库卫生 | — | 通过 | 删除 `.qoder/`、`policy/` 与 `intermediate/` 占位；脚本与环境变量文档由测试守护 |
| D2 文档中文化 | D1 | 待验证 | 全部文档中文叙述、保留 BOM；基线、配置、脚本、配对各只一处声明；`tool-reference.md` 中文生成；用户文档禁止写死工具总数 |
| D3 Task 与发布事实 | D2 | 通过 | 本页重写为当前清单；本轮变更写入 CHANGELOG 与发布说明 |
| D4 架构定稿与收口 | R2, D3 | 待执行 | `ARCHITECTURE.md` envelope 章节随 R2 定稿；CI action 升级到 Node 24 版本；推送并在两 OS CI 通过；清理候选构建树、临时下载与测试输出，复查无自有进程残留 |

## 阻塞与已知差距

| 项 | 影响 | 解除条件 |
|---|---|---|
| lavapipe 上原生回放崩溃 | X 的真实回放：候选 `librenderdoc.so` 打开 `vkcube.rdc` 后在 `ReplayController::PostCreateInit` → `WrappedVulkan::Serialise_vkCreateSwapchainKHR` 段错误，`fixture_integration` 按设计失败 | 在有真实 Vulkan 驱动的 Linux 主机复测；或在 fork 中定位 swapchain 序列化对无 surface 软件驱动的处理 |
| fork 的 GCC 编译补丁 | dde8822 在 GCC 下缺少 `#include <vector>` 无法编译；补丁只在本地 fork 克隆中，未推送 | 由仓库所有者决定是否推送到 `haolange/renderdoc`；推送后源码树与现有 Windows/APK 回执不同，需按 [release-baseline](release-baseline.md) 整套重建配对 |
| 候选未配对 Android helper | 候选源码树含 GCC 补丁，与 APK 回执的 `tree_sha256` 不同，候选只认证 `linux-x64` | 同一冻结源码重建 Linux `.so`、Windows DLL/PYD 与双 APK，写入同一份回执 |
| Linux 正式产物 | 尚无 Linux 发行包 | 下一轮：同源构建、老 glibc 基线构建环境、`package_runtime --host linux-x64`、包校验 |
| Windows 捆绑依赖早于哈希锁 | 已提交的 Windows `python/` 中仍有 MCP 时代的多余包，`bundle == lock` 校验未启用 | 下一轮用 `package_runtime --host windows-x64` 按锁重建并启用该校验 |
| Windows 与 Android 真机验收 | 本轮无 GPU 与设备，只有 CI | 发布前在 Windows 机器运行 `bash scripts/smoke_cli.sh --rdc tests/fixtures/vkcube.rdc` 与 [Android 验收](android-remote-cli-smoke-prompt.md) |
| Linux CI 偶发 daemon 停止超时 | `test_slow_real_daemon_is_reused_across_processes` 偶发 `daemon stop timed out`，本地复现不出 | 停止超时消息已带存活判定（`alive`/`unknown`），据下一次失败的判定定位根因 |
