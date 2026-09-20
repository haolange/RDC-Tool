# Tool convergence execution ledger

Current approved scope: Runtime/host final closeout C01–C07 at the end of this ledger. Earlier R/H/T tables, budgets, launcher records and capability fingerprints are historical snapshots; they do not override current facts or authorize new calls.

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
