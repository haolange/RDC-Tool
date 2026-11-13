# D3D11 RDC 静态读取（实验性）

`inspect-rdc` 直接读取容器和 D3D11 序列化内容，不创建 replay device，不需要 Wine、GPU 或监听 socket。它**不是**帧重建、像素单步调试或任意 draw 状态恢复。

## 前提与运行

按 [Linux 安装文档](linux-native.md) 准备匹配的 RenderDoc 原生库、Python binding 和运行库回执。虽然没有 GPU 回放，读取及解压容器仍使用 RenderDoc native API，不是完全不依赖原生库的纯 Python 命令。

```sh
RDC_TOOL_PYTHON="$PWD/.venv/bin/python" bash bin/rdc-tool inspect-rdc \
  /absolute/capture.rdc --output-dir /absolute/new-empty-inspection
```

当前只接受 **D3D11 FrameCapture section version 20**。未知布局拒绝，不尝试猜测。解压后 section 限额 1 GiB、chunk 限额 100,000；native API 会整体解压 section，需要预留数 GiB 内存。限制不代表 native 解压阶段已成为流式或完全防止恶意文件的资源耗尽，未知来源捕获应在隔离环境读取。

输出目录必须为空。错误时保留部分产物以便诊断，不写成功 manifest，CLI 返回非零。源 RDC 从不写入。临时解压文件在退出时关闭并清理，运行库身份检查仍生效。

## 输出及含义

- `inspection.json`：支持范围，以及明确的 `replay_verified: false`。
- `chunks.json`：序列化 chunk 顺序、方法名及字节偏移。**chunk 序号不是 RenderDoc event ID**。
- `shaders.json` / `shaders/*.dxbc`：普通 VS/HS/DS/GS/PS/CS，以及包含 Stream Output 声明的 GS bytecode、结构检查、哈希、ResourceId、捕获的 debug name 和 class linkage。
- SO shader 的 `stream_output` 保留声明、stride 和 rasterized stream；声明字段为 `stream`、`semantic`（`null` 表示 gap）、`index`、`start_component`、`component_count`、`output_slot`。这是原始静态描述，不执行 SO，也不推导捕获未提供的 stride。
- `buffers.json` / `buffers/*.bin`：序列化初始 buffer 描述及数据。`initial_data_supplied` 区分创建时实际提供的数据与合成初始填充值；后续捕获时补丁也可能改变序列化初始内容。它们**不是**某个选定 draw 的当前 buffer。
- `resource-names.json`，以及存在时的 `embedded-thumbnail.png`。内嵌缩略图不是本次重放输出。

提取内容不等于完整资源状态。纹理全 mip、Map/Unmap 覆盖、复制、清除、SO/CS 生产链、间接参数、绑定和生命周期必须另行准确处理，才能构建某个事件的可执行输入。不要把初始 buffer 或捕获 after 图像当作真实生产链输出。

## 静态 shader 转换

Debian 类系统可安装官方包（其他发行版使用相应包名）：

```sh
sudo apt-get install vkd3d-compiler spirv-tools spirv-cross
.venv/bin/python scripts/convert_static_shaders.py /absolute/new-empty-inspection
```

脚本核对输入哈希，将 DXBC 转为 SPIR-V，执行 `spirv-val`，并输出反汇编和 GLSL。结果在 `shader-analysis`，非空目录不会被覆盖；每项返回码和诊断被记录。需要这四个程序位于 PATH：`vkd3d-compiler`、`spirv-val`、`spirv-dis`、`spirv-cross`。

转换成功不证明原帧回放成功，也不证明跨驱动语义等价。生成 GLSL 不是原 HLSL 源代码，某些 shader 或目标环境可能无法转换，必须检查逐项结果而非只看是否生成文件。

## 与 D3D11 回放的关系

Linux RenderDoc 缺少 D3D11 replay backend。静态提取不会补上这个后端。研究性 DXVK Native 执行可以使用提取的数据，但需要另写、验证事件与资源恢复逻辑，见 [实际可运行路径与依赖](linux-replay-paths.md)。本命令不承诺自动生成该执行程序。

格式参考来自 RenderDoc v1.47 的 `serialise/serialiser.h`、`driver/d3d11/d3d11_common.h`、`d3d11_device_wrap.cpp` 和 `d3d11_device.cpp`，修订 `b0e1370309f7d7bf986a73830446ca39d9b8c1fd`。RenderDoc 为 MIT 许可；本仓库不包含用于研究的私有捕获或游戏资产。
