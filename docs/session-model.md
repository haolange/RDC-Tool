# Session Model

The CLI runtime stores context state per daemon context. `rdx context status` returns the current state; `rdx context update` changes agent-facing fields such as notes and focus. `session_locator` summarizes the active `.rdc`, session, frame, and event.

`--daemon-context <id>` selects the continuous runtime namespace. It is not a daemon-mode switch; omitting it uses `default`. `rdx context list` shows known namespaces and `rdx context clear` clears the selected namespace. Creating a new namespace is limited by live occupancy (`max_contexts`), not by how many state files remain on disk. Reusing an existing namespace does not consume an extra slot. `rdx context clear` still deletes that namespace's state files when it succeeds.

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

This path creates no desktop preview window. `rd.session.open_preview`,
`rd.session.close_preview`, and `preview.display` retain their distinct standalone
CLI window contract and geometry smoke coverage. Both use the same native replay
controller; an embedded consumer must not enable the independent window lifecycle.

Device-side presentation is independent of PNG success. The bundled RemoteServer
binding exposes no display/preview acknowledgement API. Its BecomeRemoteServer
previewWindow callback is a server-side integration point, not a client command.
Until the Android helper exposes verified presentation control and receipts,
`remote_display.status` is `unsupported` (local: `not_applicable`). A connected
Android device or successful export must not be reported as device-screen sync.

Observation PNGs are process results, not automatically an Agent investigation
trace. The host records them only after actual operations, outside performance
measurement transactions; reading a saved trace must not call observe or mutate
replay. The host owns output file cleanup and project/session retention.

Embedded observations export directly to the host-owned PNG path without publishing
a duplicate into the native artifact store. Standalone texture export retains its
artifact publication contract through the same texture writer.

Image errors distinguish `no_color_output` (event has no color attachment), `missing_target` (explicit target is absent), and `export_failure` (image acquisition failed). Only acquisition failures merit retrying the same image request. Explicitly selecting a Present event resolves its verified copyDestination swap buffer using the same resolver as final-output opening; the final label requires it to be the actual final Present.

Texture pixel history accepts either `texture_id` or a `target`, never both. A target may identify a texture or an actual `rt_index` output slot; mutually exclusive or missing targets fail before history acquisition.

Observations include native revision, actual baseline/intervention/restored shader replacement state, and PNG subresource/range parameters. Transfer stages come only from remote CopyCaptureToRemote callbacks through the existing daemon progress sink. Observation applies the event after a synchronous measurement command has returned; it does not promise zero perturbation across an entire multi-command experiment.

## Android helper lifecycle

A connection records started_activity, owned_pids and created_forward from this attempt. Existing helpers stay borrowed, including when no matching local APK exists. Disconnect, failed open and cancellation close this connection and remove only its verified forward; they never shut down a borrowed server. Persisted bootstrap metadata does not grant ownership of newly observed processes. Cancelled connection workers are joined before publishing any handle. Cleanup errors must accompany the original failure.

Remote replay uses the owning runtime connection for transfer and OpenCapture. clear_context closes only sessions and remotes belonging to the requested context before resetting its snapshot; cleanup failure preserves recovery identity and returns failure.

## Temporary replay reads

`capture_initial` texture/buffer reads and complete-replay GPU timing execute inside the serialized replay boundary. Native work is drained on cancellation before the original event is restored. Context selection and shader replacements remain owned by the session. Restoration failure sets the session restart requirement and rejects later operations; consumers must not issue successful evidence receipts. Capture-initial bytes require recorded provenance, not an assumption that an arbitrary earlier event contains original data.

Android capture transfer uses ADB and verifies SHA256 before OpenCapture. A verified existing device copy is reused without taking ownership; a newly transferred path is owned by the connection and removed on failed transfer or disconnect. An unreadable or mismatched existing path fails instead of being overwritten. Non-Android remote transfer uses RenderDoc RPC.

The native remote server waits for the next packet while a user is idle; the receive deadline applies after packet data arrives, not to the time between CLI operations. Server shutdown remains interruptible. The runtime worker retains one event loop and replay executor across requests to preserve native thread affinity.
