# Quickstart

Run all commands from `resources/tools`, or set `RDC_TOOL_ROOT` when using `bin/rdc-tool` from another directory.

```bat
rdc-tool --version
rdc-tool version --json
rdc-tool --json doctor
rdc-tool tools search pipeline --json
rdc-tool context status --json
rdc-tool capture open --file "C:\path\sample.rdc" --frame-index 0
rdc-tool context status --json
rdc-tool context update --key notes --value "triaged" --json
rdc-tool vfs ls --path / --format tsv
rdc-tool vfs cat --path /context --format json
rdc-tool vfs tree --path /draws --depth 2 --max-nodes 2000 --format json
rdc-tool event list --format tsv
rdc-tool pipeline show --event-id 42 --format json
rdc-tool resource list --format tsv
rdc-tool completion powershell
```

For preview checks after a capture is open:

```bat
rdc-tool session preview on
rdc-tool session preview status
rdc-tool session preview off
```

Inspect `preview.display` in `context status` JSON output for framebuffer, window, and fit geometry. Use `context clear` and `daemon stop` at the end of smoke runs.

JSON is the canonical agent protocol. TSV is only a tabular projection for list/navigation commands such as `vfs ls`, `event list`, and `resource list`; nested state such as context, pipeline, shaders, exports, pixel history, and preview remains JSON.

For agent-visible smoke, run the bash entrypoint so every CLI command is visible:

```bash
bash scripts/smoke_cli.sh
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```

The script prints each CLI command before executing it and mirrors output to `intermediate/logs/smoke_cli.log`. Without `--rdc`, it runs entry smoke only. Pass an explicit `.rdc` path for the daemon-backed capture chain; committed fixtures are for repository tests and are excluded from release packages. If a daemon-backed command times out, it prints the failed command, daemon status, known context state fields, and cleanup results.

Remote-only smoke still uses CLI transport. Watch for `remote_handle_consumed` after `rd.capture.open_replay` binds a remote handle to a session.

For task-level recipes, see [rdc-tool-native agent playbook](rdc-tool-native-agent-playbook.md). The full generated tool list is [Tool reference](tool-reference.md).

Texture export is truthful about requested precision. `file_format` is the only format parameter. Explicit HDR/EXR/DDS requests fail closed with structured format metadata if the encoder cannot produce that format; PNG is display-mapped evidence, not proof of retained HDR data.
