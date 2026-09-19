# Android Remote CLI Smoke Prompt

Use this prompt for Android remote-only smoke through CLI transport. Consult [../README.md](../README.md) for package orientation when needed. When changing this workflow, check and update references for the affected topic: [session-model.md](session-model.md) for session lifecycle, [agent-model.md](agent-model.md) for agent usage, [troubleshooting.md](troubleshooting.md) for recovery, [doc-governance.md](doc-governance.md) for documentation rules, and [../scripts/README.md](../scripts/README.md) for smoke script usage.

Core sequence:

```bat
rdx --json doctor
rdx call rd.remote.connect --args-file intermediate\logs\remote_connect_args.json --format json
rdx call rd.remote.ping --args-file intermediate\logs\remote_ping_args.json --format json
rdx call rd.capture.open_file --args-file intermediate\logs\remote_open_file_args.json --format json
rdx call rd.capture.open_replay --args-file intermediate\logs\remote_open_replay_args.json --format json
rdx call rd.session.get_context --format json
```

For direct RenderDoc remote endpoints, the connect args file must include
`host` and can include `port`. For Android adb bootstrap, set
`options.transport="adb_android"`; `host` may be omitted and defaults to the
local bootstrap endpoint. Include `options.device_serial` when more than one
adb device may be attached. Release smoke records the actual serial used in
`intermediate/logs/tool_smoke_findings.md`.

Keep `options.remote_id` explicit for `rd.capture.open_replay` so remote replay
never falls back to local.

Run `preview_geometry_smoke.py` when the Android remote smoke changes preview behavior.

Embedded replay acceptance additionally calls `rd.session.get_replay_events`,
then `rd.session.observe` with a fresh absolute PNG path and `final_output: true`,
and again with a visibly different event. Check requested/applied/image EIDs,
PNG dimensions and failure diagnostics independently from device presentation.
Navigate with real IDs from the complete replay index, query one bounded action
subtree, close the owning replay, and reopen it once. Reuse the established
remote connection and the already confirmed transfer result instead of uploading
the same capture repeatedly. Put smoke logs and small observation images under
`RDX_INTERMEDIATE_ROOT`; remove them after the recorded acceptance result is saved.
The matching native client and helper expose `PresentReplay(event_id, texture_id)`.
`remote_display.status=presented` requires the applied event, selected texture and fresh
native completion sequence; PNG export alone does not prove presentation. Missing native
capability reports `unsupported`; a missing/background surface or failed present reports
`unavailable`. No-color output clears the native surface and returns `unavailable` with
`reason=no_color_output` and its successful clear sequence. Screen samples independently
verify actual output changes and restoration. Do not stop or replace a running user-owned
helper merely to obtain this proof.

Existing-service smoke must record the helper PID and forwards before connect, verify connect/Ping/disconnect/reconnect, then assert that the helper and pre-existing forwards survive. If no helper exists, let normal connect start it; a controlled fixture may create an idle service to exercise borrowing. Never ask the user to clear processes or manually launch RenderDoc Command. Clean only the fixture-owned resources after the application test.

Matching native client and Android service are a prerequisite after a native rebuild. Record a real protocol mismatch separately from service busy; do not retry a known incompatible handshake. Build the matching Android component with an available NDK before repeating replay acceptance. Do not replace a borrowed service without its owner releasing it.

Repeat-observation acceptance must include a valid color event, an event with no color output, and a return to the original valid event. The middle result must clear the image; the final result must perform a fresh readback with matching requested/applied/image event IDs. An old PNG or swallowed readback error is not acceptance.

Include an idle interval longer than five seconds before replay navigation and repeat observation. An idle connection must remain usable; a truncated packet must still fail within the transport deadline. Verify a close/reopen uses the already verified device copy instead of uploading the capture again.
