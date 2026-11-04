## RDC-Tool 1.0.2 稳定发行回执（2026-09-23）

- `v1.0.2` tag 与发行源码指向 `07f613f3420d7a7b7480f5a8114c7ebc9f13c3b3`；main CI run [35770638452](https://github.com/haolange/RDC-Tool/actions/runs/35770638452) 通过。
- Windows x64 独立包 `rdc-tool-1.0.2-windows-x64.zip` 已通过包校验及完整 `release_gate.py`（overall PASS，3130 个文件）；GitHub Release [v1.0.2](https://github.com/haolange/RDC-Tool/releases/tag/v1.0.2) 两项资产 digest 与本地一致：ZIP `a7480ad08080e41c8133c2e9021bee1b5c8be260a70f57e9656bb0156680b1ae`，`SHA256SUMS` `4cf27faed3dd0396fbfa87950af1d2d736a0814e20470668caf48ded237d6f48`。
- 本地仅保留当前正式候选 ZIP 与 checksum；已清理本轮旧候选和之前 timeout 调查的过期 1.0.1 候选。`.qoder` 中现存用户修改保持原样。

## 2026-11-04 原生回放交付与上传

本轮交付：修复原生 Pixel History 多 subpass 回放，查清已定位的 Store/Don't Care 现象；同步维护源码、仓库默认运行环境、Tools/Agent 契约与正式打包门禁。用户追加授权清理和提交推送：Tools/Agent 上传 main，RenderDoc 上传现有 v1.x；不创建/切换分支、不强推、不创建 tag 或 GitHub Release。原 capture、用户数据、Agent .cursor、在用依赖与服务保持受保护。

| 任务 | 依赖 | 状态 | 交付及验收 |
|---|---|---|---|
| T0 固定旧基线 | — | 通过 | 三库、设备、旧产物及 capture 身份固定；不重复触发旧 PH 崩溃 |
| T1 同步维护源码 | T0 | 通过 | v1.x/f6aff93bc 合入官方282b28b3，保留维护功能，29冲突按行为解决且无unmerged |
| T2 修复多 subpass | T1 | 通过 | 完整拓扑与逻辑/物理推进协调，处理附件、resolve、descriptor/layout/barrier及恢复；原生与Android数值/恢复通过 |
| T3 Store 异常收敛 | T0,T2 | 通过 | 2229/pass2220/颜色804479原始load=DONT_CARE、store=STORE；图案来自load，2237结束后像素为正常场景。保留原始rpinfo再归一化并区分Begin load/End store，无清零或隐藏诊断 |
| T4 同源运行环境 | T2,T3 | 通过 | Python、DLL/PYD、双ABI APK、ADB/shader工具整套匹配；实际CLI/Agent加载、APK签名/so BuildID及受限环境启动分别核验 |
| T5 Tools 全操作 | T4 | 通过 | canonical129项/980d49d7…a90f，120项有实际运行证据，9项N/A；最终完整1176 tests/2subtests（目录检查修复另有31项定向复验）、完整source gate及整包验证通过 |
| T6 Agent 消费 | T4,T5 | 通过 | 同安装绑定、busy保护、真实画面、事件恢复、Close/Cancel/显式重连/断连通过；3440 tests/4既有opt-in默认跳过，受影响测试、coverage-ratchet/type/lint/gates/build通过 |
| T7 文档与资源清理 | T5,T6 | 通过 | 自有native/debugger/QA/forward已退出；设备备份与调试器、QA/测试树已清理，桌面启动权交还；既有ADB保留 |
| T8 仓库默认环境同步 | T4–T7 | 通过 | 根binaries的3009文件与候选逐项hash匹配，原CMD入口实加载1.48；修复原生JSON生成token带CR、严格JSON内容门禁及Git字节保护 |
| T9 发布规则与强制门禁 | T8 | 通过 | AGENTS写硬规则、release-baseline写机制；正式打包要求clean commit、source/native/整包验证，同包实际导入及精确路径核对，源码/产物漂移拒绝、发布三件失败回滚；CI全测/严格doctor通过才上传验收包，不自动Github发布 |
| T10 精简交付与推送 | T0–T9 | 通过 | 已清理约7.60GiB原生缓存、231份过渡回执及最后测试/验证ZIP；Native dde88226a→v1.x、Agent f3cddd56→main、Tools实现及修复1aa16a8→main均已普通推送。Agent CI41838905324已成功；Tools首轮CI的生成目录误判已修正并补真实按需创建验证，31定向测试/独立复核通过，最新CI状态单列、不冒称通过。 |

### 根因与实际修复

PH原先中断多subpass后恢复为单subpass pass，随后继续原始NextSubpass而崩溃；修复完整恢复与推进机制，不禁用PH、不返回假空或自动重试。Tools同时修复安装空终态、捕获传输/只读缓存、daemon归属与退出、Android target transport、CaptureOptions、VFS/stage/shader及GPU计时分类；ADB清理收敛到完整带长度协议authority，失败保留lease。Agent同步错误主因、owning lease及恢复消费。

### 验证范围

- Native：74 cases/21763302 assertions、官方PH全case、Load_Store_None/Dynamic_Rendering 2/2、Release数值/恢复和合法fixture实际Khronos1.4.341零消息/VUID。
- BlackHair/Adreno：1691/2236/1684三组PH分别27/80/60行，末值与独立前后像素读回精确一致，事件/replacement恢复；最终拓扑4087条，877成功Create、1092对Begin/End、96 Next，无新增未归因提前End或越界Next。
- 该capture原始RP3123定义7 subpass，但chunk4410 Begin后紧接4411 End、无Next/draw。用户批准保留语义；最终观察到的15次提前End均归于这处原始缺陷，不能宣称BlackHair全部调用合法。观察仅覆盖最近Begin→Next/End拓扑，不等价Reset/同步/全VUID认证。
- Agent实际main→同包CLI→RMX3551：2653→2236→2229 LOAD DONTCARE→2237准确无可用画面→2236恢复；真实手机screencap与前台归属分别取证。占用不抢占、关闭/取消等待终态、显式恢复及断连均以helper退出、完整空forward帧和进程回执核验。
- Android单事件GPU时间71.406248us；此队列无FrameGPUDuration，准确返回capability/frame_timing_unavailable并恢复事件，未冒充整帧时间。

### 身份与交付入口

- 原始BlackHair：232496214字节，SHA256 a1d2a989f5f54badbe4a0b676863a9804a814327614a90b1bc4dbd0261b5960a，原件与受保护设备缓存保持不变。
- Native执行产物来自冻结源树0a0fd1db…028cb（f6aff93bc+官方282b28b3+维护修复）；随后只修复_jsonProcess的版本token Trim并单列metadata生成回执，没有假称重新编译DLL/PYD/APK。
- DLL 3ce77ff7…a904，PYD 1e4c7341…fe25；arm64 APK36df7cff…5f66，实际so BuildID f248e2630f709b10。完整值与编译配置以根binaries/windows/x64/manifest.runtime.json为准。
- 默认使用仓库bin/rdc-tool.cmd。唯一完整本地候选为intermediate/native-replay/candidate-delivery/rdc-tool，清单74254e3c8f02e2199d6d1713101a5f9acfdee3804684078d2fb156b2887c5262；它是local_validation_candidate，不是正式Release。当前native字节和129项契约未变，实际UI/设备证明保留36669阶段身份，新门禁与候选另验，不给旧证据换标签。

### 清理、证据与边界

已按明确路径、Git归属、无活动进程及无链接越界清理本轮Native开发输出、对象/链接/Android缓存和旧运行时副本，逻辑文件约7.60 GiB；另清理231份过渡回执、7个评审测试目录及最后验证ZIP/测试状态。磁盘实际剩余空间另行测量，不用逻辑体积冒充释放量。保留当前最终产物/符号、唯一完整候选、Python构建/测试依赖、合法fixture及最小验收证据；不删除原capture、用户SDK/NDK、Agent node_modules/out、原.cursor及旧调查材料。

证据根：intermediate/native-replay；主要索引catalog-verification.json、source-delivery-identity.json、release-chain-delivery.json、publication-cleanup.json及native-trace。Agent正式消费见其acceptance-ledger。远端CI与GitHub Release是独立事实：Agent CI已成功；Tools新CI已触发，状态以对应提交运行记录为准。正式clean提交05a7f90的打包/源码门禁/同包Native导入/完整ZIP链已本地实际通过（ZIP c30dc4ff…f2844，验后删除）；1176+2全测通过。未创建tag或GitHub Release。

未验证：其他GPU/API/设备、arm32实机、未覆盖depth/stencil resolve、secondary/multiview组合、模型质量及Windows独立preview物理视觉。构建、原生数值、UI与手机呈现各有独立证据，不互相替代。

# Tool convergence execution ledger

Current release update: RDC-Tool 1.0.2 session worker/transport timeout alignment, coordinated with RDC-Agent timeout defaults and tracked in the adjacent RDC-Agent release readiness and acceptance ledger. Earlier C/R/H/T tables and receipts are historical snapshots; current contracts are [public-contract.md](public-contract.md) and [install.md](install.md). Generated .qoder wiki content is not SSOT.

2026-09-20追加发行授权：Tools 1.0.1正式发布，Agent 0.6.0-rc.1未签名预发布；允许main提交、非强制推送与新tag/Release，不覆盖v1.0.0。Tools发行回归37项及2个subtests、markdown/identity通过；最终zip完整验证通过，SHA256 `e5cd8df1237ad95ecaf64afd911107c5298d08898492924edefb32efdf958357`。提交/上传状态由相邻Agent任务账本P1–P3追踪。下文“不提交或发布”是历史阶段边界。

2026-09-20 Agent退出补验已完成：现有打包窗口与上手指南目视正常，Alt+F4正常退出；主进程、子进程与canonical lock均释放，隔离配置已删除。下表先前单列的Agent原生容器/退出未验项已补齐，跨库计划T1–T6通过；不提交或发布。

| Task | 状态 | 范围与验证 |
|---|---|---|
| T4 发行修复 | 通过 | CHANGELOG/version/license/staging/dist-info升级与验证脚本生命周期完成；34项不同受影响测试通过；隔离runtime的真实成功、异常和取消清理均通过，cleanup失败不得写PASS |
| T5 候选验证 | 通过 | dist/candidate/rdc-tool-1.0.1-windows-x64.zip；SHA256 9d3a653b0fcfc78ba97324cf5e452651e8e90f7f445b19981540a24d9509b254；更新zip真实CLI与门禁通过，3130文件匹配源码。未改运行时，沿用Agent设置1.0.1/128操作与Vulkan EID21打开关闭证据 |
| T6 收口 | 通过 | 源码门禁记录intermediate/logs/first-use-release-cleanup.md；context释放、daemon停止、runtime/staging/解压/测试临时目录清理完成；无Python残留，canonical lock不存在。保留一套候选，不提交或发布；Agent原生容器/正常退出仍由跨库计划单列，Browser界面验收已通过 |

Original approved scope: Tools 196 → 124, RDC-Agent fixed integration and capability policy,
three specialist manuals, real configuration upgrade, required validation and cleanup.
Historical restoration mode: approved necessary-capability restoration, with the deleted-operation review retained below. No new agent, branch, commit, push, compatibility route,
unrelated refactor, large capture copy or distribution-package generation.

Baseline: Tools `7f5b085b999641977863f91cdb984e667db36629`; Agent
`d2aecfad274552b7a1e2df8ad9076af5998120a4`. Both were clean at start.

## Tasks

## Necessary-capability restoration

Approved repair scope: 18 missing capabilities, adjacent RDC-Agent integration, four existing RenderDoc merge conflicts and the recorded WhiteHair repeat-observation failure. No fixed operation-count target. Existing green evidence applies only to unaffected behavior. Real provider budget: at most six requests including retries and continuations. Temporary root: `intermediate/capability-restoration`; no large capture copies.

| Task | Dependencies | State | Scope / completion criterion | Verification / blocker |
|---|---|---|---|---|
| R01 Contracts and matrix | Completed 73-operation review | 通过 | Map all 18 gaps to canonical definitions and meaningful tests; retain 55 reasonable deletions | 18-row interface/implementation/verification matrix below; canonical catalog/reference freshness, derived 128-operation set and schema negatives passed |
| R02 Native foundation | R01 | 通过 | Resolve four authorized conflicts, preserve customizations, build required targets and matching runtime | Four working-file conflicts resolved with reviewed union patch. Windows DLL, matching Python binding and Qt target built successfully. Native whole-frame counter measured real Vulkan fixture; Four index conflicts marked resolved. User authorized installing required Android tools; NDK 27.3.13750724 and CMake 3.31.6 installed in the existing Android Studio SDK. Both Android architectures built; host include-bin build fixed for MSVC. Matching arm64 deployed and connected. Native idle-receive repair built for both Android architectures; Windows incremental DLL build and deployment passed; 2964 manifest entries verified |
| R03 Pipeline and descriptors | R01 | 通过 | Full pipeline facts, samplers, descriptor stores/ranges, API-specific availability | 38-case pipeline/structured/restoration batch passed. Native Vulkan sections and CLI full pipeline, descriptor stores, resource/sampler ranges including empty slots passed; real Vulkan/D3D12 state, nonzero-index/slot and filter tests plus Agent query consumer passed; other real GPU backends remain outside available hardware evidence |
| R04 Capture and structured data | R01 | 通过 | Embedded thumbnail, bounded event/chunk reads, initialization provenance | Bounded object/child/string continuation implemented and tested. CLI embedded PNG thumbnail (without replay), event/chunk calls passed. Native Thumbnail struct mismatch discovered and fixed; actual D3D12 initialization chunk correspondence and bounded/invalid provenance negatives passed |
| R05 Initial contents and frame timing | R01,R02 | 通过 | Proven initial bytes and GPU replay span, cancellation and restoration | Real native and CLI Vulkan full-replay GPU samples passed; no event sum or CPU timer. CLI texture276 (692180 bytes) and buffer105 (1216 bytes) initial/current differ and restore identically. Failure/cancellation/restoration tests passed; D3D12 initial buffer read/restore and ten provenance/restoration tests passed. Available implementation proves Vulkan single-queue timing and recorded Vulkan/D3D12 initial content; selected D3D12 mip/array/plane coverage now implemented with six positive/negative cases; initial-content reconstruction remains limited to proven Vulkan/D3D12 records; other APIs are unavailable and not claimed supported. Matching Android runtime acceptance passed; real GPU timing coverage is the local Vulkan fixture, not an Android timing claim |
| R06 Agent policy and manuals | R01,R03,R04,R05 | 通过 | Frozen identities, capabilities, receipts, generated manuals and actual preload | Capture identity and temporary replay capabilities implemented. 44 initial policy/freeze/shell tests, 28 shell tests including actual before/after context proof and initial typecheck passed. Three generated references current; latest five-file policy/shell/freeze/frame-evidence batch: 73 passed. Shared/specialist manuals updated; type/lint/guides/gates/build passed; actual Browser General shell.rdx execution preserved owning event; capture open/close and three-Mission deterministic preload checks passed |
| R07 Android repeated observation | R02 | 通过 | Fix EID3029 → EID3027 → EID3029 DataNotAvailable; close and reopen | Matching runtime resolved the old handshake failure. Device log proved idle receive timed out after five seconds; native server now waits for a packet before applying its bounded receive deadline. CLI 3029 → 3027 → 3029 passed after an idle gap, with two fresh 1552×720 PNGs and correct no-color result. Android transfer uses verified SHA256 reuse without repeated upload. 34 remote/worker/error tests passed; actual Agent Android close/reopen, fresh repeated observation and 900×760 UI passed; final UI close cleared the picture; ADB helper/forward queries empty |
| R08 Real acceptance | R03,R04,R05,R06,R07 | 通过 | Small themed local/Android batches, isolated Browser QA, <=6 provider requests | Small fixture CLI open/thumbnail/pipeline/descriptors/structured/initial/timing passed; Large local direct open/thumbnail/pipeline/root signature/resource states/structured query passed. Browser small fixture Present21 → draw15 → no-color17 → draw15, close/reopen passed; 900×760 drawer, Composer and adjacent empty panels inspected. ClinePass DeepSeek V4 Flash executed one shell.rdx query with actual output, retained EID15; Provider request snapshots: 2/6. local and Browser batches complete; Android CLI and actual Capture sequence, close/reopen, error recovery and narrow UI passed. Device presentation unsupported; unavailable API hardware/model Mission quality remain explicit boundaries |
| R09 Docs, gates and cleanup | R01–R08 | 通过 | Current generated docs, necessary full gates/build, own resources removed and startup restored | Tools full run: 326 passed, 3 stale fixture/interface assertions failed; all 3 repaired and targeted rechecks passed. Native-thumbnail repair: 7 affected tests passed. Agent full run: 2815 passed, 8 failed; two empty-stdout process classification failures repaired, six timeout files rerun with two workers and unchanged assertions/timeouts; all eight files/70 tests passed. Type/lint/guides/gates/build passed. Tools source gate: only two unknown-operation error-code failures; repaired CLI preflight, 13 tests and both real negative CLI calls passed. Windows runtime DLL/binding and both APKs deployed; manifest integrity, final Markdown/reference and affected 34+19 tests plus failed-transfer cleanup regression passed. QA, three task-owned gate daemons, device sample and forwarding released; temporary root, test spill root and runtime backups removed. Current Windows build moved without copying to native x64; original inputs/history and older unowned daemons preserved; canonical desktop lock absent |

## Runtime and host convergence (2026-09-19)

Approved scope: thin CLI and explicit installer; sequential fail-fast read-only batch; strict host binding; dedicated file routing and session-local read-before-edit; replay fact audit; generated guides and acceptance. No commit, push, release or branch creation.

| Task | Dependencies | State | Completion criterion |
|---|---|---|---|
| H01 Launchers and installer | — | 通过 | install.cmd and bin/rdx.cmd; old bat and PowerShell runtime removed; installer and package checks |
| H02 Read-only batch | H01 | 通过 | One Python process; canonical envelopes with index; first error stops; cancellation |
| H03 Host binding | — | 通过 | Paired bundled Python/CLI; persisted invalid settings blocked; Settings UI |
| H04 File routing and read-before-edit | — | 通过 | Four modes; command-position matching; session-local successful realpath reads |
| H05 Replay facts | — | 通过 | Real alignment/mesh/usage JSON audit; truthful supported and unavailable fields |
| H06 Knowledge and generated contracts | H05 | 通过 | CLI and Agent recipes; explicit catalog generation; matching fingerprints |
| H07 Gates and live acceptance | H01–H06 | 通过 | Domain and full checks; Browser/argv/timing evidence; owned-resource cleanup |
### 本轮事实与验收证据

源码基线：Tools `453f75611bc8fb6008d6d3c8f71ecc31a9dfa428`，Agent `2dd81bc99e61f0bb1ab07c46ee9b4a9a32df48bf`；以下结果对应未提交工作区，不能归因于基线提交本身。原始样例和进程回执保留在本库 `intermediate/runtime-host-evidence/`，不入分发包。

原始输入未修改：`tests/fixtures/vkcube.rdc`（SHA256 `00797a27e6316a0cf4369327f9db30a21635fa757673b3f9712af07989145ba8`，EID11）和 `vkcube_validation.rdc`（SHA256 `c50cd1e7c29241c64fd33faf07cb35e802f9dc85692a8512aa36db01c956b385`，EID15）。A/B 使用同 context 不同 session；B 打开后仍可显式读取 A；同 capture_file_id 再次 open_replay 返回 reused_session=true。ResourceId 只作单 capture 内关联。

`sample_ok=true` 表示真实回执符合声明，包括如实报告缺失或不支持，不表示缺失能力已实现。下列 sample_path 相对上述证据目录；a-/b- 代表两份 JSON。

| intent | operation | field | present/added/unsupported | sample_ok | sample_path |
|---|---|---|---|---|---|
| 完整事件索引 | rd.session.get_replay_events | complete / events[].event_id | present | true | a-/b-index.json |
| 父链与 marker | rd.session.get_replay_events | parent_chain / marker_path | added；无 marker 为 null | true | a-/b-index.json；a-index-after-b.json |
| action 与附件 | rd.event.get_action_details | parent_chain / marker_path / depth_output | added；不推断唯一 marker | true | a-/b-details.json |
| 稳定 shader 键 | rd.pipeline.get_state | shader.hash | added；原始 bytes SHA256，缺失 null | true | a-/b-pipeline.json |
| shader 调试名 | rd.pipeline.get_state | shader.debug_name | added；样例 null，排除自动 ResourceId 名称 | true | a-/b-pipeline.json |
| VS 布局与位置 | rd.mesh.get_post_transform_data | mesh_format / vertex_rows[].position / attributes | added；可靠 Float32 布局 | true | a-/b-mesh.json |
| 法线与 UV | rd.mesh.get_post_transform_data | attributes.normal / attributes.uv | unsupported；无可靠语义布局 | true | a-/b-mesh.json |
| GS 可用性 | rd.mesh.get_post_transform_data | stage_bound / availability_reason / vertex_rows | present；未绑定是合法空结果 | true | a-/b-gs.json |
| 有界 mesh 读取 | rd.mesh.get_post_transform_data | vertex_byte_size / truncated | added；无界原生长度且达到请求上限时 truncated=null | true | a-/b-mesh.json |
| OBJ 输出 | rd.export.mesh | vertex_count / primitive_count / attributes | position present；normal/uv unsupported | true | a-/b-obj.json；a.obj / b.obj |
| usage 读写 | rd.resource.get_usage | usage_name / is_read / is_write | added；native enum 分类，未知 null | true | a-/b-usage-color.json |
| usage 绑定边界 | rd.resource.get_usage | binding_only_observable | added；false，不声明纯绑定或未使用 | true | a-/b-usage-depth.json |
| event 与附件关联 | rd.resource.get_usage | event_id / raw_event_id / event_resolvable / attachments | added；color slot 与 depth | true | a-/b-usage-color.json；a-/b-usage-depth.json |

Clear 真实样例 read=false/write=true；ColorTarget read=null/write=true，不能据此断言无读取。法线/UV、无 marker 限制已同步教法，不生成跨 capture 对齐结论或依赖图。

生成顺序：字段修复 → catalog/reference → 教法 → 三本 Agent 手册。CLI discovery、catalog 文件和三本手册 fingerprint 一致：`8681825a610af3466a968eb379268bbebe36e174b670a788a4fda33c02fced1a`。完整128操作集保留，无 batch catalog 操作。

`thin-process.json` 保存实际 cmd→Python 父子 PID 与完整 command line，无 PowerShell 子进程；`timing-processes.json` 保存单 Python 两条 batch；`agent-native-read.json` 保存两次 shell.rdx 冻结 argv，discovery 无进程；`batch-process.jsonl` 保存两个 canonical 信封。

分段各3次：PowerShell 启动776.831/582.746/593.713ms；Python启动+import178.595/202.083/137.239ms；热pipe status2.329/2.314/2.538ms；首次/clear后open_replay1808.793/491.470/493.379ms。回放不含客户端启动和open_file，后两次复用已初始化worker。不将首次回放成本算作启动器成本，不以差值宣称优化收益。

Browser `browser-qa.json`：disposable Settings拒绝/保存/验证，Capture打开、EID切换与关闭；1813×1145和390×844，键盘焦点及disabled/selected/running状态通过。修复已有Browser PNG字节解码缺口后，EID11真实图像603×653可见。没有真实账号、模型质量、Android屏幕或额外全实验声明。

Tools最终完整回归384项通过；source release gate通过，未生成整套发行包。Agent完整测试、覆盖率、综合门禁及受影响复验结果记入Agent验收账本。资源清理单独核对，context clear不等同daemon stop。

本轮收口：Agent最终全量413文件/2936测试通过，4项外部条件测试默认跳过；真实read/parser两项另行通过。覆盖率 lines75.12%、functions76.81%、branches62.19%、statements72.70%，ratchet通过。Tools384项及release gate通过。源码逐文件SHA256见 `source-manifest.json`，验证汇总见 `verification.json`。删除709个经归属/链接/进程核验的本轮目录；Vitest临时目录现纳入既有隔离根并随退出释放，全量复跑没有再生成外部fixture残留。Browser标签页和viewport已还原，QA/桌面进程退出，canonical lock不存在；实际桌面窗口启动成功后正常关闭，桌面启动权已交还。

## Original convergence tasks

| Task | Dependencies | State | Scope / completion criterion | Current evidence / remaining work |
|---|---|---|---|---|
| T01 | — | 通过 | Baselines, 196-entry disposition and direct consumer inventory | Upgrade table and cross-repo CLI/lifecycle/caller verification completed |
| T02 | T01 | 通过 | Code definitions, registration, catalog, discovery and generated reference agree | Independent 124-name/old-name exclusion, schema negative cases, fingerprint and reference freshness passed |
| T03 | T02 | 通过 | All merges/removals and retained behavior correct | 286 tests and real small-fixture chain retained; perf 5-case independent regression passed (full event set, numeric enum, seconds→microseconds, unsupported rejection); source-package gate independently passed |
| T04 | T01,T02 | 通过 | Fixed lifecycle, Settings installation state, frozen CLI/definitions/lease | Independent version/catalog/identity/cancel/close/freeze tests and 7 fixed operations/9 real-schema argv variants passed; real large-capture open exposed missing native success context identity; fixed in Tools, 7 adjacent tests passed, UI normal close/reopen succeeded with new owning context; complete 1650-event index and requested/applied/image EID7388 verified |
| T05 | T03,T04 | 通过 | Capability execution, discovery, signed evidence and adversarial cases | Independent 60 policy/evidence tests passed. Catalog buffer truncation and missing export.texture event parameter fixed; final independent real GPU signed baseline/intervention/variant/rollback/restored test passed (1 test, 16 seconds), with changed variant pixels and restored baseline hash |
| T06 | T02,T05 | 通过 | Shared/three specialist manuals, generated references/examples and actual handoff preload | Independent 59 handoff/preload/visibility tests, 4 Skill validators and generated references passed; final export parameter is included in regenerated references |
| T07 | T03–T06 | 通过 | Authority docs and verified one-time real settings upgrade | Authority docs synchronized; real Settings 2.0.0/124 verification passed, original theme restored, only three obsolete fields changed, backup removed |
| T08 | T07 | 通过 | Remaining gates, actual application/local/remote/UI acceptance and cleanup | Small-fixture and Tools full tests retained; full suite 2792 passed/3 conditional skips after direct fixes; coverage ratchet 74.84/76.61/62.12/72.43 passed; gates/typecheck/lint/build passed. Local Settings/Capture, native signed GPU experiment, desktop startup and cleanup passed. The repeat-observation blocker is resolved by the matching native idle-receive repair; CLI and actual Android Capture repeat observation, close/reopen and final cleanup passed. Real model effectiveness is explicitly deferred, device presentation remains unsupported |

Only verified tasks become 通过. Earlier `android_helper_occupied` only proved a helper process existed; it did not prove another client occupied the service. Real model effectiveness is deferred by the user's explicit decision to a later debug loop and is not a blocker for this wave.

### T08 remaining implementation (approved 2026-09-14)

| Item | Dependencies | State | Scope / verification / blocker |
|---|---|---|---|
| T08-A Android connection and cleanup | T03 | 通过 | Existing-service reuse, one budget, cancellation join, exact ownership cleanup implemented. Latest bootstrap 25 and remote runtime 22 tests passed; retained recovery/timeout checks passed. Real borrow/Ping/disconnect/reconnect and strict clear_context removed only the new forward |
| T08-B Application integration | T08-A | 通过 | Offline device selection defers activation until owning capture context exists; removed unusable activate IPC. Native error details preserved. Device/session/protocol tests, gates, typecheck, lint and desktop build passed; actual Capture selection, opening, errors/retry and narrow drawer exercised |
| T08-C Three Mission deterministic acceptance | T06 | 通过 | All three directions cover plan/hash, required Skills, actual builtin content preload, handoff and return with controlled results; generic adversarial cases reused. Focused 49 tests, generated guide freshness, Skill validators and engineering gates passed. Real model quality is deferred by user decision |
| T08-D Real Android acceptance | T08-A,T08-B | 通过 | Historical SaveTexture 29 failure was traced to the native idle receive timeout and repaired in R07. Matching runtime passed CLI and actual application EID3029 → EID3027 → EID3029, close/reopen and final owned-resource cleanup; historical failure evidence below is retained |
| T08-E Documentation and cleanup | T08-A–D evidence | 通过 | Authority docs, catalog/reference and Markdown checks passed; all task-owned daemons/desktop processes stopped, forwards and fixture helper removed, temporary root and task replay selection removed without following links. T08-D failure preserved in this ledger |

## Retained verification evidence

- Tools catalog/schema/registry: 124 names; all removed names excluded. Canonical
  envelope remains 3.0.0, tool version 2.0.0, full catalog schema 1 and SHA256 fingerprint.
- Tools complete pytest: 286/286 passed, zero skips. Initial tmp_path ACL errors
  were rerun only for affected nodes; repaired Present fixture passed separately.
- Generated reference and catalog freshness passed; Markdown health passed 27/27;
  independent whitespace check passed. New native-API regression cases passed.
- Real hello_triangle CLI replay passed: pipeline RT256/depth276 at EID11, readable
  SRV format, actual OBJ (1509 bytes, 36 vertices/12 faces and valid indices), final
  Present observation EID14, texture/mip/target negative cases, in-memory statistics
  and histogram, clear/stop/reopen and final daemon running=false.
- T04 independent runs covered complete CLI cache identity, deep turn freezing,
  version/schema/fingerprint/fixed-capability rejection, remote serial/identity and
  late cancellation, separate clear/stop failures, and Settings installation service.
  Final focused catalog 14/14, observation 16/16 and actual Tools-schema 9 argv
  variants passed. Native parser and final independent real GPU signed five-stage A-B-A passed.
- Runtime manifest: all 2964 files independently verified. 1909 historical hashes
  reflected CRLF while Git and existing -text attributes preserve LF. Reconstructing
  CRLF reproduced every old hash; only manifest size/hash entries were corrected,
  with zero missing files/other differences and no runtime file rewrite.
- Release-gate CLI projection errors were repaired and independently rechecked.
  Explicit-package/source-gate separation has 17 targeted tests passed; independent
  two-case source-default/explicit-package confirmation passed. No new package was generated.

Unaffected green checks and completed real chains must not be rerun. New changes
receive only their affected checks. Mock results do not replace required live evidence.

- Independent real standalone preview lifecycle passed: on at EID11/texture256,
  set_active6 reflected bound_event_id6, off cleared bindings/size; dedicated context
  cleared and daemon status running=false. Native window pixels were not visually
  inspected; this evidence covers the real CLI lifecycle only.

## Current ownership and completion boundaries

| Existing owner | Exact remaining responsibility |
|---|---|
| tools_implementation | Completed implementation and affected verification; no remaining code work |
| tools_tests_docs | Completed manuals/references and verification; owned perf residue confirmed and removed |
| agent_t04_verify | Completed independent acceptance including final native GPU signed experiment |
| root | Android follow-up implementation and deterministic Mission checks completed; repeat-observation native failure remains unresolved; documentation and owned cleanup completed |

## Real settings and cleanup

`C:/Users/Vip/.rdx/config.json` exists (452167 bytes at baseline). CLI is enabled,
points to this checkout's rdx.bat, args `--non-interactive --json`, cwd this checkout,
timeout 60000 ms, no CLI environment overrides. The three obsolete fields tooling.rdxActions,
tooling.rdxCli.catalogPath and tooling.rdxCli.jsonMode have been removed; parsed equality verified every other
setting is unchanged. Live Settings confirms Tools 2.0.0 / 124 operations and handles empty/unsaved
configuration, dark/light and narrow layouts. Original dark theme was restored;
final parsed comparison proves only the three removed fields differ. The temporary
backup has been deleted after successful validation. Preserve providers, chats, captures and historical evidence.

Final cleanup: `intermediate/tool-convergence-tests` and the task-only
`D:/Projects/agentTest/rdc/.rdx/replay/sess_0cf7f31df1db` are absent. Exact default-runtime
files for `perf-correctness` and `rdc-56e34d7b-246e-4d0a-905e-be1eeffc799d` were removed.
The real-settings backup, temporary coverage junction, test images, exports and QA
userData were removed. Mixed test-directory ACL ownership was handled with the
respective execution identities; final deletion returned no errors. No links were followed.
Real inputs, existing replay `sess_366decc65ffa`, user history, dependencies and current
application build were preserved.

Formal desktop launcher reused installed dependencies/current build and opened a real
window (owner PID113508, nonzero MainWindowHandle, title RdcAgent - RenderDoc Debug Agent).
QA and desktop owners and their descendants were stopped. One owned query daemon's
normal stop timed out; its exact verified context/PIDs161980/108888 were terminated
and confirmed absent before deletion. This cleanup fallback does not replace the
successful normal application close/reopen acceptance. Canonical desktop lock is absent;
desktop startup ownership is returned. Other active contexts whose ownership was not
established were preserved, not killed by process name.

Real Provider boundary: actual settings report `hasConfiguredProvider=false` and the
Composer has no available model. Three-Mission handoff/preload integration passed,
but no real model request was made. This is explicitly unverified, not a model-success claim.
Final changes after executable verification only remove trailing whitespace and update
acceptance records; unaffected test and build evidence remains valid.

Large local capture: `D:/Projects/agentTest/rdc/.rdx/inputs/眼睛泪腺白点.rdc`.
Android capture: same directory `WhiteHair.rdc`; prior ADB-online observation does
not prove current RenderDoc/remote display availability. Never copy these inputs.

## Current-contract follow-up

| Item | Dependencies | State | Scope | Verification |
|---|---|---|---|---|
| Remove release-major coupling | T02,T04,T06 | 通过 | Revert the release bump; remove Tools-major gate and guide version binding; retain actual schema/capability validation | Agent 20 tests; Tools 6 tests; generated guide freshness, typecheck, lint, build and diff checks passed; no new temporary test roots or app processes |

Earlier 2.0.0 entries above record the completed run at that time; the follow-up supersedes its release-number decision. Package metadata remains informational and does not identify a parallel interface.

## Android follow-up evidence (2026-09-14)

RenderDoc Command normally starts through connect; the user does not need to open it manually. Initial device inspection found no helper. Normal automatic startup passed. A task-owned helper fixture was then started once to test borrowing; this is not evidence that an actual pre-existing user session was tested. Borrowed connections preserved the fixture PID and its existing forward. Only the fixture owner may finally stop it.

The real application exposed two direct defects now repaired: opening replay created a second native remote connection and received the real busy status; clear_context erased context without releasing its remote forward. Replay now uses the owning connection, and clear_context confirms session/remote cleanup before erasing identity. Fresh real connect/clear removed its forward and preserved the borrowed helper. Native CLI error codes/messages now reach application recovery UI.

WhiteHair was transferred successfully once, directly from the original file (168591424 bytes, SHA256 03df08d14e6d5819e5173209d9ac1218c2f740010104ec911a7873e97a258d42). The actual UI returned 1178 events and a visible first PNG at EID3029. EID3027 legitimately had no color output. Returning to EID3029 targeted ResourceId::148783 but SaveTexture returned DataNotAvailable (29), and retry reproduced it. Requested/applied EID were 3029 while imageEventId was null. No driver, remote-server or application root cause is established; this is an actual failed acceptance, not hypothetical risk or proof of an external device fault. Device presentation is unsupported independently of PNG export.

Latest focused Tools groups: bootstrap 25 passed, remote runtime 22 passed; earlier affected context/CLI/runtime group 26 and timeout/recovery checks retained. Agent focused groups: 49 Mission/resource/device tests, 29 device/session tests, and 46 native protocol/invoker/session tests passed (overlapping groups are not summed). Gates, typecheck, lint, generated guide checks and final desktop build passed. Desktop startup produced a nonzero native window handle and expected title; this does not replace visual QA of the web surface. No real model request was made or required for this deterministic acceptance.

Final cleanup verified: all four dedicated CLI daemons stopped normally; application/desktop processes were absent. Exact task forwards and fixture helper were removed with no cleanup error; final ADB forward list and helper query were empty. The initial device had no user helper, so only the task-owned fixture was stopped. The temporary root intermediate/android-convergence and task-only replay sess_e08b0465e44a are absent. Mixed ACL directories were removed using their execution identities, without changing repository permissions or following links. QA tab closed and viewport restored; normal desktop startup ownership returned. Real inputs, existing replay/history, dependencies, installed Android helper and current application build were preserved. Catalog/reference freshness, Markdown health (27 files) and both repository whitespace checks passed. At that stage T08 remained blocked by repeat observation; the restoration acceptance below resolves this historical failure.

## Deleted-operation review requested by user

| Item | Dependencies | State | Scope | Verification / blocker |
|---|---|---|---|---|
| Review all removed operations | Existing removal set and baseline HEAD | 通过 | Re-audit all 73 deletions without a target tool count; old input/output contracts, current primitives and native members; docs only | 73-name old/current difference verified. 55 reasonable / 18 over-cut: three additional missing viewport/scissor, blend and depth/stencil facts proven by in-memory counterexamples against current extractors. Primitive/Skill boundary retained; Markdown health 27 files and whitespace checks passed; review complete; approved repairs and backend boundaries are recorded in the restoration matrix |

### Native build provenance

Current native source HEAD: `6ed5382e2fb31ce45929295344d2b682751114db`, preserving the in-progress merge and custom working changes. Reviewed eleven-file restoration/build input digest (lexically sorted relative paths, LF, raw bytes): `4070c4f09f003c9b3228a285307e43d49b255a8dcc518b0d9be910ef7108d5cd`. Windows Release x64 targets: renderdoc, pyrenderdoc_module and qrenderdoc_local, MSBuild 18/v145; Python override 3.14.5 headers/import library, actual bundled Python 3.14.3 import and replay verified. Deployed DLL and binding hashes are in `manifest.runtime.json`; all 2964 runtime manifest entries passed integrity verification. Android NDK 27.3.13750724, CMake 3.31.6, Java 21 and build-tools 36.0.0 produced matching arm64 and arm32 APKs. The digest includes the four conflict files, renderdoc/CMakeLists.txt, replay_enums.h, core/remote_server.cpp, and Vulkan vk_core.cpp/.h, vk_counters.cpp, vk_replay.h. Final APK SHA256: arm64 d61d4d6b41167246663e90cebba0c0ef432daf4b15449179518e80584eda7b87; arm32 2247de7c1935e53381f3ab66e232ffa640b317847926c72ab678d29f421504dc.

### Restoration capability matrix

| Reviewed missing capability | Current interface | Implementation / verification |
|---|---|---|
| capture.get_thumbnail | capture.get_thumbnail | capture_queries; native embedded PNG before replay, malformed/absent data tests |
| event.get_api_calls | event.get_api_calls | capture_queries; real Vulkan/D3D12 event and initialization chunk, bounded typed tree and continuation tests |
| pipeline.get_vertex_input | get_state: vertex_input | pipeline_service GetVertexInputs; real Vulkan/D3D12 full state |
| pipeline.get_viewports_scissors | get_state: viewports_scissors | all indices/enabled, nonzero-index mutation tests |
| pipeline.get_rasterizer_state | get_state: rasterizer | API native fields, native full state |
| pipeline.get_multisample_state | get_state: multisample | API native fields, native full state |
| pipeline.get_blend_state | get_state: blend | per-slot mask/logic/equations and blend constants; mutation tests |
| pipeline.get_depth_stencil_state | get_state: depth_stencil | both faces, reference/masks/operations; mutation tests |
| pipeline.get_sampler_bindings | get_resource_bindings | actual GetSamplers, stage/type filtering, descriptor access identity; focused tests |
| pipeline.get_push_constants | get_state: push_constants | Vulkan bytes/ranges/stages/layout identities; native valid empty fixture result |
| pipeline.get_dynamic_state | get_state: dynamic_state | Vulkan effective state; absent dynamic declarations remain unknown |
| pipeline.get_root_signature | get_state: root_signature | native D3D12 root signature, real large capture |
| pipeline.get_descriptor_heaps | get_state: descriptor_heaps | native D3D12 heap identities, real large capture |
| pipeline.get_resource_states | get_state: resource_states | native D3D12 states/Vulkan images, no barrier-history claim |
| resource.get_initial_contents | texture/buffer.get_data state | recorded provenance and drained restoration; Vulkan bytes differ/restore, D3D12 64-byte read/restore, ten negative/restoration tests |
| resource.get_descriptor_info | resource.get_descriptors | native store/ranges, resource/sampler records including empty slots; range validation |
| resource.get_creation_context | resource.get_details include_initialization | recorded chunks/parents/derived, real chunk2205 correspondence; no fabricated stack |
| perf.get_frame_timing | perf.get_frame_timing | Vulkan complete single-queue native timestamps, actual samples and invalid measurement tests |

Real backend coverage is Vulkan and D3D12 on this host; other API field fixtures are deterministic evidence only. The Vulkan timing counter is not advertised for unsupported/incomplete queue coverage. D3D12 initial buffers prove full saved byte length; texture initial reads require recorded coverage of every requested native plane, and unsupported provenance remains unavailable. No claim is made that every API/backend can reconstruct every resource. Android matching-runtime and repeat-observation acceptance passed. Backend limits above remain explicit; unavailable D3D11/GL initial-content reconstruction is not represented as successful restored data.

Large capture final-output boundary: chunk10420 (`Internal::End of Capture`) records `PresentedImage=ResourceId::0`; the resolver correctly reports final_output_unavailable. Explicit EID7388 exported 2131×1909 PNG with event/image EID7388 and no image error; the 9670968-byte sample was deleted immediately. Small fixture Present21 provides positive final-Present coverage. After the provenance fix, small texture276 and buffer105 again differed at capture_initial and matched their original current bytes after restoration.

Current-runtime standalone preview: small fixture EID15 opened a live 530×653 texture256 window through the CLI. Setting Present21 under active-event preview reported no previewable bound output and cleared display identity; this differs from explicit final-output observation. Off cleared all bindings and the owning context/daemon stopped normally. Native window pixels were not visually inspected.

Latest initial-read checks: 38 tests passed; four export fixtures could not create the default OS pytest temp directory, then all four passed using the task-owned explicit basetemp. This covers selected D3D12 mip/array/3D slice and depth/stencil plane coverage, and simultaneous read/restoration errors preserving both diagnostics. No dependency installation was needed for Python tests.

Final restoration cleanup: no helper or ADB forward remained after application close. The verified task device copy was removed; original WhiteHair and local RDC were preserved. Browser tab/viewport and QA PID127104 were released; three task-root gate daemons stopped through CLI. Both temporary roots capability-restoration and tool-convergence-tests are absent. Native x64 is now a real directory holding the current build, with no temporary junction. Existing SDK/NDK/CMake and current runtime/build are retained. Three older contexts predate this restoration and were preserved because they are outside proven task ownership. Real Mission model effectiveness remains the user-planned debug loop; no extra Provider calls were issued.

Publication cleanup recheck: 295 OS-temp investigation fixture directories from this execution window were removed after checking fixture contents, process references and reparse boundaries. Older task evidence, user histories, dependencies and current builds remain intact. Both repositories publish independently on main with structured Changes, Validation and Acceptance boundaries; remote commit equality is checked after each push.

## Runtime/host final closeout (approved 2026-09-19)

| Item | Dependencies | State | Scope | Verification / blocker |
|---|---|---|---|---|
| C01 Desktop facts | H01-H07 | 通过 | IRP EID1346 Float32 normal/UV and full input OBJ; marker and named resource | 42 domain tests, real canonical receipts and independent review passed; shader debug name absent remains null |
| C02 Phone presentation | H01-H07 | 通过 | Paired native runtime, existing remote preview and correlated acknowledgement | Physical color/clear/restore/background/reopen, Agent actual phone output, paired builds and rebuilt desktop consumer smoke all passed; android/acceptance.json |
| C03 Canonical generation | C01, C02 interfaces | 通过 | Tool definitions/catalog/reference, Agent manuals and fingerprint | Explicit source generated fingerprint 4eefd77d649bef8a03d53ab408f097314c781c33ff01b0eec436c5c1562caf4f; three manuals fresh |
| C04 Model and Browser | C03 | 通过 | Three real scenarios; original24 plus explicitly approved6 DeepSeek calls, max3000 output tokens/request | Supplement6 allHTTP200; current A/B context, replay, capture, lease, SHA, events and trace match actual open/query receipts. Artifacts equal model writes; independent verification passed. Seventh continuation denied before dispatch after B artifact readback; no extra final text claimed. agent/supplement/verification.json |
| C05 Short A-B-A | H01-H07 | 通过 | Small disposable fixture; two native runs completed in about 22 seconds | Actual pixel change/restoration and five signed receipts independently verified; applicable original fingerprint retained |
| C06 Independent verification | C01-C05 | 通过 | Domain tests, native/device proofs, Agent gates and independent review | Current Agent2944/413 files, contracts248, coverage ratchet/typecheck/lint/gates/build; Tools405 and release gate; native/device and independent scoped review passed; verification.json; C04 narrow supplement independently passed |
| C07 Closeout | C06 | 通过 | Contracts/ledger, owned resource cleanup and desktop ownership | Docs and evidence synchronized; credentials/test copies/QA cleaned, contexts cleared before owned daemon/helper stop, no forwards; ordinary desktop launch/exit and absent canonical lock verified. Supplemental two contexts released, credentials/copies/QA cleaned, ordinary desktop window verified and canonical lock absent. All C01-C07 complete; agent/supplement/cleanup.json |

## RDC identity and public maintenance (2026-09-20)

Approved scope: RDC-Tool and RDC-Agent identity hard cut, including Agent internal identifiers; local one-time data conversion only; no runtime migration compatibility. Preserve rd.* operation contracts, captures and original historical evidence. Work on main; authorized non-force commits/pushes, Tool release and Issue #1 closure after release. Agent stays private. The earlier task restrictions above are historical and do not override this approval.

| Task | Dependencies | State | Completion / evidence |
|---|---|---|---|
| T1 Naming and contract baseline | — | 通过 | Approved naming map; original catalog saved locally for semantic comparison; current worktrees clean |
| T2 Tool identity and distribution | T1 | 通过 | Canonical package/launchers/env/metadata; 128 operation definitions unchanged; original fingerprint retained |
| T3 Tool docs, License and CI | T2 | 通过 | Generated docs and Windows CI pass; Apache-2.0 retained with updated copyright. GitHub License API remains NOASSERTION (recognition limitation); wiki retained |
| T4 Agent complete identity | T1,T2 | 通过 | Full source/IPC/policy/skill/path rename; same-install Settings validation and real 128-operation catalog handshake pass |
| T5 Integrated gates | T3,T4 | 通过 | Tool 407 cases covered by full batch and affected rechecks; catalog/reference/Markdown/identity/source release gate pass. Agent 2946 pass, 4 existing opt-in skips; coverage ratchet 75.14 lines/76.81 functions/62.23 branches/72.72 statements; typecheck/lint/gates/build pass |
| T6 Package and local cutover | T5 | 通过 | Single Tool zip SHA256 73b41bed3953ef1153b49dbb638e8db545104ddb9ed624cce085def4b2a93a1f; 3132 extracted/installed files match. Settings, catalog, bounded replay open/close, historical messages and new resource read/write pass. Same-volume roots renamed; IDs/capture hashes preserved. Agent packaged desktop starts/closes normally and releases its lock |
| T7 Commit, push and release | T6 | 通过 | Both main heads pushed; annotated v1.0.0 targets green 4a819f75. Release zip/checksum/SBOM remote SHA256 digests match local assets; explicit LFS push succeeded and Windows LFS checkout/bundled execution passed |
| T8 Issue and cleanup | T7 | 通过 | Issue #1 commented after verified release and closed completed. Agent remains private. One-time converter, seven metadata backups, QA credentials/test copies, staging and superseded zip removed; current installation/build and user history preserved |

Validation policy: focused batch after identity edits; one complete final gate batch; rerun only affected failures. No repeated GPU/Android acceptance or full package copies. Original local data and historical evidence are not disposable test output.

Acceptance boundaries: installation is isolated on this host, not a second clean Windows machine. No repeat Android presentation or model-effectiveness claim. The browser automation carrier blocked localhost and no Chrome carrier was available; UI screenshots/visual inspection are not claimed. Native desktop window creation/title and normal exit were independently observed through the process lifecycle.

Packaging failure resolved during T6: electron-builder 26.8.1 omitted pnpm deduplicated transitive dependencies, causing a packaged-main missing-module error while source execution worked. Agent upgraded to upstream 26.16.1; the packaged runtime and ordinary desktop then passed. Desktop smoke now uses isolated data roots and requires actual service initialization, preventing a live error-dialog process from passing. General's resident Skill wording remains domain-neutral; assertions were retained. Both wiki inventories are preserved (159 Tool, 253 Agent); naming/reference corrections were delegated to Luna as requested.

Pre-publication correction: the final Markdown check caught a missing UTF-8 BOM in tool-interface-upgrade.md; Actions independently reported the same failure. Corrected the source and candidate before publication. Only that document and RELEASE_MANIFEST.json changed; all runtime files are byte-identical and installed/archive hashes were rechecked. No replay or full functional suite was rerun for this encoding-only correction.

Publication evidence: [Release v1.0.0](https://github.com/haolange/RDC-Tool/releases/tag/v1.0.0), [release-commit Windows CI](https://github.com/haolange/RDC-Tool/actions/runs/35498524790), [Issue response](https://github.com/haolange/RDC-Tool/issues/1#issuecomment-5748580795). Remote CI runs 9 marked contract/unit tests plus generators, identity, Markdown and no-capture doctor; the complete local regression evidence above is separate. License identification remains NOASSERTION after publication; no repeated license-text mutation was attempted.

## License text correction (2026-09-20)

| Task | State | Evidence |
|---|---|---|
| L1 Diagnose and restore standard text | 通过 | Compared with Apache official LICENSE-2.0.txt: previous text altered definitions and clauses, not merely whitespace. Agent already had standard clauses and was recognized as Apache-2.0; only its copyright placeholder is filled. Restore official body with Copyright 2026 CGBull; earlier classification as an external-only issue was incorrect |
| L2 Remote recognition and distribution notice | 通过 | Both APIs return Apache-2.0 with blob d0b10b02b8be510590934199b721c0a4dd21a2fb. Release correction attachment SHA256 1ff2e3232cca48a89945e95ca4542e13c235abb21df1d0dbc26e61892bd5a2b1 matches remote digest. Top-level release notice supersedes the original zip root LICENSE; original assets/tag preserved |
| L3 Handoff and prompt | 通过 | Desktop handoff and separate evening prompt updated: License resolved, second-host visual/runtime acceptance remains. Official-text equality and Markdown checks passed; no runtime changed or full suite repeated |

## Home Windows follow-up acceptance (2026-09-21)

Non-clean second development host; source repositories and independent user data are not assumed identical to the handoff machine. After reviewing the completed acceptance, the user authorized the related commits and normal main pushes. No new release or published-asset update is included. Existing identity/publication/license work stays closed. Agent runtime must use a C-drive Release installation, not the Tool checkout.

| Task | Dependencies | State | Completion / evidence |
|---|---|---|---|
| F1 Host inventory and safe update | — | 通过 | Both main branches safely fast-forwarded: Agent 37dbfa52 → 11e51d06; Tool b09e64e8 → 04295e47. Existing worktree preserved; no dirty files or divergent commits at baseline. Non-clean second development host; local roots inventoried independently |
| F2 Release installation and real chain | F1 | 通过 | Official 1.0.1 ZIP/checksum and all 3130 installed entries verified; C-drive Python/CLI/catalog and isolated local replay passed. After unlock, native Agent WhiteHair Android 3029 → 2973 → 3029 matched applied/image EIDs and physical phone screenshots. Normal capture close released Tool processes/helper/forward. This is a non-clean second development host; no new full Android/model matrix claim |
| F3 Visual acceptance and focused repairs | F1,F2 | 通过 | Browser onboarding/Settings/local Capture, light/dark and 600px Settings reviewed. Installation field clipping and empty-heading overlay fixed. Native desktop, Android Capture, resource editing/deletion, folder selection and verified Release result reviewed. Scoped style-mod CSP patch confirmed by actual Markdown input/preview and clean inline-style log; no CSP relaxation |
| F4 License correction | Historical L1–L3 | 通过 | Closed by prior publication. If downloading 1.0.0 retain both correction attachments; never claim its original ZIP was overwritten |
| F5 Local data and runtime cutover | F1,F2 | 通过 | Same-volume roots/structured references converted once; C-drive Release bound. Capture hashes/IDs/names preserved; all 41 historical session files rechecked unchanged. Independent unregistered session preserved. Temporary Skill saved, reopened and deleted through native UI, directory absent afterward. Recovery copies removed after acceptance; no canonical QA full-access expansion |
| F6 Verification and cleanup | F2,F3,F5 | 通过 | 21 installation tests plus 2 CSP regressions and focused engineering checks/build passed. Owned test roots/QA credentials/scripts and completed recovery copies removed; evidence and release download retained. Normal desktop close returned launcher exit 0, no owned Electron/launcher/Tool/helper/forward remains, instance.lock absent. Desktop startup ownership returned. No full-suite rerun or repack; related commits/main pushes subsequently authorized, no new release |

## Android 冷启动补丁 1.1.2 发行与安装验收（2026-10-29）

- 用户明确授权两库提交推送 main、补丁发行和官方升级；未创建分支。发行源 `bcb1275ed8fa5acc908e08ac328da3d581c2ff54`，稳定 latest [v1.1.2](https://github.com/haolange/RDC-Tool/releases/tag/v1.1.2)，tag 不随验收文档提交移动。
- 清洁源码正式打包，3143 个 ZIP entries CRC、manifest/SBOM/版本/许可证与完整发行门禁通过；ZIP SHA256 `3bd5ca30c0601e91bffb3021241ba53028e9c04163aadd592bbdc39eb0bd81e1`。仅 ZIP/SHA256SUMS 两项远端资产，digest 核对一致。既有 828 测试及 2 subtests，新增发布阶段 99 项回归通过；发行源 CI success。
- 已发布包内官方 upgrade 将本机 1.1.1 升至 1.1.2；全 3140 程序清单文件哈希一致，旧 dist-info 移除。升级前与运行后 1592 个保护文件一致（含安装内 493 个非程序文件），用户 PATH 与原 ADB server 保留。
- 真实 Electron Agent 服务复用安装版 Python/CLI/ADB，Android 首次打开与 EID3029 设备呈现通过；owning General 冻结 catalog/CLI/lease 后导出实际最终纹理，主进程签名验证、篡改拒绝与 OS 可执行路径/进程出生身份核对通过。完整跨库事实见 RDC-Agent `docs/product/acceptance-ledger.md` 同日发行条目；无真实模型或 shader 修复声明。
- 保留边界：末帧复制事件无普通截图输出时明确失败；一次后续重开伴随手机 RenderDoc helper Vulkan pipeline compilation SIGSEGV，人工重开成功，尚无驱动根因或完整设备稳定性矩阵结论。
- clear context 后 stop daemon，daemon/worker 与手机自有 helper 退出；官方桌面再次启动与正常退出，canonical 锁释放。清理本轮临时提取、测试依赖、脚本/日志/QA 数据及 43 个测试链接；正式发行包与最小证据保留，用户数据保持。

## Android 服务准备、未决安装核验与验收边界（2026-10-30）

- 来源：Tools main基线 `e19ee333aa51eddba7eeb6ebff10b18822aba332`、Agent main基线 `94e09f36da01f39ba74b77dc1dc6de1726046eac` 加本轮工作树；保持当前分支，未提交、推送或发布。逐节点源码/构建身份与最小证据位于相邻Agent `.local/remote-readiness/verify/engineering-receipt.json`、`implementation-identity.json`、`runtime-receipt.json`、`window-lifecycle-receipt.json`；不复制成第二份原始日志归档。
- 当前契约：rd.remote.connect由同安装APK/ADB/native负责缺失安装、兼容运行服务借用与受支持保数据升级，busy不抢占；签名替换、降级、卸载或停止未知服务必须明确确认并绑定实际设备/安装/进程/目标APK/动作fingerprint。PackageManager未决状态通过canonical error.details.device_action保留，取消ACK、host退出或包暂时不存在均不能证明安装已结束；唯一只读rd.remote.inspect_installation返回clear/pending/unknown，clear只排除相关未决安装，不证明服务可用，不自行安装、启动、卸载或abandon。
- 工程通过：最终全量890项测试及2个subtests，catalog/reference/Markdown（27文件）与源码release gate通过；当前catalog为129操作，fingerprint `3b632b109c1644c84635dc6cb10f2ae163776d708e2b51d5e2b1278a41fd0dfa`。超时政策由定义真源生成，worker保留native budget后的收口余量，transport/宿主继续保留响应余量；Agent按冻结catalog推导外壳预算。Windows canonical worker隐藏自有控制台、ADB group/stdio边界的确定性回归与工程门禁通过，不等于真实安装成功或间歇空stdout故障已经消除。相邻Agent全量4175+4既有opt-in跳过、ratchet78.01/79.37/66.30/75.66及后续99项owner保护/19项UI增量分节点记录，不相加成虚构全量。
- 隔离产品窗口通过：Agent正式Browser及标准start:human验证选择即准备、无会话禁用、同owning context打开、切换取消/确认、busy、fingerprint显式确认、未决安装核验、原始诊断、键盘焦点、中英文、主题/大字/390px，以及重启不自动连接。全部是明确UI-FIXTURE CLI和存储样本，不使用手机、模型或真实Provider，不能作为Tools安装/Ping/Open/Android呈现证据。隔离进程、锁与fixture目录清理单独有回执。
- 真实设备变更与未通过范围：用户授权helper136→145；保数据替换遇签名冲突后，已确认卸载实际提交，首轮145安装超时。用户仅批准PM session1443114869取消，初始ACK不是设备终态。18:40一次canonical只读核验clear/verified且helper absent为历史观察。其后一次get-state exit0空stdout/stderr在修改前拒绝，单次带诊断核验通过仍未定位间歇原因；未因此持续重试或放松校验。
- 最终真实Main新尝试：沿同145目标授权仅一次prepare实际进入checking→installing；121.438秒后原生android_apk_install_timeout，Agent类型化stage=installing/recovery=verify_installation/deviceAction=package_install/unconfirmed，未ready/Ping/Open。本次uninstalledExisting=false不否定前轮已卸载事实；约215秒宿主门限没有在原生回执前提前终止。取消或clear不清除未决owner；随后停止设备操作，未重新查询包和PM状态，当前只能报告unconfirmed，不能用早前absent/pending代替现态，也不宣称145安装、回放或设备呈现通过。
- 保护与恢复边界：最后尝试自有native context/daemon/worker已收口，随后QA主进程明确终止并非正常窗口退出；host清理不代表设备动作完成。借用ADB保留，原capture和用户配置保护单独核验。后续应保留同目标APK与冻结CLI/catalog身份，经只读安装核验获得可证明终态后再决定下一步；用户暂不重启，未代为重启、另行卸载、重复安装或取消其他PM session。安装未决不作为全部验收通过，当前配置/CLI交付状态与总清理由独立最终回执确认。
- 本机CLI交付例外（用户明确授权）：用户选择“现在切到源码入口”，明确允许Android正向验收未过时先切换。实际用户配置 `C:/Users/vulcangu/.rdc-agent/config.json` 经hash-guard原子提交，仅Python executable、cli/run_cli.py参数前缀和workingDirectory三个路径改为 `D:/Projects/Native/rdx/RDC-Tool` 同根源码入口，其余配置语义不变，正式release目录未改。实际读绑定 --version 返回exit0、rdc-tool1.1.2，原子临时文件0；回执在相邻Agent `.local/remote-readiness/verify/local-cli-binding.json`。未接设备，不将该绑定成功记为Android安装、ready、Ping或Open通过；最终设备动作仍unconfirmed。
- 最终总清理（2026-10-30）：相邻Agent `.local/remote-readiness/verify/cleanup-receipt.json` 核对自有tmp、测试依赖、ui-fixture及coverage报告均已清理，nofollow核验后去除冗余验证文件，保留最终回执、来源节点、必要日志和三张画面；不以逻辑字节量冒称实际释放空间。node_modules、out、源码Tools及正式release保留。无本轮Task进程、5127监听或canonical锁；借用ADB32864原启动身份保留，原capture的SHA256/大小/mtime复核一致。桌面启动权已交还。设备PM仍unconfirmed，host清理不是设备回滚或安装完成证明，Android ready/Ping/Open正向链仍未通过。

## 2026-11-02 两库同步与回归交付

- 范围：保持main，在Tools `e19ee333`基础上交付Remote准备／修复实现；配套Agent同步云端 `efb3df4f`，保留模型目录和计划审批恢复修复。服务准备仍唯一由 `rd.remote.connect`负责，Agent当前会话提前持有连接并在Open复用；不新增第二套安装、设备选择或兼容路径。
- 验证：冻结工作树完整890 tests及2 subtests通过（98.89s）；catalog129操作、生成reference、Markdown27文件、release gate及diff通过。catalog指纹 `3b632b109c1644c84635dc6cb10f2ae163776d708e2b51d5e2b1278a41fd0dfa` 与Agent冻结目录／专业手册一致。使用既有Python和缓存测试依赖，无全局安装；不制作发行包。Agent合并后完整4228 tests通过、4项既有opt-in跳过，type/lint/contracts/gates/build通过。
- 工程与真实设备分开：本轮不操作Android安装或服务。此前145目标APK安装超时、设备结果unconfirmed仍未解除，未证明实际Ping、Open或设备呈现；UI夹具与代码回归不能替代该链。保留已授权同安装来源和身份校验，未知状态先只读核验，不能靠重新安装、停止ADB或默认回退伪造恢复。
- 状态：实现及工程回归通过；窗口与清理结果由配套Agent本次验收账本记录。既有真实Android正向验收未通过的历史保持原样。
- 配套窗口收口：Agent最终构建经正式Browser及原生Electron隔离验收，通过提前准备／同context打开／切换取消／busy／修复／未知安装及持久化计划恢复；全部为UI夹具，无真实Android或模型调用。自有测试／QA目录、进程和监听器已收口，当前用户安装及原capture不改动。设备端unconfirmed维持未验证，不影响如实交付本轮工程和窗口结果。
