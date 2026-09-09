# AGENTS.md

Scope: this file governs the `rdx-tools` CLI project (`rdx/`, `cli/`, `docs/`, `scripts/`, `tests/`, `spec/`).

`rdx-tools` is CLI-only. Use `rdx` as the public user command; keep `rdx.bat`, `bin/rdx`, and `python cli/run_cli.py` as package launcher files.

## Contract consistency

If CLI docs, catalog, tests, or implementation disagree, use the public contract, requested behavior, and observed evidence to identify the incorrect side. Correct it and synchronize affected references; a documentation error alone does not require a runtime change.

Consult and update documentation according to the affected topic:

- Session state and lifecycle: docs/session-model.md.
- Agent-facing workflows: docs/agent-model.md.
- Failure diagnostics and recovery: docs/troubleshooting.md.
- Documentation generation and publishing rules: docs/doc-governance.md.
- Android remote smoke: docs/android-remote-cli-smoke-prompt.md.

Remote self-tests should cover `rd.remote.connect`, `rd.remote.ping`, and `rd.capture.open_replay`.

## preview / 几何观察面改动

涉及 preview / 几何观察面改动时，必须同步检查 `rd.session.open_preview`、`preview.display`、`preview_geometry_smoke.py` 与 CLI 文档。

Complete the requested changes and relevant validation before delivery; continue past the first implementation until those checks pass, or report a concrete blocker with evidence.
