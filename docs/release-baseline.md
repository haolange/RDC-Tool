# 发布基线 `Release Baseline`

本文是原生运行库身份、发布资格与交付规则的唯一权威。每次能力变更都要让仓库默认 `binaries/`、生成的 catalog、用户文档与 RDC-Agent 消费契约保持一致；`intermediate/` 下的候选只用于隔离验证，不能代替正式打包使用的仓库运行库。

## 当前原生基线

| 项 | 值 |
|---|---|
| RenderDoc | **1.48**，源码 fork `https://github.com/haolange/renderdoc` 的 `dde88226a1cf8145edfe7094a67cbcdab6363d46`（= base `f6aff93…` 与 upstream `282b28b…` 的合并） |
| 已配对目标 | `windows-x64`（DLL/PYD）、`android-arm32`、`android-arm64`（helper APK） |
| 已支持主机布局 | `windows-x64`（`binaries/windows/x64`）、`linux-x64`（`binaries/linux/x64`，正式产物下一轮随同源构建加入） |

RDC-Tool 不自动跟随上游每个版本；新运行库只有在完成同源配对打包、catalog 检查、测试与发布门禁后才成为基线。capture 格式兼容性遵循上游 RenderDoc。

## 运行库身份与能力范围

- `rdc_tool/operation_definitions.py` 是操作契约的唯一真源；`spec/tool_catalog.json` 与 `docs/tool-reference.md` 由它生成。catalog fingerprint 是能力身份，不能用包版本号代替。
- 每个主机运行目录下的 `manifest.runtime.json` 是该目录捆绑文件集与哈希的真源（含 `bundled_python`、`bundled_tools`）。
- `binaries/native_build.json` 是全目标共享的原生构建回执：一份冻结源码产出的所有目标都记录在这一份文件里。`rdc_tool.runtime_identity.native_manifest_status` 与 `rdc-tool --json doctor` 校验它；实际加载的模块路径与哈希是独立的运行时观察。
- “最新”指最近一次提交且所声明能力与捆绑运行库都通过必需检查的发布，不代表自动跟随上游 RenderDoc，也不代表支持所有 API、capture、驱动或设备。
- 能力或行为变更须同步仓库根 `binaries/` 默认运行集、生成的 catalog 与参考文档、受影响文档及 RDC-Agent 消费集成。未受影响且已验证的组件可沿用已记录的身份与证据；本地候选或其他运行目录只是测试证据，不能在发布中代替根运行库。

## 原生构建回执

回执结构：

- `source`：字段必须恰好是 `repository`（https URL）、`revision`（被构建的 40 位提交）、`base_revision`、`upstream_revision`（40 位）与 `tree_sha256`（源码树摘要，64 位）。多余或缺失字段直接判为无效，打包工具同样拒绝而不是静默丢弃。
- `builds`：每个目标一项，目标名唯一且属于 `NATIVE_TARGETS`（全部主机布局 + `android-arm32`/`android-arm64`）。每项记录 `configuration`、`toolchain`、`inputs_sha256`（必须等于 `source.tree_sha256`）与 `outputs`。输出角色：主机目标为 `native_library` 与 `binding_module`（路径由主机布局决定，如 `binaries/linux/x64/librenderdoc.so`），Android 为 `helper_apk`（另记录 APK 版本、signer 证书指纹、包内原生库 SHA256 与 ELF BuildID；读取证书指纹不代表已执行密码学验签）。主机目标还必须有完整 `runtime_files`，覆盖运行目录根部的原生库、Vulkan layer JSON 与 `pymodules/` 全部文件。

校验规则（存在即严格，缺席仅报告）：

- 列出的目标若其输出全部存在，则逐字节核对输出与 `runtime_files`，并要求 layer JSON 为合法对象；结果记为 `verified`。
- 列出的目标若输出全部缺席，记为 `absent`（例如 Windows 发行包里不含 Linux 运行库）；部分存在直接判为 `invalid`。
- 两个 Android helper 同时存在时，signer 证书与版本元数据必须一致。
- 场景按需要的目标集合判定资格：默认是本主机目标加两个 Android helper。需要的目标未列出或缺席时状态为 `unavailable`（并给出 `missing_targets`）；任何已存在的字节与回执矛盾时为 `invalid`。worker 拒绝在 `invalid` 下启动，正式打包与发布验证只接受 `verified`。

## 原生运行库变更

修改 RenderDoc 或 helper 运行内容时，必须从同一份冻结源码构建，并通过同一份回执配对各主机的原生库与绑定（Windows DLL/PYD、Linux `.so`）以及两个 Android helper APK。主机运行文件清单必须覆盖完整原生集合（如 Windows 的 `renderdoc.dll`、`renderdoc.pyd`、`renderdoc.json` 与支持库）。禁止把单个库拷进旧集合、混用不同源码树的产物，或向 PATH、其他安装、SDK、上游二进制添加未经验证的 fallback。

声称运行时验收时，除仓库文件身份外还要记录实际加载或使用的 Python、绑定、原生库与 helper APK。构建元数据或磁盘哈希不能证明运行库已被加载、设备已呈现画面或某个 capture 受支持。签名密钥、构建输入、设备等外部条件缺失时，把对应验收记为阻塞或未验证，不得用候选、清单或本地构建冒充缺失的证据。

## 发布资格与交付

正式发布打包使用干净的已提交检出与仓库根 `binaries/`。`python scripts/package_release.py` 要求原生回执 `verified`，运行源码/仓库运行库门禁，构建完整 ZIP，再校验暂存归档及其身份后才接受输出。脏源码、过期或不完整的运行库身份、包内容不匹配或任何检查失败都会拒绝；不得向包内单独拷贝二进制或混入早期构建产物。

必需的发布 CI 须通过全量测试、catalog/文档与源码门禁、正式打包和完整包校验，然后把校验过的 ZIP 与其 SHA256 作为 GitHub Actions artifact 上传。该 artifact 只是交接物：CI 不创建也不发布 GitHub Release。之后经授权的 Release 必须使用同一个已校验 ZIP 与校验和，CI 校验后不得重建、重打包或重组二进制。发布仍需明确授权。

本地 `--candidate-dir` 输出与 `--runtime-root` 只用于隔离验证：不得覆盖已有目标目录，且必须带有已验证的配对原生身份。通过候选检查不等于获得正式发布资格，也不能作为升级安装来源。

发布 smoke 证据直接经 bash 运行，命令与结果可见：

```bash
bash scripts/smoke_cli.sh --context release-smoke
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context release-smoke
```

smoke 入口写入 `intermediate/logs/smoke_cli.log`，`release_gate.py --require-smoke-reports` 要求其中含 `[smoke] PASS`。preview 几何证据单独记录。完整回放 smoke 使用显式 `.rdc` 样本；仓库内 fixture 仅供测试，不随发行包分发。smoke 证据不能代替包校验或设备呈现证据。
