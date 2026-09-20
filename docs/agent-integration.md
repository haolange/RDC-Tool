# Agent Integration

Agents should call `rdc-tool` through their shell tool. The public user command is `rdc-tool`.

Recommended probes:

```bat
rdc-tool --version
rdc-tool --json doctor
rdc-tool context status --json
rdc-tool tools search pipeline --json
rdc-tool tools describe rd.pipeline.get_state --json
rdc-tool vfs ls --path / --format tsv
```

Canonical agent lifecycle:

```bat
rdc-tool --daemon-context task-123 --json doctor
rdc-tool --daemon-context task-123 context status --json
rdc-tool --daemon-context task-123 capture open --file "C:\captures\case.rdc"
rdc-tool --daemon-context task-123 capture open --file "C:\captures\android.rdc" --remote-id "<remote_id_from_rd.remote.connect>"
rdc-tool --daemon-context task-123 vfs tree --path /draws --depth 2 --max-nodes 2000 --format json
rdc-tool --daemon-context task-123 event list --format tsv
rdc-tool --daemon-context task-123 pipeline show --event-id 42 --format json
rdc-tool --daemon-context task-123 context update --key notes --value "triaged" --json
rdc-tool --owner-pid %PID% --daemon-context task-123 context clear --json
rdc-tool --owner-pid %PID% --daemon-context task-123 daemon stop
```

`context clear` only releases that namespace's replay/preview/remote/snapshot. `daemon stop` stops that namespace's daemon and worker. Hosts must pass `--owner-pid` so a dead launcher can reap the daemon after the lease, even if a request count is stuck. Do not treat clear success as process exit.

After enabling preview for an opened capture, agents should inspect `preview.display` in `context status --json` for framebuffer, window, and fit geometry instead of inferring geometry from screenshots alone.

Shader edit/replace tools expose an `edit_plan` object in JSON payloads. Agents should treat it as the machine-readable usage contract: it says whether the current shader text can be edited, which edit inputs are allowed, which patch ops are safe, whether a toolchain such as `spirv-as` is required, and which tool to call next when replacement is unsupported. A `can_replace=false` plan is a safe stop, not a signal to retry with a different text encoding.

`--daemon-context <id>` selects a continuous runtime namespace. It is not a daemon-mode switch; omitting it uses the `default` namespace. JSON is the canonical protocol. TSV is an optional tabular projection for list/navigation commands; use JSON for nested runtime state.

For visible smoke, use bash so every CLI command and result appears in the agent terminal:

```bash
bash scripts/smoke_cli.sh
```

`rdc-tool` is CLI-only. Agents should integrate through shell commands and the canonical JSON envelope.

CLI callers should fetch the catalog from the same configured `rdc-tool` executable they invoke and freeze its fingerprint with the turn/session binding. Do not load a second catalog path or translate removed names. Use `tools list --namespace` for an exact domain; free-text search intentionally returns related cross-domain matches.


The generated reader-facing tool list is [Tool reference](tool-reference.md). Migration destinations are in [Tool interface convergence](tool-interface-upgrade.md). The task-level SOP is [rdc-tool-native agent playbook](rdc-tool-native-agent-playbook.md).

## RenderDoc runtime baseline

The current assembled and verified baseline is **RenderDoc 1.45**. RDC-Tool does not track every upstream minor release: a newer runtime becomes the baseline only after matching runtime packaging, catalog checks, tests and release gates pass. RenderDoc 1.44 and earlier official GUI releases are not separate assembly targets. Use the replay path matching this bundled runtime. Capture-format compatibility follows upstream RenderDoc.

RDC-Agent **0.6.x** pairs with RDC-Tool **1.0.0** and the current RenderDoc **1.45** runtime. Catalog definitions and fingerprints, not package version numbers, authorize operations. Local PNG export does not prove Android device presentation.
