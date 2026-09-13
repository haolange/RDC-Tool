# Session Model

The CLI runtime stores context state per daemon context. `rdx context status` returns the current state; `rdx context update` changes agent-facing fields such as notes and focus. `session_locator` summarizes the active `.rdc`, session, frame, and event.

`--daemon-context <id>` selects the continuous runtime namespace. It is not a daemon-mode switch; omitting it uses `default`. `rdx context list` shows known namespaces and `rdx context clear` clears the selected namespace.

Multiple daemon contexts are isolated from each other, and callers choose the context id they want to operate on. Remote handles still keep context locality and lifecycle protection. `remote_handle_consumed` means the handle has moved into session ownership and reconnect logic must create or recover a fresh handle.

## Replay Lifecycle

`rd.capture.open_replay` is idempotent for a live same-capture session in the same daemon context and returns `reused_session=true` instead of opening a second D3D12 replay. `rd.capture.close_replay` is the canonical resource release path. If stale session cleanup fails, the runtime returns `stale_session_requires_restart` with recovery commands rather than silently creating another replay.

## Preview State

The session context includes `preview` state. Preview geometry must describe the whole framebuffer and distinguish viewport / scissor from preview window fitting. `preview.display` is the stable surface for framebuffer extent, viewport rect, window rect, fit mode, and screen cap settings.

## Embedded replay observations

`rd.session.get_replay_events` returns the complete discrete action index for the
selected live context (`complete: true`). It does not inherit the browsing API's
node limit and does not change the active event.

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

Observations include native revision, actual baseline/intervention/restored shader replacement state, and PNG subresource/range parameters. Transfer stages come only from remote CopyCaptureToRemote callbacks through the existing daemon progress sink. Observation applies the event after a synchronous measurement command has returned; it does not promise zero perturbation across an entire multi-command experiment.
