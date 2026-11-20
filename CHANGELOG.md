# 变更记录 `Changelog`

## 待发布 `Unreleased`

- 修复 Linux 本地回放在打开 capture 时段错误：POSIX 加载原语此前先用 ctypes 预加载 `librenderdoc.so`，RenderDoc 的库构造函数此时还看不到 Python 绑定导出的 `renderdoc__replay__marker`，便按"被注入的捕获目标"安装钩子，随后在 `WrappedVulkan::Serialise_vkCreateSwapchainKHR` 崩溃。Linux 主机布局把原生库移到 `lib/librenderdoc.so`（Vulkan layer 清单同在 `lib/`），由绑定自带的 RUNPATH `$ORIGIN/../lib/` 作为依赖加载，POSIX 不再预加载任何库。此前记为"lavapipe 上原生回放崩溃"的阻塞即此缺陷，与驱动无关。
- 统一请求拒绝的无副作用证明：事件缺失等前置拒绝仅在未尝试原生效果且入口回放及关联状态逐项不变时返回 `validation` 与保全字段；无法证明时返回 `runtime`。事件不存在的分类由 `not_found` 改为 `validation` 或 `runtime`；仅有未尝试 shader replacement 不再证明整个回放未变。
- 新增 `rdc_tool/platform/` 平台层（host、locks、process、ipc、native、preview），每个契约一套共享逻辑加 Windows/POSIX 原语；平台包外禁止任何主机判断，由 `tests/test_platform_boundary.py` 守护。此前 HEAD 在 Linux 上无法 import。参考外部 PR #2 重新实现并署名。
- 锁：进程内 mutex 与文件锁共用一个 monotonic deadline，文件锁只做非阻塞重试；daemon 启动等待 30 秒，持久化 context 状态与 snapshot 等待 10 秒并返回声明错误 `state_lock_timeout`。Windows 不再使用约 10 秒后静默放弃的 `LK_LOCK`。
- 进程身份 `(pid, birth)` 成为唯一存活依据：PID 复用与僵尸判为已退出，不可读身份为 unknown，永不当作已退出、永不授权终止；POSIX daemon 领导独立进程组，停止时整组回收；内存不可测时报告 `null` 与原因而非固定 0。
- 安全：daemon IPC 在解码任何请求前完成 HMAC 握手（此前 Windows daemon 先 unpickle 再比对 token）；IPC key 经 stdin 交给 daemon，不再出现在 argv 与任何输出中（`daemon status`/`start`、attach、`context clear` 曾打印它）；POSIX socket 位于 0700 私有目录，state 文件为 0600；握手失败不再终止 accept 循环。
- daemon state 由 `rdc_tool/daemon/state.py` 唯一拥有，输出字段 `pipe_name` 改为 `endpoint`；删除未文档化的 `daemon start --pipe-name`、`start_daemon` 别名、`session_state*.json` 与 `context_id`/`started_at_ms` 双写双读。旧格式 state 判为无效，按恢复指引重新启动即可。
- 原生 preview 窗口成为主机能力：非 Windows 主机返回 `preview_unsupported_platform`，`rd.core.get_capabilities` 报告 `preview_window`。
- CLI 单入口：`cli/run_cli.py` 只定位安装并调用 `rdc_tool.cli.main`；删除第二套 version 载荷、私有 `--context-id` 别名、吞掉子命令 help 的拦截与非标准 envelope 的简化 doctor；shell 补全词表从 argparse 树与 catalog 派生；删除 `RDX_*` 退役守卫。
- 删除约 3.8k 行死代码（6 个模块、26 个只被它们使用的 model、`jinja2` 依赖、无读取者的配置节与环境变量、约 30 个无引用函数）；`rd.core.set_config` 只接受实际生效的键，未知键报错；`RDC_TOOL_ARTIFACT_STORE` 并入 `RDC_TOOL_ARTIFACT_DIR`；删除 S3 artifact 模式与 shader encoding 静默回退（请求的 encoding 不可用时按目标不可用报错）。
- Catalog 运行时单源：运行时、前置条件路由与 discovery 只读 `operation_definitions` 构建的不可变索引，`spec/tool_catalog.json` 仅为生成物；两个 CI job 都运行 `build_catalog --check`；doctor 报告 catalog 来源、fingerprint 与工具数。
- `requires-python >=3.14`；CI 新增 ubuntu job；LFS filter 不再作用于捆绑 Python 的 `.pyd`/`.exe` 普通 blob（此前 LFS 检出总显示 105 个文件被修改，并阻塞正式打包的干净源码检查）。
- 原生构建回执迁出 `binaries/windows/x64/manifest.runtime.json`，成为全目标共享的 `binaries/native_build.json`；`source` 新增必填 `repository` 与 `revision`（fork `haolange/renderdoc@dde8822`，已核验其两个 parent 即原记录的 base/upstream），主机输出角色改为平台中立的 `native_library`／`binding_module`。二进制未变，`receipt_sha256` 随回执内容变化。
- 回执校验改为“存在即严格、缺席仅报告”：doctor 与发布脚本按场景所需目标（默认本主机 + 两个 Android helper）判定，结果新增 `targets` 与 `missing_targets`。
- `rd.capture.open_replay` 在本地回放前检查 `LocalReplaySupport`：本主机运行库不能回放该 capture API 时返回 `local_replay_unsupported`，不再进入原生回放后才失败。
- `package_runtime` 跨平台：`--host` 组装本主机运行目录；捆绑 Python 来自 `scripts/python-runtimes.json` 钉住的官方归档（Windows NuGet 3.14.3、Linux python-build-standalone 3.14.6），依赖按哈希锁 `scripts/runtime-dependencies.lock` 安装，不再复制开发机 `.venv`；新增 `--host-tools` 输入；运行目录中无归属的文件直接拒绝。解释器路径改由主机布局声明，manifest 的 `bundled_python` 只记录来源（Windows 清单按既有回执事实补齐，二进制未变）。
- `bin/rdc-tool` 按主机选择捆绑解释器（Linux x86_64 → `binaries/linux/x64/python/bin/python3.14`，MSYS/Cygwin → Windows 解释器），未知主机与缺失解释器以退出码 2 明确拒绝；两个 launcher 清除 `PYTHONHOME`/`PYTHONPATH`、以 `python -s` 启动，不再导出任何 `RDC_TOOL_*` 变量。preview 几何 smoke 改经公开 launcher 运行，adb 只走主机工具契约，删除 PATH/SDK 搜索。
- daemon 与 worker 子进程以 `python -P -m` 启动：工作目录里同名的 `rdc_tool` 包不再遮蔽安装本身（Linux 候选真实运行发现）。
- 新增 `scripts/native_source_digest.py`，按 Git 提交内容定义回执的 `tree_sha256`；本地候选只认证并携带其回执配对的目标；新增需显式开启的 `fixture_integration` 真实回放测试（`--fixture-integration`、`--fixture-root`）；删除与 `vkcube.rdc` 字节相同的 `hello_triangle.rdc`。
- 13.5k 行的 `server_runtime.py` 按领域拆入 `rdc_tool/runtime/`：`dispatch`（执行）→ `routing`（catalog 路由、参数与前置条件、replay 健康作用域）→ `operations/<ns>.py`（每个命名空间一个 `dispatch(action, args)`）→ 服务与记录模块；删除 `server.py` 转发壳、`tool_router.py`、19 个一行 `handlers/`、`core/engine.py`、`core/operation_registry.py` 与 `replay_observation.py`（并入 `runtime/observation.py`），worker 入口移至 `rdc_tool.runtime.worker_main`。新增分层门禁：只允许 replay 服务组成环、服务层不依赖操作层、各命名空间处理的动作与 catalog 完全一致（删除了无法到达的 `remote.set_overlay_options` 分支）。
- 发布脚本按主机布局工作：包名带主机目标，`binaries/` 只带本主机运行目录、Android helper 与共享回执；校验解压时还原权限位；原生加载核验不再依赖 Windows 专属 `PATH`。删除发布门禁与包校验中的“已删除名单”（旧别名、pre-GA 标记、MCP 标记、`rdc_tool.bat` 示例、旧路径扫描）及依赖 `rg` 的双实现扫描器；catalog 与定义完全一致的检查已覆盖多余工具。
- 操作结果改为类型化的 `Success`/`Failure`：构造时一次性转成 JSON 安全数据，`dispatch` 只做类型分派，其他返回值一律为 `internal_error`；删除 `_ok`/`_err` 的 JSON 字符串往返、五种结果形状嗅探与“未知结构判成功”，操作间组合不再解析字符串。修复 `rd.util.list_artifacts` 的 `data.artifacts` 被丢弃（契约声明了该字段）；`rd.debug.evaluate_expression` 在读取变量失败时返回该失败，而不是当作空变量表。
- 仓库与文档：删除 `.qoder/`（175 个过期生成页）、空 `policy/` 与强制跟踪的 `intermediate/` 占位；全部文档改为中文叙述（术语保留英文）；RenderDoc 基线、环境变量、脚本说明与 RDC-Agent 配对各只在一处声明并由测试守护；用户文档不再写死工具总数，`docs/tool-reference.md` 改为中文生成；`docs/tool-interface-upgrade.md` 收为已删除操作的历史处置记录；`docs/tool-convergence-tasks.md` 只保留当前 Task 清单。
- Linux 原生构建不再需要修改 fork：dde8822 的 `vk_pixelhistory.cpp` 缺少 `#include <vector>`，改用 `-include vector` 编译选项补齐，源码树保持干净，Linux 产物与 Windows、Android 产物同属一个 revision；绑定通过 `Python3_EXECUTABLE` 对捆绑解释器编译。按此构建的本地候选与两个 Android helper 同源配对（doctor 三个目标均为 `verified`），配置见 `docs/release-baseline.md`。
- 修复 POSIX 上 `daemon stop` 偶发误报超时：读取正在被 init 回收的进程的 `/proc/<pid>/stat` 会在 `open` 成功后以 ESRCH 失败（立即回收的环境下约四成概率），此前被当作“身份不可读”而判为仍存活；现在 ESRCH 判为已退出，停止流程也不再在确认退出后重复探测。超时消息报告实际存活判定（`alive`/`unknown`）。

## 1.1.2 — 2026-10-29

- 修复 Windows 后台 worker 的 Android 冷启动：使用同安装 ADB 有界启动 server，显式设备按冻结 serial 查询 get-state，仅在 device 状态继续准备。
- 未指定 serial 时保留明确枚举并校验响应；空响应与未授权、离线分别失败，不静默切换设备、不增加隐藏重试。
- ADB 子进程在 Windows 使用分离进程组，继续复用连接 deadline、取消和退出回收；不改变 helper 归属、catalog 或用户数据边界。

## 1.1.1 — 2026-10-29

- Windows 安装自包含 ADB 36.0.2、所需 DLL 与 SPIRV-Tools v2026.4 汇编/反汇编程序，固定来源、哈希与许可证并写入 SBOM。
- ADB/SPIR-V 默认解析本安装；保留显式高级覆盖，无效覆盖直接失败，删除 PATH/SDK 静默搜索与无调用配置。
- doctor、runtime manifest 重生成和发行门禁验证完整工具链；未连接设备与安装损坏分别报告。
- 修复非交互 ADB 继承 stdin 导致输出丢失，连接与传输统一使用受控标准输入；不改变操作 catalog 与用户数据边界。


## 1.1.0 — 2026-10-29

- 汇总原生事件取证与远端回放能力，补齐 shader 编译、替换、设备恢复与回放证据契约。
- Shader patch 绑定精确目标 ID 与原始源码，拒绝有歧义或来源不匹配的替换。
- 同一 daemon context 启动串行化，锁竞争共用有界 deadline，避免重复启动和无限等待。
- 发行包记录清洁源码提交号、完整文件哈希及一致版本的 Python distribution metadata；升级清除上一份发行清单中已替代的程序文件。
- 修复 bash smoke 入口变量，沿用 RenderDoc 1.45 基线及同安装捆绑 Python/CLI 绑定；实际能力以 catalog 指纹和参数契约校验。

## 1.0.2 — 2026-09-23

- 将 `rd.session.*` worker 操作预算统一提高到 60 秒；CLI daemon transport 继续增加 5 秒响应缓冲，门限为 65 秒。
- 与 RDC-Agent 默认 120 秒外层 CLI 等待对齐；操作目录与 IPC/result contract 不变。
- 补充 session timeout 策略测试、故障排查说明与会话模型文档。

## 1.0.1 — 2026-09-20

- 恢复完整 Apache-2.0 LICENSE 并收入新 zip，不修改 v1.0.0 tag 或旧资产。
- 核对发行版本、CHANGELOG、manifest、SBOM、license inventory 与 checksum；包内 LICENSE 必须与当前源码逐字节一致。
- 打包使用独立暂存目录，成功或失败均释放；Agent 可直接选择解压目录。
- 发行验证使用隔离运行目录，成功、失败或取消时先释放 context 再停止自有 daemon；清理失败使门禁失败并保留恢复信息，不吞掉占用错误。

## 1.0.0

### Breaking

- Breaking: 产品和公共命令统一为 `rdc-tool`，旧 `rdx` / `rdx-tools` 入口不提供转发或兼容别名。嵌入宿主绑定同安装捆绑 Python 与 `cli/run_cli.py`。

### 首个 GA baseline

- 发布口径锁定为 1.0.0 首个 GA baseline；pre-GA 的 owner/lease/baton/handoff 与 runtime materialization 实验不进入 1.0 公共契约。
- 收敛 CLI context 模型：`--daemon-context` 仅表示隔离 runtime namespace，不承载业务编排或任务交接语义。
- 移除 worker runtime materialization/cache 设计，worker 直接使用 packaged runtime binaries 与 `pymodules`。
- 明确 `rd.remote.connect` 的 direct RenderDoc 与 Android adb bootstrap 参数契约。
- 加固 release package 验证：发布包必须与当前 release source tree manifest 一致，且不得携带 pre-GA runtime cache / owner-handoff surface。
- 新增持久化 `context/session` state，支持本地 `.rdc` warm resume、多 session `current_session_id` 选择、trace-linked operation history、runtime metrics 与 bounded event-tree pagination。
- 新增 `rd.session.list_sessions`、`rd.session.select_session`、`rd.session.resume`、`rd.core.get_operation_history`、`rd.core.get_runtime_metrics`、`rd.core.list_tools`、`rd.core.search_tools` 与 `rd.core.get_tool_graph`。
- 新增只读 `rd.vfs.*` tools，以及配套的 CLI `vfs` commands，用于在 draws、passes、resources、pipeline、context 与 artifacts 上执行 JSON-first 导航。
- 修复 `scripts/release_gate.py`，使 `rg` fallback 能区分 literal/path scan 与 regex scan，并避免在无效 regex assembly 时崩溃。
- 新增 `pyproject.toml`，让依赖、pytest markers 与本地开发 entrypoints 可复现，同时不改变 repo-first runtime model。
- 新增聚焦 VFS 的 tests 与 release-gate regression coverage。
- 新增 stable/GA CLI surface：`--version`、`version --json`、`completion powershell|bash|zsh|fish`、自包含 Windows x64 release package、安装生命周期脚本、package verification 与 1.x 兼容承诺文档。
