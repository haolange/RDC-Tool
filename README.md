# rdx-tools

`rdx-tools` is a CLI-only RenderDoc `.rdc` runtime package for Windows x64 local replay plus remote Android replay. The current interface exposes JSON-first `rd.*` operations through the `rdx` command; `rdx tools list` derives the available set from the operation definitions.

## Entry Points

```bat
rdx --version
rdx version --json
rdx --json doctor
rdx tools list --json
rdx tools describe rd.pipeline.get_state --json
rdx context status --json
rdx capture open --file "C:\path\capture.rdc" --frame-index 0
rdx context update --key notes --value "triaged" --json
rdx vfs ls --path / --format tsv
rdx event list --format tsv
rdx pipeline show --event-id 42 --format json
rdx resource list --format tsv
rdx completion powershell
```

```bash
bash resources/tools/bin/rdx --json doctor
```

The thin Windows launcher has no private CLI flags; `rdx --json doctor` calls the same native Python entrypoint.

## Smoke

Agent platforms should run smoke through bash so every CLI step is visible in the terminal:

```bash
bash scripts/smoke_cli.sh
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```

The smoke script calls `bin/rdx` directly for `doctor`, lightweight discovery, and, when `--rdc` is passed, the daemon-backed capture chain. The repository includes small public `.rdc` fixtures for tests only; release packages exclude them. Full smoke can pass an explicit local or remote capture path. By default the script writes below `intermediate/logs`; set `RDX_INTERMEDIATE_ROOT` to isolate a run under one owned temporary root.

## Install

Release packages are self-contained Windows x64 zips. See [Install](docs/install.md).

## Session State

Use `rdx context status` to read context state and `rdx context update` to update notes, focus, and agent-visible metadata. `--daemon-context <id>` selects the continuous runtime namespace; omitting it uses `default`. Multiple daemon contexts are isolated from each other, and callers choose the context id they want to operate on. The state includes `session_locator`, current capture/session IDs, preview state, and remote lifecycle fields. `remote_handle_consumed` means a remote handle has been bound to a replay session and must not be reused as a free remote connection.

## Preview CLI Contract

`session preview on|status|off` is daemon-backed through `rd.session.open_preview`. `rdx context status` reports `rd.session.get_context.preview` and `preview.display`; the preview surface should expose the complete framebuffer（完整 framebuffer）instead of cropping viewport / scissor state.

## Docs

- [Session model](docs/session-model.md)
- [Agent model](docs/agent-model.md)
- [Install](docs/install.md)
- [Agent integration](docs/agent-integration.md)
- [Stability](docs/stability.md)
- [Documentation governance](docs/doc-governance.md)
- [Tools](docs/tools.md)
- [Tool reference](docs/tool-reference.md)
- [Tool interface convergence](docs/tool-interface-upgrade.md)
- [rdx-native agent playbook](docs/rdx-native-agent-playbook.md)
- [Fixture strategy](docs/fixture-strategy.md)
- [Scripts](scripts/README.md)

## License

`rdx-tools` is Apache-2.0. Test-only third-party fixture attribution is tracked in [Third-Party Notices](THIRD_PARTY_NOTICES.md).

### Windows entrypoints

Double-click `install.cmd` for installation; run `rdx` from the installed `bin` PATH entry. The thin `bin/rdx.cmd` calls bundled Python directly. Embedding hosts bind bundled Python and the matching `cli/run_cli.py`, never a batch or PowerShell launcher. See [installation](docs/install.md).

`rdx --daemon-context case-1 batch queries.jsonl` executes predetermined read-only catalog operations sequentially in one client process. Each JSONL input contains `operation` and `args`; output is one canonical envelope per attempted entry, with `meta.batch.index` and `operation`. The first error stops the batch; no retry, skip or automatic daemon shutdown. See [playbook](docs/rdx-native-agent-playbook.md).
