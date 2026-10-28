# scripts

`scripts/` contains reusable smoke and release checks for the CLI-only package.

Common checks:

```bat
python -B spec/build_catalog.py --check
python -B scripts/check_markdown_health.py
python -B scripts/generate_tool_reference.py --check
python -B scripts/package_runtime.py
python -B scripts/package_release.py
python scripts/release_gate.py --require-smoke-reports --require-release-package
```

Smoke checks should be run through bash so every CLI call is visible to the agent terminal:

```bash
bash scripts/smoke_cli.sh
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context cli-smoke
```

`smoke_cli.sh` directly invokes `bin/rdc-tool` for `doctor`, tool discovery, and, when `--rdc` is passed, the capture/session chain. The release gate checks `intermediate/logs/smoke_cli.log` only when smoke reports are required. Set `RDC_TOOL_INTERMEDIATE_ROOT` before tests or smoke when a task needs one isolated, removable output root.

`generate_tool_reference.py` reads the code-owned operation definitions directly. `spec/tool_catalog.json` is a generated artifact and is never an alternate authoring input.

`preview_geometry_smoke.py` validates preview window geometry and should stay aligned with CLI preview behavior.

`rdc_tool_install.ps1` handles install, upgrade, uninstall, and doctor for self-contained Windows x64 release packages. Upgrade compares existing files by size and SHA-256 and leaves byte-identical files untouched, including an in-use bundled Python executable. A changed file that is locked still fails the upgrade; verify the installed catalog and code after retrying. Use `-DryRun` before mutating a real machine PATH.

Release packaging requires a clean committed source checkout. The release manifest and SBOM record the full `source_revision`; the gate checks this revision and every shipped source file against HEAD. Upgrade removes only files owned by the prior release manifest that no longer appear in the new manifest.
