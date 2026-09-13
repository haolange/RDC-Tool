# Tool convergence execution ledger

Original approved scope: Tools 196 → 124, RDC-Agent fixed integration and capability policy,
three specialist manuals, real configuration upgrade, required validation and cleanup.
Current mode: approved necessary-capability restoration, with the deleted-operation review retained below. No new agent, branch, commit, push, compatibility route,
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
