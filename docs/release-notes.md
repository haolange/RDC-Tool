# Release Notes

## Operation interface convergence

- Removed redundant projections, workflow/report wrappers and generic file utilities. The subsequent 73-operation review identified 18 necessary capability gaps; restoration adds four real operations and expands existing queries. The current set is derived from definitions, with no old-name aliases or forwarding handlers.
- Moved operation names, schemas, prerequisites, scope, effects, evidence kinds, and path inputs into one code-owned definition set. Catalog, discovery, and reference output carry a deterministic content fingerprint.
- Added `rdx tools describe <name>` and full catalog discovery. `rd.core.list_tools(query=...)` now owns canonical query discovery.
- Consolidated pipeline state, event tree browsing, resource kinds and usage, texture statistics, pixel-history targets, and VS/GS post-transform mesh reads into bounded canonical operations.
- Texture statistics, histograms, and numeric differences reuse in-memory readback. Unsupported layouts, non-finite inputs, invalid ranges, and backend read failures fail explicitly.
- Kept `rd.session.observe` window-free and atomic. Standalone preview remains an independent human-facing lifecycle.
- See [Tool interface convergence](tool-interface-upgrade.md) for every previous operation's disposition.

## CLI runtime baseline

- `rdx-tools` is a CLI-only RenderDoc `.rdc` runtime.
- The public user command is `rdx`; release packages keep `bin/rdx.cmd`, `bin/rdx`, and `bundled-python cli/run_cli.py` as launcher files.
- This is the first GA public contract baseline. Pre-GA ownership, lease, baton, handoff, and runtime materialization experiments are intentionally outside the public contract.
- CLI daemon contexts are isolated runtime namespaces chosen by the caller; business orchestration remains outside this package.
- Workers use the packaged runtime binaries in place instead of materializing per-run binary copies.
- `rd.remote.connect` documents both direct RenderDoc endpoints and Android adb bootstrap via `options.transport`.
- Added stable `version` and shell completion commands.
- Release packaging produces a Windows x64 self-contained zip with checksums, manifest, license inventory, and SBOM.
- Install lifecycle is handled by `scripts/rdx_install.ps1`.
- Release validation uses catalog validation, pytest, markdown health, bash CLI smoke, manifest integrity, bundled runtime checks, and package verification.

