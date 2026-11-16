# 当前 Task 清单

本页只记录当前一轮工作的任务、依赖、状态与阻塞；已发布版本的事实见 [CHANGELOG](../CHANGELOG.md) 与 [发布说明](release-notes.md)，稳定规则见 [AGENTS.md](../AGENTS.md) 与 [ARCHITECTURE.md](../ARCHITECTURE.md)。状态取值：`待执行 / 执行中 / 待验证 / 通过 / 阻塞`。

## 本轮目标：RDC-Agent 对接问题修复

| 任务 | 依赖 | 状态 | 交付与验收 |
|---|---|---|---|
| 旧 daemon 状态 | 无 | 待验证 | 隔离样本通过进程、锁、资源和状态损坏检查；旧现场仍登记远程资源，保留原件 |
| 异常 worker 后清理 | 无 | 待验证 | 隔离测试覆盖已退出身份、replacement、远程归属与原生清理失败；待产品实机复验 |
| shader 产物字节 | 无 | 待验证 | 隔离测试覆盖 LF、CRLF 与非 ASCII，保存字节和 artifact store 一致；待产品审计 |
| 错误分类 | 无 | 待验证 | 对提交中的 36 处逐项核对，安全前置拒绝返回证明；不确定结果保持隔离 |
| 集成验收与本地交付 | 上述任务 | 执行中 | Windows 全量测试 1316 passed、12 skipped、2 subtests passed；catalog 和生成文档检查通过，待正式隔离打包与最小产品路径。受限沙箱中的 taskkill 返回 Access denied，同一测试及全量门禁在正常权限下通过 |

错误分类核对：20 处是 catalog 路由不支持操作的兜底，另 3 处已被参数校验或更早的调试参数检查拦截。其余分支中，capture 缺失、事件索引未命中、表达式未找到和可提前确认的格式错误按实际阶段提供保全信息；图像依赖缺失是 capability 错误，当前 Agent 尚不将该类别的一般保全证明用于保留 lease。healthcheck 会触及文件、debug 超时可能已推进调试状态、Pixel History 可能已进入原生调用，均保留不确定分类；自动选择格式后才能判断的失败也不虚报前置保全。

## 上轮：跨平台收敛与架构升级

把外部 Linux 适配 PR 引出的问题收敛为单一实现：`rdc_tool/platform/` 平台层、Linux x64 作为与 Windows 同策略的主机布局（本轮代码与工具链，正式产物下一轮）、运行时与 catalog 单一真源、`server_runtime.py` 按领域拆分、遗留与文档债务清零，并用测试门禁锁住。PR #3 已合并，Windows 与 Android 验收结果见下文；本轮不打 tag、不发布。

| 任务 | 依赖 | 状态 | 交付与验收 |
|---|---|---|---|
| C 预备 | — | 通过 | LFS filter 只对捆绑 Python 的 `.pyd`/`.exe` 关闭，blob 不变；`requires-python >=3.14`；删除未使用的 `gpu_live` marker |
| P 平台层 | C | 通过 | host/locks/process/ipc/native/preview 契约与 Windows/POSIX 原语；daemon HMAC 先于解码、IPC key 经 stdin、`endpoint` 取代 `pipe_name`；平台边界门禁与真实后端契约测试；CI 新增 ubuntu job |
| L 遗留清洗 | P | 通过 | 删除死模块与无读取配置；CLI 单入口；重复实现收一；删除 S3 模式与 encoding 静默回退 |
| R 拆分运行时 | L | 通过 | R1 catalog 单源、R3–R9 拆入 `rdc_tool/runtime/` 与分层门禁；R2 操作结果改为类型化 `Success`/`Failure`，`dispatch` 只接受类型化结果，JSON 字符串往返与形状嗅探已删除；本地全量测试与两 OS CI 通过 |
| I 运行库身份 | R | 通过 | `HOST_LAYOUTS`（windows-x64、linux-x64）；共享回执 `binaries/native_build.json`（`source.repository/revision`）；`local_replay_unsupported` |
| K 打包工具链 | I | 通过 | `package_runtime` 跨平台、钉住解释器与哈希锁依赖；按主机选择解释器的 launcher；按主机打包与校验 |
| T 测试分层 | K | 通过 | 单元测试用 fake renderdoc 在任意主机运行；`fixture_integration` 显式开启才运行，开启后不可回放即失败 |
| X Linux 候选 | T | 阻塞 | 从未修改的 fork `haolange/renderdoc@dde8822` 构建 `librenderdoc.so` 与 binding（`-include vector`，见 [release-baseline](release-baseline.md#linux-原生构建)），带 adb r36.0.2 与源码构建的 SPIRV-Tools v2026.4 组装候选。候选回执与仓库回执共用同一 `source`，doctor 报告 `linux-x64`、`android-arm32`、`android-arm64` 均为 `verified`（回执 sha256 `137638888bcd…`）；实际加载 `librenderdoc.so` `5b13dd58…`、`renderdoc.so` `4a860c0d…`，内嵌提交 dde8822、版本 1.48。真实回放阻塞，见下文 |
| G RDC-Agent 对齐 | R | 通过 | 分支 `claude/happy-einstein-n9rvui`：daemon 注册名 `rdc_tool_cli`，不再传 `RDC_TOOL_ROOT`；合并后主进程真实发现、只读调用与 guide catalog 指纹一致，详见下文 |
| D1 仓库卫生 | — | 通过 | 删除 `.qoder/`、`policy/` 与 `intermediate/` 占位；脚本与环境变量文档由测试守护 |
| D2 文档中文化 | D1 | 通过 | 全部文档中文叙述、保留 BOM；基线、配置、脚本、配对各只一处声明；`tool-reference.md` 中文生成；用户文档禁止写死工具总数 |
| D3 Task 与发布事实 | D2 | 通过 | 本页重写为当前清单；本轮变更写入 CHANGELOG 与发布说明 |
| D4 架构定稿与收口 | R2, D3 | 通过 | `ARCHITECTURE.md` 操作结果章节；CI action 升到 Node 24 版本；两 OS CI 通过；候选构建树、临时下载与测试输出已清理，无自有进程残留 |

## 阻塞与已知差距

| 项 | 影响 | 解除条件 |
|---|---|---|
| lavapipe 上原生回放崩溃 | X 的真实回放：候选 `librenderdoc.so` 打开 `vkcube.rdc` 后在 `ReplayController::PostCreateInit` → `WrappedVulkan::Serialise_vkCreateSwapchainKHR` 段错误，`fixture_integration` 按设计失败 | 在有真实 Vulkan 驱动的 Linux 主机复测；或在 fork 中定位 swapchain 序列化对无 surface 软件驱动的处理 |
| Linux 正式产物 | 尚无 Linux 发行包 | 下一轮：在 glibc 较老的构建环境中按 [release-baseline](release-baseline.md#linux-原生构建) 的配置构建，把 `linux-x64` 写入仓库共享回执，`package_runtime --host linux-x64` 与包校验 |
| Windows 捆绑依赖早于哈希锁 | 已提交的 Windows `python/` 中仍有 MCP 时代的多余包，`bundle == lock` 校验未启用 | 下一轮用 `package_runtime --host windows-x64` 按锁重建并启用该校验 |

## 2026-11-16 合并后验收

| 项 | 状态 | 结果 |
|---|---|---|
| PR 与 main CI | 通过 | PR #3 以 merge commit `a971e4b6fb30c76701ba56eedbe92159fa2f2aa0` 合入；PR [CI](https://github.com/haolange/RDC-Tool/actions/runs/43899238747) 与该 merge commit 的 [main CI](https://github.com/haolange/RDC-Tool/actions/runs/43900135329) 均通过 contract、linux、doctor-no-capture、release-package |
| Windows 测试与身份 | 通过 | Python 3.14 全量测试 1268 passed、12 skipped、2 subtests passed；catalog、tool-reference、Markdown health、identity 检查通过。doctor 的 native_build、windows-x64、android-arm32、android-arm64 均为 verified；catalog fingerprint 为 `05322468c3e39db23a671fdd20747d52b8db11e455979fbf2c6ba2e523254042` |
| Windows 真实回放与 preview | 通过 | 仓库 `vkcube.rdc`（Vulkan）和用户提供的 D3D12 capture 分别通过 CLI smoke；preview 修复后实际显示 Vulkan 画面，窗口关闭且所属 daemon/worker 退出。修复与回归测试在 PR 提交 `0391d50`，预览定向测试 32 项通过 |
| Android 远端 | 通过 | ADB 设备上复用已安装的匹配 arm64 helper，以 `WhiteHair.rdc` 完成 connect、ping 和显式 remote_id 的 open_replay；释放本轮回放、连接、helper 进程及 forward。设备实际画面呈现未验证，不以回放成功推断呈现 |
| RDC-Agent 真实发现 | 通过 | 隔离设置验证并应用合并后的安装，显示 1.1.2、129 操作；独立主进程真实回放验收中 list/describe 的指纹与快照一致，资源只读调用成功，原输入哈希不变，daemon/worker 退出。Agent 门禁及相关测试见其验收账本 |

Linux 候选的真实回放和 Linux 正式发行包仍按上表阻塞；Windows 捆绑依赖按锁重建仍属下一轮范围。
