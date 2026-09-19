# Stability

`rdx-tools` treats the CLI entrypoints and canonical JSON envelope as stable.

Stable public command:

- `rdx`

Packaged launcher files:

- `bin/rdx.cmd`
- `bin/rdx`
- `bundled-python cli/run_cli.py`

Stable agent-facing commands:

- `context status|update|list|clear`
- `vfs ls|cat|tree|resolve`
- `diff pipeline|image`
- `assert pipeline|image`

Stable JSON envelope fields:

- `schema_version`
- `tool_version`
- `result_kind`
- `ok`
- `data`
- `artifacts`
- `error`
- `meta`
- `projections`

Exit codes:

- `0`: success
- `1`: runtime, assertion, or tool operation failure
- `2`: argument, setup, installation, or bootstrap failure

Current contract policy:

- Code-owned operation definitions are the current contract. Removed names and parameter aliases are rejected.
- Consumers validate the actual catalog, fingerprint, parameter contracts and required capabilities; package release numbers do not select or authorize an interface.
- Tool-specific JSON `data` payloads may add fields such as shader `edit_plan` when they make agent usage safer without changing existing fields.
- JSON is the canonical agent protocol.
- TSV is a stable tabular projection only where a command documents table output, such as `vfs ls`.
- `--daemon-context <id>` selects a continuous runtime namespace; omitting it uses `default`.
- Interface changes update the same definitions, consumers, tests and documentation; do not introduce version-named runtime paths or compatibility aliases.

