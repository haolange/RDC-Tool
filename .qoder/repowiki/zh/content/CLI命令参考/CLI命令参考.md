# CLI命令参考

<cite>
**本文引用的文件**
- [rdx/cli.py](file://rdx/cli.py)
- [cli/run_cli.py](file://cli/run_cli.py)
- [bin/rdx.cmd](file://bin/rdx.cmd)
- [install.cmd](file://install.cmd)
- [rdx/cli_batch.py](file://rdx/cli_batch.py)
- [intermediate/runtime-host-evidence/batch.jsonl](file://intermediate/runtime-host-evidence/batch.jsonl)
- [intermediate/runtime-host-evidence/batch-process.jsonl](file://intermediate/runtime-host-evidence/batch-process.jsonl)
- [scripts/smoke_cli.sh](file://scripts/smoke_cli.sh)
- [tests/test_cli_capture_open.py](file://tests/test_cli_capture_open.py)
</cite>

## 更新摘要
**变更内容**
- 新增 Windows 入口点整合：新的 rdx.cmd 启动器与 install.cmd 安装脚本分离
- 新增 JSONL 批量处理功能：通过 batch 命令支持 JSONL 格式的批量操作执行
- 更新批处理命令文档，包含语法、参数、输入输出格式和使用示例
- 增强错误处理和故障排查指南中的批处理相关说明

## 目录
1. [简介](#简介)
2. [项目结构](#项目结构)
3. [核心组件](#核心组件)
4. [架构总览](#架构总览)
5. [详细组件分析](#详细组件分析)
6. [依赖分析](#依赖分析)
7. [性能考虑](#性能考虑)
8. [故障排查指南](#故障排查指南)
9. [结论](#结论)
10. [附录](#附录)

## 简介
本文件为 RDX Agent Tools 的 CLI 命令参考，覆盖基础命令、工具管理命令、会话控制命令、守护进程命令与批量处理命令。内容基于仓库中的 CLI 实现与启动器，提供命令语法、参数、选项、输入输出格式、错误处理、使用示例与最佳实践。读者可据此快速掌握命令用法、组合使用方式以及在不同平台（Windows、POSIX Shell）下的运行方式。

**更新** 新增 Windows 入口点整合与 JSONL 批量处理功能。新的 rdx.cmd 启动器提供了统一的 Windows 入口，install.cmd 专门负责安装流程。新增的 batch 命令支持 JSONL 格式的批量操作执行，适用于自动化脚本和大规模数据处理场景。

## 项目结构
RDX CLI 由三层组成：
- 启动器层：独立的 Python 启动器和 Windows 批处理入口负责环境初始化、依赖检查与版本信息输出。
- 核心 CLI 层：封装了所有命令的解析与执行逻辑，通过守护进程客户端与后端交互。
- 批量处理层：JSONL 格式的批量操作执行引擎，支持流式处理和错误恢复。

```mermaid
graph TB
subgraph "启动器层"
RUNCLI["cli/run_cli.py<br/>独立启动器"]
RDXCMD["bin/rdx.cmd<br/>Windows 批处理入口"]
INSTALLCMD["install.cmd<br/>安装脚本"]
end
subgraph "核心CLI层"
CORECLI["rdx/cli.py<br/>命令解析与执行"]
BATCH["rdx/cli_batch.py<br/>批量处理引擎"]
end
subgraph "数据格式"
JSONL["JSONL 批量输入格式"]
OUTPUT["JSONL 批量输出格式"]
end
RUNCLI --> CORECLI
RDXCMD --> RUNCLI
INSTALLCMD --> RDXCMD
CORECLI --> BATCH
BATCH --> JSONL
BATCH --> OUTPUT
```

**图表来源**
- [cli/run_cli.py:1-290](file://cli/run_cli.py#L1-L290)
- [bin/rdx.cmd:1-12](file://bin/rdx.cmd#L1-L12)
- [install.cmd:1-11](file://install.cmd#L1-L11)
- [rdx/cli.py:1-1779](file://rdx/cli.py#L1-L1779)
- [rdx/cli_batch.py:1-62](file://rdx/cli_batch.py#L1-L62)

**章节来源**
- [cli/run_cli.py:1-290](file://cli/run_cli.py#L1-L290)
- [bin/rdx.cmd:1-12](file://bin/rdx.cmd#L1-L12)
- [install.cmd:1-11](file://install.cmd#L1-L11)
- [rdx/cli.py:1-1779](file://rdx/cli.py#L1-L1779)
- [rdx/cli_batch.py:1-62](file://rdx/cli_batch.py#L1-L62)

## 核心组件
- 基础命令
  - 版本查询：显示工具版本与兼容性信息。
  - 自检诊断：检查运行时目录、Python 布局、RenderDoc 组件、工具目录与守护进程状态等。
  - 补全生成：按 Shell 生成自动补全脚本。
- 工具管理命令
  - 列表与搜索：列出或按关键字搜索已安装工具。
- 守护进程命令
  - 启动、停止、状态查询；支持附加/心跳/分离等高级操作。
- 会话控制命令
  - 预览开关与状态查询；上下文状态查看、更新、列举与清理。
- 通用调用命令
  - 调用任意后端操作，支持 JSON 参数传递与输出格式化。
- **新增** 批量处理命令
  - JSONL 批量执行：读取 JSONL 文件并顺序执行操作，支持只读操作验证和错误处理。
- 文件系统命令
  - VFS 列表、树形浏览、解析路径等。
- 捕获与差异/断言命令
  - 打开捕获文件、查询状态；对管线与图像进行差异与断言。
- CLI Facade命令族
  - 事件、管线、着色器、导出、像素、资源命令，映射到现有的 rd.* 工具。
- TSV投影支持
  - 所有命令支持TSV输出格式，提供结构化数据导出能力

**章节来源**
- [rdx/cli.py:62-94](file://rdx/cli.py#L62-L94)
- [rdx/cli.py:392-516](file://rdx/cli.py#L392-L516)
- [rdx/cli.py:540-547](file://rdx/cli.py#L540-L547)
- [rdx/cli.py:645-648](file://rdx/cli.py#L645-L648)
- [rdx/cli.py:650-706](file://rdx/cli.py#L650-L706)
- [rdx/cli.py:1201-1218](file://rdx/cli.py#L1201-L1218)
- [rdx/cli.py:1721-1723](file://rdx/cli.py#L1721-L1723)
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)

## 架构总览
CLI 的整体调用链如下：

```mermaid
sequenceDiagram
participant U as "用户"
participant L as "启动器(run_cli.py)"
participant W as "Windows入口(rdx.cmd)"
participant C as "核心CLI(rdx/cli.py)"
participant B as "批量处理器(cli_batch.py)"
participant D as "守护进程客户端"
participant S as "后端服务"
U->>W : 执行 rdx (Windows)
U->>L : 执行 rdx (其他平台)
W->>L : 调用 Python 启动器
L->>C : 转交命令解析
alt 批处理命令
C->>B : 执行批量处理
B->>D : 顺序执行 JSONL 操作
D->>S : 调用后端操作
S-->>D : 返回结果
D-->>B : 结果回传
B-->>U : JSONL 输出
else 普通命令
C->>D : 发起守护进程请求
D->>S : 调用后端操作
S-->>D : 返回结果
D-->>C : 结果回传
C-->>U : 格式化输出(JSON/TSV)
end
```

**图表来源**
- [cli/run_cli.py:225-282](file://cli/run_cli.py#L225-L282)
- [bin/rdx.cmd:10-11](file://bin/rdx.cmd#L10-L11)
- [rdx/cli.py:1721-1723](file://rdx/cli.py#L1721-L1723)
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)

**章节来源**
- [cli/run_cli.py:225-282](file://cli/run_cli.py#L225-L282)
- [bin/rdx.cmd:10-11](file://bin/rdx.cmd#L10-L11)
- [rdx/cli.py:1721-1723](file://rdx/cli.py#L1721-L1723)
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)

## 详细组件分析

### 基础命令

#### 版本命令
- 语法
  - rdx version [--json]
- 选项
  - --json：以 JSON 格式输出版本信息
- 输入
  - 无
- 输出
  - 文本模式：打印版本号
  - JSON 模式：返回包含工具版本、架构、入口点与兼容性信息的对象
- 错误处理
  - 无运行时错误，失败情况由上层启动器处理
- 使用示例
  - rdx version
  - rdx version --json

**章节来源**
- [rdx/cli.py:540-547](file://rdx/cli.py#L540-L547)
- [cli/run_cli.py:164-196](file://cli/run_cli.py#L164-L196)

#### 自检诊断命令
- 语法
  - rdx doctor
- 选项
  - --json：以 JSON 格式输出诊断详情
- 输入
  - 无
- 输出
  - 成功：包含 Python 布局、RenderDoc 组件、工具目录、守护进程状态、入口点存在性等字段
  - 失败：返回"设置不完整"的错误对象
- 错误处理
  - 依赖缺失、Python 布局不正确、RenderDoc 组件缺失、工具入口不存在等情况均会触发错误
- 使用示例
  - rdx doctor
  - rdx --json doctor

**章节来源**
- [rdx/cli.py:392-516](file://rdx/cli.py#L392-L516)
- [cli/run_cli.py:198-223](file://cli/run_cli.py#L198-L223)

#### 补全命令
- 语法
  - rdx completion <shell>
- 可选值
  - powershell、bash、zsh、fish
- 输入
  - 无
- 输出
  - 生成对应 Shell 的自动补全脚本文本
- 错误处理
  - 不支持的 Shell 将报错
- 使用示例
  - rdx completion powershell

**章节来源**
- [rdx/cli.py:645-648](file://rdx/cli.py#L645-L648)
- [rdx/cli.py:601-643](file://rdx/cli.py#L601-L643)

### 工具管理命令

#### 工具列表
- 语法
  - rdx tools list [--namespace <ns>] [--limit <n>] [--json]
- 选项
  - --namespace：按命名空间过滤
  - --limit：限制返回数量
  - --json：以 JSON 格式输出
- 输入
  - 无
- 输出
  - 成功：包含工具计数与工具数组（名称、分组、描述、参数名、前置条件）
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx tools list --json
  - rdx tools list --namespace rd.pipeline --limit 5 --json

**章节来源**
- [rdx/cli.py:650-668](file://rdx/cli.py#L650-L668)

#### 工具搜索
- 语法
  - rdx tools search <query> [--limit <n>] [--json]
- 选项
  - --limit：限制返回数量
  - --json：以 JSON 格式输出
- 输入
  - 查询词
- 输出
  - 成功：包含查询词、工具计数与匹配工具数组
- 错误处理
  - 缺少查询词时返回验证错误
- 使用示例
  - rdx tools search pipeline --json
  - rdx tools search shader --limit 10 --json

**章节来源**
- [rdx/cli.py:670-706](file://rdx/cli.py#L670-L706)

### 守护进程命令

#### 守护进程生命周期
- 语法
  - rdx daemon start [--pipe-name <name>] [--owner-pid <pid>]
  - rdx daemon stop
  - rdx daemon status
- 选项
  - --pipe-name：管道名（启动时）
  - --owner-pid：启动时指定拥有者进程 ID（用于自动停止）
- 输入
  - 无（除 start）
- 输出
  - 成功：返回守护进程运行状态与当前状态快照
  - 失败：返回错误对象（含清理提示）
- 错误处理
  - 状态查询异常时尝试清理陈旧状态并重试
- 使用示例
  - rdx daemon start --daemon-context local
  - rdx daemon status --daemon-context local

**章节来源**
- [rdx/cli.py:1201-1218](file://rdx/cli.py#L1201-L1218)
- [rdx/cli.py:250-292](file://rdx/cli.py#L250-L292)

#### 守护进程高级操作
- 语法
  - rdx daemon attach --client-id <id> [--client-type <type>] [--pid <num>] [--lease-timeout-seconds <sec>]
  - rdx daemon heartbeat --client-id <id> [--pid <num>]
  - rdx daemon detach --client-id <id>
  - rdx daemon cleanup
- 输入
  - 客户端标识与可选参数
- 输出
  - 成功：返回相应操作的结果
- 错误处理
  - 无直接错误处理，失败由守护进程客户端包装
- 使用示例
  - rdx daemon attach --client-id cli-001 --daemon-context local

**章节来源**
- [rdx/cli.py:1207-1217](file://rdx/cli.py#L1207-L1217)

### 会话控制命令

#### 预览控制
- 语法
  - rdx session preview on|off|status
- 输入
  - 子命令：on、off、status
- 输出
  - 成功：返回预览状态
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx session preview on
  - rdx session preview status

**章节来源**
- [rdx/cli.py:991-1010](file://rdx/cli.py#L991-L1010)

#### 上下文管理
- 语法
  - rdx context status [--json]
  - rdx context update --key <k> --value <v> [--json]
  - rdx context list [--json]
  - rdx context clear
- 输入
  - update 需要键值对
- 输出
  - 成功：返回上下文快照或操作结果
- 错误处理
  - 无会话时返回"需要会话"的错误提示
- 使用示例
  - rdx context update --key notes --value triaged --json
  - rdx context clear

**章节来源**
- [rdx/cli.py:734-770](file://rdx/cli.py#L734-L770)
- [rdx/cli.py:741-748](file://rdx/cli.py#L741-L748)
- [rdx/cli.py:750-755](file://rdx/cli.py#L750-L755)
- [rdx/cli.py:757-770](file://rdx/cli.py#L757-L770)

### 通用调用命令

#### call 命令
- 语法
  - rdx call <operation> [--args-json <json>|--args-file <path>] [--format json|tsv] [--remote] [--daemon-context <id>]
- 选项
  - --args-json：内联 JSON 参数
  - --args-file：参数文件路径
  - --format：输出格式（json、tsv）
  - --remote：远程模式
  - --daemon-context：守护进程上下文
- 输入
  - 操作名与参数
- 输出
  - 成功：根据 --format 输出 JSON 或 TSV
  - 失败：返回错误对象
- 错误处理
  - 参数互斥校验、JSON 解析失败、TSV 投影缺失等
- 使用示例
  - rdx call rd.session.get_context --args-file ./args.json --format json
  - rdx call rd.vfs.ls --args-json '{"path":"/"}' --format tsv

**章节来源**
- [rdx/cli.py:821-832](file://rdx/cli.py#L821-L832)
- [rdx/cli.py:313-378](file://rdx/cli.py#L313-L378)

### **新增** 批量处理命令

#### batch 命令
- 语法
  - rdx batch <jsonl_file> [--remote]
- 选项
  - --remote：远程模式
- 输入
  - JSONL 文件格式：每行一个 JSON 对象，包含 operation 和 args 字段
- 输出
  - JSONL 格式：每行一个操作结果，包含 ok、data、error、meta.batch 等字段
- 错误处理
  - 文件读取错误、JSON 解析错误、操作验证错误、中断处理
- 使用示例
  - rdx batch operations.jsonl
  - rdx batch operations.jsonl --remote

**更新** 新增 JSONL 批量处理功能，支持只读操作的批量执行。每个操作必须包含 operation 和 args 字段，系统会自动验证操作类型和参数。

**章节来源**
- [rdx/cli.py:1721-1723](file://rdx/cli.py#L1721-L1723)
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)
- [intermediate/runtime-host-evidence/batch.jsonl:1-3](file://intermediate/runtime-host-evidence/batch.jsonl#L1-L3)
- [intermediate/runtime-host-evidence/batch-process.jsonl:1-3](file://intermediate/runtime-host-evidence/batch-process.jsonl#L1-L3)

### 文件系统命令

#### VFS 命令族
- 语法
  - rdx vfs ls|cat|tree|resolve [--path <path>] [--depth <n>] [--format json|tsv] [--daemon-context <id>]
- 选项
  - --path：目标路径
  - --depth：树形深度（tree）
  - --format：输出格式
  - --daemon-context：守护进程上下文
- 输入
  - 子命令与路径
- 输出
  - 成功：根据 --format 输出
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx vfs ls --path / --format tsv
  - rdx vfs tree --path / --depth 2 --format json

**章节来源**
- [rdx/cli.py:834-842](file://rdx/cli.py#L834-L842)

### 捕获与差异/断言命令

#### 捕获命令
- 语法
  - rdx capture open --file <path> [--frame-index <n>] [--preview] [--remote-id <handle>] [--daemon-context <id>]
  - rdx capture status
- 选项
  - --file：捕获文件路径
  - --frame-index：帧索引
  - --preview：打开预览
  - --remote-id：显式指定远程句柄，强制使用远程后端进行回放（无本地回退）
- 输入
  - 捕获文件路径与可选参数
- 输出
  - 成功：返回捕获状态与上下文快照，包含 backend 类型（local/remote）和 remote_id 信息
  - 失败：返回多步骤失败时的详细错误与恢复建议
- 错误处理
  - 多步骤失败时返回详细错误与恢复建议
- 使用示例
  - rdx capture open --file D:\path\capture.rdc --frame-index 0 --preview
  - rdx capture open --file D:\path\capture.rdc --remote-id remote_abc --frame-index 0
  - rdx capture status

**更新** 新增 `--remote-id` 参数支持，允许显式指定远程句柄进行远程回放功能。当设置此参数时，系统将强制使用指定的远程后端，不会回退到本地 OpenCapture。

**章节来源**
- [rdx/cli.py:844-1222](file://rdx/cli.py#L844-L1222)
- [rdx/cli.py:717-725](file://rdx/cli.py#L717-L725)
- [rdx/cli.py:1442-1446](file://rdx/cli.py#L1442-L1446)
- [tests/test_cli_capture_open.py:95-157](file://tests/test_cli_capture_open.py#L95-L157)

#### 差异与断言
- 语法
  - rdx diff pipeline|image <args...>
  - rdx assert pipeline|image <args...>
- 输入
  - 具体子命令与参数（详见后端工具定义）
- 输出
  - 成功：返回比较/断言结果
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx diff pipeline --args-json '{"..."}' --format json
  - rdx assert image --args-json '{"..."}' --format json

**章节来源**
- [rdx/cli.py:1068-1141](file://rdx/cli.py#L1068-L1141)
- [rdx/cli.py:1107-1141](file://rdx/cli.py#L1107-L1141)

### CLI Facade命令族

#### 事件命令（event）
- 语法
  - rdx event <subcommand> [args...] [--format json|tsv]
- 子命令
  - list：列出事件
  - get：获取特定事件
  - filter：按条件过滤事件
- 选项
  - --format：输出格式（json、tsv）
- 输入
  - 事件操作参数
- 输出
  - 成功：根据 --format 输出事件数据
  - 失败：返回错误对象
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx event list --format tsv
  - rdx event get --event-id 123 --format json

**章节来源**
- [rdx/cli.py:1219-770](file://rdx/cli.py#L1219-L770)

#### 管线命令（pipeline）
- 语法
  - rdx pipeline <subcommand> [args...] [--format json|tsv]
- 子命令
  - list：列出管线
  - get：获取特定管线
  - validate：验证管线配置
- 选项
  - --format：输出格式（json、tsv）
- 输入
  - 管线操作参数
- 输出
  - 成功：根据 --format 输出管线数据
  - 失败：返回错误对象
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx pipeline list --format tsv
  - rdx pipeline validate --pipeline-id main --format json

**章节来源**
- [rdx/cli.py:1219-770](file://rdx/cli.py#L1219-L770)

#### 着色器命令（shader）
- 语法
  - rdx shader <subcommand> [args...] [--format json|tsv]
- 子命令
  - list：列出着色器
  - get：获取特定着色器
  - disassemble：反汇编着色器代码
- 选项
  - --format：输出格式（json、tsv）
- 输入
  - 着色器操作参数
- 输出
  - 成功：根据 --format 输出着色器数据
  - 失败：返回错误对象
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx shader list --format tsv
  - rdx shader disassemble --shader-id vertex --format json

**章节来源**
- [rdx/cli.py:1219-770](file://rdx/cli.py#L1219-L770)

#### 导出命令（export）
- 语法
  - rdx export <subcommand> [args...] [--format json|tsv]
- 子命令
  - capture：导出捕获数据
  - screenshot：导出截图
  - geometry：导出几何数据
- 选项
  - --format：输出格式（json、tsv）
- 输入
  - 导出操作参数
- 输出
  - 成功：根据 --format 输出导出数据
  - 失败：返回错误对象
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx export capture --output-dir ./exports --format tsv
  - rdx export screenshot --frame-index 0 --format json

**章节来源**
- [rdx/cli.py:1219-770](file://rdx/cli.py#L1219-L770)

#### 像素命令（pixel）
- 语法
  - rdx pixel <subcommand> [args...] [--format json|tsv]
- 子命令
  - sample：采样像素值
  - compare：比较像素数据
  - histogram：生成像素直方图
- 选项
  - --format：输出格式（json、tsv）
- 输入
  - 像素操作参数
- 输出
  - 成功：根据 --format 输出像素数据
  - 失败：返回错误对象
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx pixel sample --x 100 --y 100 --format tsv
  - rdx pixel compare --reference ./ref.png --format json

**章节来源**
- [rdx/cli.py:1219-770](file://rdx/cli.py#L1219-L770)

#### 资源命令（resource）
- 语法
  - rdx resource <subcommand> [args...] [--format json|tsv]
- 子命令
  - list：列出资源
  - get：获取特定资源
  - stats：获取资源统计信息
- 选项
  - --format：输出格式（json、tsv）
- 输入
  - 资源操作参数
- 输出
  - 成功：根据 --format 输出资源数据
  - 失败：返回错误对象
- 错误处理
  - 无运行时错误
- 使用示例
  - rdx resource list --format tsv
  - rdx resource stats --resource-id texture0 --format json

**章节来源**
- [rdx/cli.py:1219-770](file://rdx/cli.py#L1219-L770)

### TSV投影支持

#### TSV输出格式
- 语法
  - 所有命令支持 --format tsv 选项
- 功能特性
  - 结构化数据导出
  - 机器可读格式
  - 支持批量处理
- 使用示例
  - rdx tools list --format tsv
  - rdx event list --format tsv
  - rdx pipeline list --format tsv

**章节来源**
- [rdx/cli.py:313-378](file://rdx/cli.py#L313-L378)

## 依赖分析
- CLI 与启动器的耦合
  - 启动器负责环境初始化与依赖检查，核心 CLI 仅处理命令解析与执行。
- **新增** Windows 入口点整合
  - bin/rdx.cmd 提供统一的 Windows 入口，install.cmd 专门处理安装流程。
- CLI 与守护进程的耦合
  - 大多数命令通过守护进程客户端转发到后端服务，保证一致性与隔离性。
- **新增** 批量处理模块集成
  - JSONL 批量处理作为独立模块集成到 CLI 执行流程中，支持只读操作验证。
- 平台入口
  - Windows 提供 rdx.cmd 批处理入口；POSIX 环境通过 Python 启动器。

```mermaid
graph LR
RUNCLI["cli/run_cli.py"] --> CORECLI["rdx/cli.py"]
RDXCMD["bin/rdx.cmd"] --> RUNCLI
INSTALLCMD["install.cmd"] --> RDXCMD
CORECLI --> BATCH["rdx/cli_batch.py"]
CORECLI --> DAEMON["守护进程客户端"]
BATCH --> JSONL["JSONL 处理"]
```

**图表来源**
- [cli/run_cli.py:225-282](file://cli/run_cli.py#L225-L282)
- [bin/rdx.cmd:10-11](file://bin/rdx.cmd#L10-L11)
- [install.cmd:4-7](file://install.cmd#L4-L7)
- [rdx/cli.py:1721-1723](file://rdx/cli.py#L1721-L1723)
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)

**章节来源**
- [cli/run_cli.py:225-282](file://cli/run_cli.py#L225-L282)
- [bin/rdx.cmd:10-11](file://bin/rdx.cmd#L10-L11)
- [install.cmd:4-7](file://install.cmd#L4-L7)
- [rdx/cli.py:1721-1723](file://rdx/cli.py#L1721-L1723)
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)

## 性能考虑
- 输出格式选择
  - TSV 适合批量处理与脚本解析，但要求后端提供投影；JSON 更通用。
- **新增** 批量处理性能优化
  - JSONL 批量处理采用流式读取，避免大文件内存占用
  - 支持信号中断处理，确保优雅退出
  - 只读操作验证减少不必要的写操作开销
- 超时策略
  - 守护进程执行超时依据操作类型动态计算，避免长时间阻塞。
- I/O 优化
  - 参数文件读取采用 UTF-8-SIG 支持，减少编码问题。
- 进程生命周期
  - 启动时可指定 owner-pid，便于自动停止与资源回收。

**章节来源**
- [rdx/cli.py:313-378](file://rdx/cli.py#L313-L378)
- [rdx/cli.py:226-247](file://rdx/cli.py#L226-L247)
- [rdx/cli.py:1202-1205](file://rdx/cli.py#L1202-L1205)
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)

## 故障排查指南
- 依赖缺失
  - 启动器检测到缺失依赖时会输出错误并返回非零退出码；doctor 命令可快速定位问题。
- **新增** Windows 入口点问题
  - rdx.cmd 启动失败时检查 Python 可执行文件是否存在
  - install.cmd 安装失败时检查 PowerShell 执行策略和权限
- 守护进程异常
  - status 命令失败时会尝试清理陈旧状态并重试；必要时手动执行 cleanup。
- 参数错误
  - --args-json 与 --args-file 互斥；TSV 输出需后端提供投影。
- 会话缺失
  - 未打开捕获或未指定 session-id 时，相关命令会返回"需要会话"的错误提示。
- **新增** 批量处理问题
  - JSONL 文件格式错误时检查每行是否包含 operation 和 args 字段
  - 只读操作限制：批量处理仅接受只读操作，写操作会被拒绝
  - 中断处理：Ctrl+C 会优雅终止批量处理并返回适当的状态码
- 自动补全
  - 生成对应 Shell 的补全脚本，确保命令与参数可被正确补全。

**章节来源**
- [cli/run_cli.py:238-253](file://cli/run_cli.py#L238-L253)
- [bin/rdx.cmd:6-9](file://bin/rdx.cmd#L6-L9)
- [install.cmd:4-7](file://install.cmd#L4-L7)
- [rdx/cli.py:250-292](file://rdx/cli.py#L250-L292)
- [rdx/cli.py:178-208](file://rdx/cli.py#L178-L208)
- [rdx/cli.py:313-378](file://rdx/cli.py#L313-L378)
- [rdx/cli.py:757-770](file://rdx/cli.py#L757-L770)
- [rdx/cli.py:601-643](file://rdx/cli.py#L601-L643)
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)

## 结论
本参考文档系统梳理了 RDX CLI 的全部命令族，明确了语法、参数、选项、输入输出格式与错误处理策略，并提供了跨平台入口与最佳实践。**新增的 Windows 入口点整合（rdx.cmd 和 install.cmd 分离）提供了更好的用户体验和安装流程管理。新增的 JSONL 批量处理功能（batch 命令）为自动化脚本和大规模数据处理提供了强大的支持，支持只读操作的批量执行、错误处理和优雅中断。** 建议在自动化脚本中优先使用 --json 输出，配合 doctor 命令进行环境自检，结合会话与上下文管理命令完成端到端工作流。对于批量处理场景，建议使用 JSONL 格式组织操作序列，利用其流式处理能力高效处理大量数据。

## 附录

### 命令别名与快捷方式
- Windows
  - rdx.cmd：推荐的默认入口
  - install.cmd：安装脚本
- POSIX
  - Python 启动器：cli/run_cli.py
- 环境变量
  - RDX_TOOLS_ROOT：工具根目录
  - RDX_CONTEXT_ID：默认守护进程上下文
  - RDX_LAUNCHER_PROG：启动器程序名（仅启动器）

**章节来源**
- [cli/run_cli.py:16-42](file://cli/run_cli.py#L16-L42)
- [cli/run_cli.py:82-84](file://cli/run_cli.py#L82-L84)
- [bin/rdx.cmd:3-5](file://bin/rdx.cmd#L3-L5)
- [install.cmd:3-7](file://install.cmd#L3-L7)

### 自动化脚本使用指导
- 示例脚本
  - scripts/smoke_cli.sh：演示从上下文清理、捕获打开、VFS 列表到工具列表的完整流程
- 最佳实践
  - 明确 --daemon-context，避免默认上下文冲突
  - 使用 --json 输出便于脚本解析
  - 在捕获操作前先 context clear，确保干净状态
  - 利用 TSV 格式进行批量数据处理
  - 使用 CLI Facade 命令简化常用操作
  - 使用 --remote-id 参数进行远程回放时，确保远程句柄的有效性
  - **新增** 使用 batch 命令进行 JSONL 格式的批量操作执行

**章节来源**
- [scripts/smoke_cli.sh:176-195](file://scripts/smoke_cli.sh#L176-L195)

### **新增** 批量处理使用示例

#### JSONL 批量处理示例
```bash
# 创建 JSONL 批量操作文件
echo '{"operation": "rd.session.get_replay_events", "args": {"session_id": "sess_123"}}' > ops.jsonl
echo '{"operation": "rd.vfs.ls", "args": {"path": "/"}}' >> ops.jsonl

# 执行批量处理
rdx batch ops.jsonl

# 带远程模式的批量处理
rdx batch ops.jsonl --remote
```

#### 批量处理最佳实践
```bash
# 验证 JSONL 文件格式
python -c "import json; [json.loads(line) for line in open('ops.jsonl')]"

# 执行批量处理并检查结果
rdx batch ops.jsonl && echo "批量处理成功" || echo "批量处理失败"

# 处理中断的批量任务
rdx batch ops.jsonl &
PID=$!
sleep 5
kill $PID  # Ctrl+C 等效操作
wait $PID
```

**章节来源**
- [rdx/cli_batch.py:17-62](file://rdx/cli_batch.py#L17-L62)
- [intermediate/runtime-host-evidence/batch.jsonl:1-3](file://intermediate/runtime-host-evidence/batch.jsonl#L1-L3)
- [intermediate/runtime-host-evidence/batch-process.jsonl:1-3](file://intermediate/runtime-host-evidence/batch-process.jsonl#L1-L3)

### **新增** Windows 入口点使用示例

#### rdx.cmd 启动器示例
```cmd
@echo off
REM 使用 rdx.cmd 执行命令
cd C:\path\to\RDC-Agent-Tools
bin\rdx.cmd version
bin\rdx.cmd doctor --json
bin\rdx.cmd tools list --json
```

#### install.cmd 安装脚本示例
```cmd
@echo off
REM 使用 install.cmd 进行安装
cd C:\path\to\RDC-Agent-Tools
install.cmd
REM 或使用 PowerShell 参数
install.cmd -Action install -AddToPath
```

**章节来源**
- [bin/rdx.cmd:1-12](file://bin/rdx.cmd#L1-L12)
- [install.cmd:1-11](file://install.cmd#L1-L11)