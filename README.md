# RDC-Tool

RenderDoc `.rdc` replay CLI for agents and humans.

**Platform:** Windows x64 local replay + Android remote replay. **Current baseline:** RenderDoc 1.45.

Download the Windows x64 zip from [Releases](https://github.com/haolange/RDC-Tool/releases), extract it, run `install.cmd`, open a new terminal, then run:

```bat
rdc-tool --json doctor
```

Source checkouts require Git LFS and `git lfs pull`. `binaries/windows` and `binaries/android` are required replay runtime, not examples; deleting them or leaving LFS pointers prevents replay. Release zips include these files.

**License:** [Apache-2.0](LICENSE). See [installation](docs/install.md), [stability](docs/stability.md), and the [session model](docs/session-model.md).

## Entry Points

The current release is **1.0.2**. It includes the session worker/transport timeout correction and the complete Apache-2.0 license in the archive. For RDC-Agent, select the extracted `rdc-tool` folder in Settings → Tools; standalone installation and PATH changes are optional.

```bat
rdc-tool --version
rdc-tool version --json
rdc-tool --json doctor
rdc-tool tools list --json
rdc-tool tools describe rd.pipeline.get_state --json
rdc-tool context status --json
rdc-tool capture open --file "C:\path\capture.rdc" --frame-index 0
rdc-tool context update --key notes --value "triaged" --json
rdc-tool vfs ls --path / --format tsv
rdc-tool event list --format tsv
rdc-tool pipeline show --event-id 42 --format json
rdc-tool resource list --format tsv
rdc-tool completion powershell
```

```bash
bash bin/rdc-tool --json doctor
```

The thin Windows launcher has no private CLI flags; `rdc-tool --json doctor` calls the same native Python entrypoint.

## Smoke

Agent platforms should run smoke through bash so every CLI step is visible in the terminal:

```bash
bash scripts/smoke_cli.sh
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```

The smoke script calls `bin/rdc-tool` directly for `doctor`, lightweight discovery, and, when `--rdc` is passed, the daemon-backed capture chain. The repository includes small public `.rdc` fixtures for tests only; release packages exclude them. Full smoke can pass an explicit local or remote capture path. By default the script writes below `intermediate/logs`; set `RDC_TOOL_INTERMEDIATE_ROOT` to isolate a run under one owned temporary root.

## Install

Release packages are self-contained Windows x64 zips. See [Install](docs/install.md).

## Session State

Use `rdc-tool context status` to read context state and `rdc-tool context update` to update notes, focus, and agent-visible metadata. `--daemon-context <id>` selects the continuous runtime namespace; omitting it uses `default`. Multiple daemon contexts are isolated from each other, and callers choose the context id they want to operate on. The state includes `session_locator`, current capture/session IDs, preview state, and remote lifecycle fields. `remote_handle_consumed` means a remote handle has been bound to a replay session and must not be reused as a free remote connection.

## Preview CLI Contract

`session preview on|status|off` is daemon-backed through `rd.session.open_preview`. `rdc-tool context status` reports `rd.session.get_context.preview` and `preview.display`; the preview surface should expose the complete framebuffer（完整 framebuffer）instead of cropping viewport / scissor state.

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
- [rdc-tool-native agent playbook](docs/rdc-tool-native-agent-playbook.md)
- [Fixture strategy](docs/fixture-strategy.md)
- [Scripts](scripts/README.md)

## License

`rdc-tool` is Apache-2.0. Test-only third-party fixture attribution is tracked in [Third-Party Notices](THIRD_PARTY_NOTICES.md).

### Windows entrypoints

Double-click `install.cmd` for installation; run `rdc-tool` from the installed `bin` PATH entry. The thin `bin/rdc-tool.cmd` calls bundled Python directly. Embedding hosts bind bundled Python and the matching `cli/run_cli.py`, never a batch or PowerShell launcher. See [installation](docs/install.md).

`rdc-tool --daemon-context case-1 batch queries.jsonl` executes predetermined read-only catalog operations sequentially in one client process. Each JSONL input contains `operation` and `args`; output is one canonical envelope per attempted entry, with `meta.batch.index` and `operation`. The first error stops the batch; no retry, skip or automatic daemon shutdown. See [playbook](docs/rdc-tool-native-agent-playbook.md).

## RenderDoc runtime baseline

The current assembled and verified baseline is **RenderDoc 1.45**. RDC-Tool does not track every upstream minor release: a newer runtime becomes the baseline only after matching runtime packaging, catalog checks, tests and release gates pass. RenderDoc 1.44 and earlier official GUI releases are not separate assembly targets. Use the replay path matching this bundled runtime. Capture-format compatibility follows upstream RenderDoc.

RDC-Agent **0.6.x** currently ships alongside RDC-Tool **1.0.2** and the current RenderDoc **1.45** runtime. Catalog definitions and fingerprints, not package version numbers, authorize operations. Local PNG export does not prove Android device presentation.
