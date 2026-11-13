# Linux 原生 CLI：安装、运行与支持范围

本分支是 **Linux x86-64 开发适配**，不是已经完成全平台验收的发行版。Windows/Android 原有运行库和发布流程保留；Linux 原生运行库需要按下面步骤单独准备，不应混用 Windows DLL/PYD。

Linux 改动包括 shell 入口、Python/原生库发现与身份检查、POSIX 文件锁、AF_UNIX daemon 传输和不创建监听 socket 的前台 `stdio` 传输。是否能回放某份捕获仍由 RenderDoc 后端和图形驱动决定。完整路径选择见 [Linux 截帧读取与回放](linux-replay-paths.md)。

## 支持边界

- 原生回放：OpenGL/OpenGLES/Vulkan，需捕获 API、扩展、格式及设备能力兼容。此前实际验证过 GLES 捕获的事件读取、纹理读回和会话关闭；这不是对所有捕获的保证。
- D3D11：Linux 上游 RenderDoc **不提供原生 D3D11 replay**。打开容器元数据和静态导出可以成功，但不能据此声明 `OpenCapture` 回放成功。
- 原生 Win32 preview 窗口不在 Linux 实现；显式请求返回 unsupported。无窗口的数据读取与图像导出是另一项能力。
- 上游 RenderDoc 1.47 和仓库自定义 Windows 1.45 不是同一运行库。只有加载的库实际提供的扩展才可使用，版本号不能代替能力检查。
- Linux daemon 需要系统允许 AF_UNIX listener。受限环境可能拒绝该操作；使用显式 `stdio` 是不同传输方式，不是自动绕过失败。前台模式也持有同一 context 所有权锁。
- 软件驱动不等于兼容所有 GPU 捕获。曾遇到其他厂商 Vulkan 捕获与 lavapipe 内存布局不兼容；不能把此情况计作 Vulkan replay 通过。

## 1. 安装 Python 前端

在源码根目录执行。Python 需要 3.11+，并且必须与后面构建的 RenderDoc binding 使用相同 CPython ABI。

```sh
sudo apt-get update
sudo apt-get install python3 python3-dev python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
export RDC_TOOL_PYTHON="$PWD/.venv/bin/python"
bash bin/rdc-tool --version
bash bin/rdc-tool tools list --json
```

以上只安装前端，尚未提供 RenderDoc 原生库。Linux-only 使用不需要加载 Windows DLL 或 Android APK；Windows/Android 发行验证仍遵循原发布文档。

## 2. 准备同源码、同 ABI 的 Linux RenderDoc 运行库

推荐冻结一个上游版本，同时构建 `librenderdoc.so` 和 Python binding。下面是 RenderDoc v1.47 的源码构建路径；发行版包名可能不同，依据 CMake 的实际缺失项安装对应开发包。不得混合不同版本的 library 和 binding。

```sh
sudo apt-get install build-essential git cmake pkg-config bison autoconf automake libtool \
  libx11-dev libx11-xcb-dev libxcb1-dev libxcb-keysyms1-dev \
  mesa-common-dev libgl1-mesa-dev libegl1-mesa-dev
mkdir -p third_party
# 官方来源；若目录已存在，应先核对其改动和版本，而不是覆盖。
git clone --branch v1.47 --depth 1 https://github.com/baldurk/renderdoc.git third_party/renderdoc
RD_SRC="$PWD/third_party/renderdoc"
PY_VERSION=$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])')
cmake -S "$RD_SRC" -B "$RD_SRC/build" \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_QRENDERDOC=OFF \
  -DENABLE_PYRENDERDOC=ON -DENABLE_RENDERDOCCMD=ON \
  -DFORCE_PY_VERSION="$PY_VERSION"
cmake --build "$RD_SRC/build" --target renderdoc _renderdoc renderdoccmd -j2
```

如发行版提供 `libpcre3-dev`，可安装以避免额外编译 PCRE。该版本 CMake 会构建其 [定制 SWIG](https://github.com/baldurk/swig/tree/renderdoc-modified-7)，并在缺少 PCRE 开发头时获取 PCRE。需要网络或为 `RENDERDOC_SWIG_PACKAGE` / `RENDERDOC_PCRE_PACKAGE` 指定已核验的本地源码包。普通发行版 SWIG 不是该版本的无条件替代品。内存有限时降低并行度。

使用安装脚本将成对的产物复制到独立目录，并生成文件哈希、源版本和 Python ABI 回执。脚本不下载、不覆盖已有目录，也不把成功安装等同于成功回放。

```sh
.venv/bin/python scripts/install_linux_runtime.py \
  --library "$RD_SRC/build/lib/librenderdoc.so" \
  --binding "$RD_SRC/build/lib/renderdoc.so" \
  --source-url https://github.com/baldurk/renderdoc \
  --source-revision "$(git -C "$RD_SRC" rev-parse HEAD)" \
  --version 1.47 \
  --destination "$PWD/binaries/linux/x64"

RUNTIME="$PWD/binaries/linux/x64"
export RDC_TOOL_RUNTIME_DLL_DIR="$RUNTIME"
export RDC_TOOL_RENDERDOC_PATH="$RUNTIME/pymodules"
export LD_LIBRARY_PATH="$RUNTIME${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
bash bin/rdc-tool --json doctor
```

如果使用已经构建的官方运行库，将 `--library` / `--binding` 换成实际文件，并填写其真实源码版本和 ABI，不能伪造构建回执。`doctor` 会区分记录中的磁盘文件身份与实际加载身份。不要通过 `ctypes` 预加载 `librenderdoc.so`，也不要用伪造的 ABI 文件名强迫另一版本的 Python 加载 binding。

## 3. 图形驱动与无窗口模式

Debian 类系统的软件驱动示例：

```sh
sudo apt-get install libegl1 libgl1-mesa-dri libvulkan1 mesa-vulkan-drivers vulkan-tools
vulkaninfo --summary
```

GLES 无窗口软件路径可尝试：

```sh
export EGL_PLATFORM=surfaceless
export LIBGL_ALWAYS_SOFTWARE=1
bash bin/rdc-tool --daemon-context linux-smoke stdio
```

这些变量不保证任意 GL 捕获兼容。Vulkan 用哪个 ICD 需查看实际安装文件和 `vulkaninfo` 输出；不要在多个设备间静默 fallback。ADB 和 SPIR-V 工具是可选主机工具，通过 PATH 或已有显式覆盖配置发现，不能把 Windows `.exe` 当作 Linux 工具。

## 4. 前台 stdio 会话

每行一个 JSON 请求。初始化后打开文件：

```json
{"id":"init","method":"exec","params":{"operation":"rd.core.init","args":{},"transport":"stdio"}}
{"id":"open","method":"exec","params":{"operation":"rd.capture.open_file","args":{"file_path":"/absolute/sample.rdc","read_only":true},"transport":"stdio"}}
```

从响应读取 `result.data.capture_file_id`，按当前 catalog 的 `rd.capture.open_replay` 参数打开回放，取得 `session_id` 后再调用事件、管线、资源操作。参数和 capability 以 `tools describe` 为准，不硬编码另一个进程的 ID。

- 进度消息可能先于同 ID 的最终响应；需检查内层 `result.ok`，而不只是外层请求投递 `ok`。
- 完成后调用 `rd.core.shutdown`，再发送 `{"id":"stop","method":"shutdown"}`；EOF 也会释放本进程的 native 资源。
- 进程重启后旧会话标为 `requires_restart`，需要关闭并重新打开。持久化的 session ID 不是原 controller 仍存活的证明。
- 前台模式的 `meta.process_identity` 报告 `not_daemon_worker`，不声称 daemon 父进程身份。

不支持回放的 D3D11 文件可使用 [静态读取路径](static-d3d11-inspection.md)，该命令不会建立 replay session。

## 验证范围与参考

单元测试、daemon listener、真实 replay、预览窗口和正式发布是不同验收项。请保留当前测试输出，明确标注 skipped/blocked，不用 mock 测试代替真实 GPU 验证。Linux 候选不会自动认证 Windows 发布包或 Android 设备呈现。

- [RenderDoc v1.47](https://github.com/baldurk/renderdoc/tree/v1.47)，源码修订 `b0e1370309f7d7bf986a73830446ca39d9b8c1fd`。
- [RenderDoc Linux 构建文档](https://github.com/baldurk/renderdoc/blob/v1.47/docs/CONTRIBUTING/Compiling.md)。
- [BANANASJIM/rdc-cli](https://github.com/BANANASJIM/rdc-cli)：Linux 原生库发现及 replay 流程的外部参考，不作为本项目成功保证。
- [发布基线](release-baseline.md)：运行库身份和正式发行验收。
