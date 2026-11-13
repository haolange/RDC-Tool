# Linux 截帧读取与回放：实际路径和边界

Linux 前端兼容、解析 RDC、创建图形设备、执行 shader、回放整帧、调试原像素是不同能力。不能用其中一项的成功代替另一项。本页解释当原生回放不支持某份截帧时该选择什么，不承诺任意 RDC 都能在软件 GPU 上重放。

## 选择路径

| 目标 | 路径 | 需要的软件 | 当前边界 |
|---|---|---|---|
| Linux OpenGL/OpenGLES 截帧回放 | RDC-Tool → Linux RenderDoc → OpenGL/EGL 驱动 | 匹配的 RenderDoc 原生库/Python binding、OpenGL/EGL 驱动 | 曾实际验证 GLES 事件读取、纹理读回和关闭会话；依赖截帧所需扩展 |
| Linux Vulkan 截帧回放 | RDC-Tool → Linux RenderDoc → Vulkan ICD | 匹配的 RenderDoc、Vulkan loader、兼容 ICD | 取决于设备功能、扩展和内存布局；软件 ICD 不保证能回放其他厂商捕获 |
| D3D11 RDC 的静态数据提取 | `inspect-rdc` → RenderDoc 容器解压 → 有界 Python 解析 | 匹配的 Linux RenderDoc 库/binding；无需 replay GPU | 当前仅支持文档列出的序列化版本，不能得到任意 draw 的最终状态 |
| D3D11 的正常 RenderDoc 回放 | 在支持 D3D11 的 Windows 环境使用 RenderDoc/RDC-Tool | Windows D3D11 后端与兼容驱动 | 本 Linux 分支没有增加此后端；远端连接也需实际兼容的服务 |
| 特定 D3D11 捕获的 Linux 执行研究 | 从捕获恢复调用/资源 → 自定义 C++ harness → DXVK Native → Vulkan | DXVK Native、SDL3、Vulkan loader/ICD、编译器，加针对捕获编写的代码 | 研究路径，**不是** `inspect-rdc` 后自动完整回放；不在本仓库提供通用转换器 |

[Linux 安装与启动](linux-native.md)和[静态解析](static-d3d11-inspection.md)是本分支可直接使用的入口。

## 为什么软件 GPU 不能直接解决 D3D11 RDC 回放

Linux RenderDoc 的回放驱动必须先识别并实现捕获 API。安装 lavapipe/llvmpipe 只提供 Vulkan/OpenGL 的实现，不会给 RenderDoc 增加 D3D11 replay driver。Linux 下 D3D11 容器元数据可读，但 `OpenCapture` 仍可能返回 `API used in this capture is unsupported`。把 Windows DLL 改名、设置 `LD_LIBRARY_PATH` 或安装 DXVK 不会改变这一事实。

DXVK Native 实现的是 **D3D11 调用到 Vulkan 的执行**，并不读取 RenderDoc 的 `.rdc` 文件。必须另行解析原始事件、资源初始内容、Map/Unmap、状态绑定、间接参数、SO/CS 生产链及生命周期，再生成合法 D3D11 调用。只上传最终 VB/IB 或某个 after 纹理，只能称快照实验，不能称原生产链回放。

## DXVK Native 研究环境安装

以下是已使用的环境类型：Linux x86-64、DXVK Native 3.1.1、SDL3、Mesa lavapipe。具体发行版包版本和硬件不同会改变行为。下列安装只提供运行环境，不包含捕获特定 harness 或游戏资产。

Debian 13 类系统的基础依赖示例（其他发行版使用对应官方包）：

```sh
sudo apt-get update
sudo apt-get install build-essential pkg-config curl ca-certificates \
  libvulkan1 libvulkan-dev mesa-vulkan-drivers vulkan-tools libsdl3-0
vulkaninfo --summary
```

从 [DXVK 官方 v3.1.1 Release](https://github.com/doitsujin/dxvk/releases/tag/v3.1.1) 下载与系统 ABI 匹配的 **native** 归档。不要误用只含 Windows DLL 的归档。先核对官方发布信息，再在独立目录解压。已使用的 native 归档提供 `usr/include/dxvk`、`usr/lib/libdxvk_d3d11.so` 和 `libdxvk_dxgi.so`。

```sh
mkdir -p third_party/dxvk-native
# 用实际下载的 native 归档路径替换，不从未知来源取二进制。
tar -xf /path/to/dxvk-native-release.tar.gz -C third_party/dxvk-native
DXVK_ROOT="$PWD/third_party/dxvk-native/usr"
# harness.cpp 需要自行提供；它不是 RDC-Tool 自动生成的文件。
c++ -std=c++17 -O0 -I "$DXVK_ROOT/include/dxvk" harness.cpp \
  -L "$DXVK_ROOT/lib" -ldxvk_d3d11 -ldxvk_dxgi \
  -Wl,-rpath-link,"$DXVK_ROOT/lib" -o harness

export LD_LIBRARY_PATH="$DXVK_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export DXVK_WSI_DRIVER=SDL3
export SDL_VIDEODRIVER=offscreen
export XDG_CACHE_HOME="$PWD/.cache"
export DXVK_LOG_PATH="$PWD/dxvk-logs"
mkdir -p "$XDG_CACHE_HOME" "$DXVK_LOG_PATH"
# 在 /usr/share/vulkan/icd.d 中查找实际存在的 lavapipe JSON，勿猜文件名。
ls /usr/share/vulkan/icd.d
# 可选：export VK_DRIVER_FILES=/absolute/path/to/lvp_icd.json
./harness
```

注意：

- 使用 SDL3 的 `offscreen`；`dummy` 不等价于能创建 Vulkan 设备。
- `XDG_CACHE_HOME` 必须可写。缓存目录只读曾使首次 shader 创建中止，即使 buffer 创建测试已成功。
- native 归档的 glibc、libstdc++、SDL3 等依赖必须与系统匹配。使用 `ldd` 检查实际 `.so`，不要混装不同发行版的库后假定兼容。
- 原生设备创建、buffer copy、shader 创建和 dispatch 都应分别验证。一个空 query 成功不能证明原 shader 被正确执行。

## 已观察到的兼容问题

研究性执行曾实际构建连续 SO → CS → 原 VS/PS 调用链，并在多个事件边界与捕获导出值比较。它不是通用 RDC replay 功能，也没有建立任意原像素的 RenderDoc 单步调试能力。本仓库不发布私有截帧、纹理、完整游戏 shader 或捕获特定 harness。

以下问题说明为何不能承诺仅安装依赖就还原画面：

1. **各向异性采样的非有限结果。** 特定 Mesa 25.0.7 软件路径中，固定 UV、1×1 白纹理和隐式各向异性采样即可复现 NaN；同 shader 的仿射 UV 对照正确。独立的采样数下限保护版消除了该实验的 NaN，并通过正常采样对照。此研究补丁不等于已被上游接受的正式驱动修复，本分支不自动修改系统 Mesa。
2. **warp/subgroup 同步假设。** 一份捕获的跨块前缀扫描依赖 32-lane 共享内存执行模式，而测试设备 subgroup 为 8，出现影响索引内容和画面的非确定性。独立同步合法的兼容 CS 可以匹配受限输入合同，但它是替换 shader 的兼容路径，不是原 CS 已修复。不能在分歧分支中随意增加工作组屏障。
3. **量化、插值和退化输入。** 即使拓扑正确，也可能因 10-bit 存储转换、子像素位置量化或常量 UV 下奇异归一化产生差异。加 epsilon、强制 LOD0 或改变舍入可能同时改善和退化像素，不能自动作为保真修复。

若需要这类研究，应冻结原始路径，在独立副本中改动，分别保留：资源与调用来源、实际执行计数、完整 VS 属性/有向三角形集合、附件比较、未知或缺失参考、失败样本。索引排序变化并不自动等价；只有拓扑、属性及对应输出共同通过，才可限定地接受顺序变化。

## 成功标准

- `doctor` 成功：环境和加载身份检查，不是 replay 成功。
- `inspect-rdc` 成功：静态解析，不是创建 replay session。
- shader 翻译成功：静态转换，不证明跨驱动语义相同。
- harness 退出码为 0：需结合实际 draw/dispatch 和结果验证，不能单凭退出码宣称还原。
- 同一程序独立重跑相同：可复现性，不等于与原捕获相同。
- 只有对真实、同资源、同事件边界的参考逐项比较，才可声明该范围内的匹配；缺参考必须明确注明。

## 跨机器复现边界

软件 Vulkan / DXVK Native 的输出不保证跨 CPU、LLVM/JIT 或驱动版本逐字节一致。迁移环境时记录 CPU、LLVM、Mesa、DXVK 与 RenderDoc 的版本和构建指纹；按附件格式统计差异（如 8-bit 通道 ±1），同时保留原基线，不应静默替换 hash。已保存二进制一致也不能单独证明像素输出一致。
