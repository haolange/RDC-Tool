# Session Model

The CLI runtime stores context state per daemon context. `rdc-tool context status` returns the current state; `rdc-tool context update` changes agent-facing fields such as notes and focus. `session_locator` summarizes the active `.rdc`, session, frame, and event.

`--daemon-context <id>` selects the continuous runtime namespace. It is not a daemon-mode switch; omitting it uses `default`. `rdc-tool context list` shows known namespaces and `rdc-tool context clear` clears the selected namespace. Creating a new namespace is limited by live occupancy (`max_contexts`), not by how many state files remain on disk. Reusing an existing namespace does not consume an extra slot. `rdc-tool context clear` still deletes that namespace's state files when it succeeds. Context clear releases replay, preview, remote, and snapshot state; it does not stop the daemon or worker. Hosts that own the process must pass `--owner-pid` and later run `daemon stop` on the same context. If the daemon exits abnormally, `daemon stop` still reaps that context's recorded worker, and the worker exits when its parent daemon PID dies.

Read a different namespace by issuing `rd.session.get_context` with that daemon context. There is no context-selection operation that mutates an implicit current namespace.

Multiple daemon contexts are isolated from each other, and callers choose the context id they want to operate on. Remote handles still keep context locality and lifecycle protection. `remote_handle_consumed` means the handle has moved into session ownership and reconnect logic must create or recover a fresh handle.

## Replay Lifecycle

`rd.capture.open_replay` is idempotent for a live same-capture session in the same daemon context and returns `reused_session=true` instead of opening a second D3D12 replay. `rd.capture.close_replay` is the canonical resource release path. If stale session cleanup fails, the runtime returns `stale_session_requires_restart` with recovery commands rather than silently creating another replay.

## Preview State

The session context includes `preview` state. Preview geometry must describe the whole framebuffer and distinguish viewport / scissor from preview window fitting. `preview.display` is the stable surface for framebuffer extent, viewport rect, window rect, fit mode, and screen cap settings.

## Embedded replay observations

`rd.session.get_replay_events` returns the complete discrete action index for the
selected live context (`complete: true`). It does not inherit the browsing API's
node limit and does not change the active event.

`rd.event.get_action_tree` is the bounded interactive browser. It supports a root page or an event subtree, filters, depth/node budgets, and tabular projection, and reports truncation explicitly. `rd.event.get_action_details` includes direct child event IDs; marker paths come from the real parent chain.

`rd.session.observe` takes a fresh absolute PNG `out_path`, optional `event_id`,
and optional `target` (`texture_id` or actual `rt_index` attachment slot). Without
an event it observes the current context event, including an event changed by an
analysis/debug/shader operation. Use `final_output: true` on open; this cannot be
combined with event or target selection. A final image is claimed only when the
last actual Present action identifies a unique SwapBuffer through copyDestination.
If unavailable, `final_output_error` explains the missing evidence and the current
available color output is explicitly not labelled final.

The daemon serializes apply, color selection and PNG export with all other calls
in the same context. Successful apply followed by failed export returns the
applied `event_id`, null `image_path`/`image_event_id`, and `image_error`; it never
reuses an old PNG. `revision` increases per live context/session observation.
Consumers must additionally track their binding generation across native restarts.

Session-context operations use a 60-second worker budget. The CLI daemon transport
adds the shared 5-second response buffer, so its deadline is 65 seconds for these
operations. This budget is selected by the operation policy; callers do not pass a
second per-request timeout. The host application should keep its outer CLI process
deadline above the 65-second transport deadline.

This path creates no desktop preview window. `rd.session.open_preview`,
`rd.session.close_preview`, and `preview.display` retain their distinct standalone
CLI window contract and geometry smoke coverage. Both use the same native replay
controller; an embedded consumer must not enable the independent window lifecycle.

Device-side presentation is independent of PNG success. The paired native RemoteServer
`PresentReplay(eventId, textureId)` validates the already applied replay event, renders
that texture through the existing native preview window, and returns a fresh sequence
only after successful GPU presentation on a visible foreground surface. A null texture
clears the surface. The client and Android helper must use the matching protocol; an old
helper fails the handshake instead of falling back.

Every `remote_display` contains `status`, `event_id`, `texture_id`, `sequence`, and `reason`.
`presented` requires a positive monotonic sequence and matching selected target; local
observations are `not_applicable`. Missing binding capability is `unsupported`; surface,
transport, or rendering failure is `unavailable` with no stale completion sequence.
No-color events return `unavailable` and `reason=no_color_output`; a positive sequence
then proves the native surface was cleared, not that a texture was presented. A new
native replay handle resets receipt tracking. Successful export or connectivity is
never proof of device-screen sync; acceptance also records actual screen samples.

Observation PNGs are process results, not automatically an Agent investigation
trace. The host records them only after actual operations, outside performance
measurement transactions; reading a saved trace must not call observe or mutate
replay. The host owns output file cleanup and project/session retention.

Embedded observations export directly to the host-owned PNG path without publishing
a duplicate into the native artifact store. Standalone texture export retains its
artifact publication contract through the same texture writer.

Image errors distinguish `no_color_output` (event has no color attachment), `missing_target` (explicit target is absent), and `export_failure` (image acquisition failed). Only acquisition failures merit retrying the same image request. Explicitly selecting a Present event resolves its verified copyDestination swap buffer using the same resolver as final-output opening; the final label requires it to be the actual final Present.

`rd.export.screenshot` first resolves a verified Present target, then may export an actual event output or event binding with degraded provenance. If neither exists, it returns `preview_event_output_unavailable` with the Present failure in details; an unrelated texture from the capture must not be presented as framebuffer evidence. An explicit texture export remains available through `rd.export.texture`. When screenshot target resolution fails after applying an event, Tool restores the prior native event before returning an error. Only a successful restoration carries `replay_state_restored:true`, `restored_event_id`, and `artifact_write_attempted:false`; missing prior event or failed restoration has no usable proof and the owning consumer must quarantine the replay. This does not turn a missing Present target into framebuffer evidence.

Texture pixel history accepts either `texture_id` or a `target`, never both. A target may identify a texture or an actual `rt_index` output slot; mutually exclusive or missing targets fail before history acquisition.

Pixel shader debugging binds to the requested Event and pixel through that target's history. An explicit debug target is used alone. Without one, the current Event's output targets are tried; the default output is considered only when no Event output can be listed. A native debugger handle is insufficient when the selected target has no hit from the requested Event.

Observations include native revision, actual baseline/intervention/restored shader replacement state, and PNG subresource/range parameters. Transfer stages come only from remote CopyCaptureToRemote callbacks through the existing daemon progress sink. Observation applies the event after a synchronous measurement command has returned; it does not promise zero perturbation across an entire multi-command experiment.

Process continuity is observable through `rd.session.get_context.data.process_identity` and each canonical result's `meta.process_identity`. A live daemon worker reads its own and its actual parent's OS process-birth identities. `pid + start_generation` must match for both across experimental stages; a reused PID or rebuilt worker is a new process even when replay IDs survive. An unavailable identity remains unknown and cannot qualify continuity. These read-only queries neither recover replay nor claim helper ownership.

## Android helper lifecycle

A connection records started_activity, owned_pids and created_forward from this attempt. Existing helpers stay borrowed, including when no matching local APK exists. Starting an owned helper resolves RenderDoc's config directory by device SDK level (`Android/data` below 30, `Android/media` from 30 onward) and keeps a regular device `renderdoc.conf` intact; an empty default is pushed only if it is missing. An unknown SDK or file state fails before launch. Disconnect, failed open and cancellation close this connection and remove only its verified forward; they never shut down a borrowed server. Persisted bootstrap metadata does not grant ownership of newly observed processes. Cancelled connection workers are joined before publishing any handle. Cleanup errors must accompany the original failure.

A stopped helper process does not make an existing package or configuration owned by this connection. Before installing, a successful package-manager query must confirm that the exact helper package is absent; unknown, failed or malformed query results fail closed. An installed package is reused without a local APK dependency, replacement install, uninstall or configuration creation. Only a newly installed helper may receive a missing default configuration. A fresh installation is attempted once without replacement flags; conflicts, signature/version errors and package-install races are reported without uninstalling or retrying. Process and forward ownership remain separate from installation ownership. Historical bootstrap metadata remains readable; it never authorizes a new mutation.

The owning snapshot and normalized remote session record persist the PIDs captured when this connection started an Android helper, together with the created forward identity. After a daemon restart, recovery verifies the old context, device, endpoint and forward before removing that mapping and allocating a fresh one. The recovered handle keeps the verified origin context so `clear_context` can release its new forward. If the helper PID is still the recorded PID, the new connection retains its original cleanup ownership; a changed PID is never claimed. Missing, inconsistent or changed forward ownership blocks reconnection instead of leaving an untracked mapping. `clear_context` applies the same identity checks to a deferred remote; cleanup failure retains the context for recovery. Borrowed helpers are never stopped.

Remote replay uses the owning runtime connection for transfer and OpenCapture. clear_context closes only sessions and remotes belonging to the requested context before resetting its snapshot; cleanup failure preserves recovery identity and returns failure.

## Temporary replay reads

`capture_initial` texture/buffer reads and complete-replay GPU timing execute inside the serialized replay boundary. Native work is drained on cancellation before the original event is restored. Context selection and shader replacements remain owned by the session. Restoration failure sets the session restart requirement and rejects later operations; consumers must not issue successful evidence receipts. Capture-initial bytes require recorded provenance, not an assumption that an arbitrary earlier event contains original data.

Android capture transfer uses ADB and verifies SHA256 before OpenCapture. A verified existing device copy is reused without taking ownership; a newly transferred path is owned by the connection and removed on failed transfer or disconnect. An unreadable or mismatched existing path fails instead of being overwritten. Non-Android remote transfer uses RenderDoc RPC.

The native remote server waits for the next packet while a user is idle; the receive deadline applies after packet data arrives, not to the time between CLI operations. Server shutdown remains interruptible. The runtime worker retains one event loop and replay executor across requests to preserve native thread affinity. Shader patch inspection, compilation, application and rollback (including event rebinding and target-resource release) execute on that same replay executor; an async patch API must not access native controller objects on the event-loop thread.

A replay operation tracks only controllers it actually accesses, within its own async context. The first access and final result boundary poll native fatal status on the persistent replay executor. No-controller validation errors do not open or probe a replay. Fatal or unobservable health marks that owning session `requires_restart` and rejects the result before canonical success/artifact publication; scope is reset even on failure or cancellation. Catalog lifecycle operations retain their cleanup path. Controller resources in pipeline snapshots are fetched on the same replay executor, never on the async event-loop thread. A successful health check is an instantaneous observation, not a future connection guarantee or restoration receipt.

Normal shader rollback removes the replacement, rebinds its event and releases its target resource on the existing live replay controller. It does not close or reopen the replay or remote connection. A lost worker reply or unexpected worker error is an unknown outcome: the daemon never resubmits that request, stops its owned worker and preserves the owning context session metadata as `requires_restart`. Initialization and recovery scans retain that quarantine. Explicit context cleanup remains available; a new worker, an empty registry or a reopened capture is not rollback/restoration evidence.

Client cleanup and the daemon lifecycle share the same unreleased-resource check. Idle time alone cannot stop a live daemon holding a capture, replay, remote ownership, or an active request; an expired lost-owner lease still permits cleanup. Unreadable ownership state is retained for controlled recovery. A newly started or replaced worker marks persisted replay sessions `requires_restart` before dispatch, retaining their metadata; requests never spawn a replacement worker implicitly. Explicit context cleanup remains available. Persistent session IDs and equal image hashes do not establish continuity across worker replacement.

Daemon startup serializes the state check, creation and readiness publication per canonical context state path across CLI processes. Concurrent callers reuse the published owner rather than creating competing daemons and splitting file/replay handles. The startup lock is released on success or failure; it does not lock other contexts or replace the existing runtime operation serialization.
