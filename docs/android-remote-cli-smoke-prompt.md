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
The current bundled client binding cannot confirm Android screen presentation;
record `remote_display.status=unsupported` as an external helper/API acceptance
blocker even if remote open and PNG export succeed. Do not stop or replace an
already running user-owned RenderDoc Android helper merely to obtain this proof.
