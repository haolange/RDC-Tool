# Documentation Governance

This package is CLI-only. Documentation must describe shell entrypoints and canonical JSON behavior.

Keep navigation links current and follow [../AGENTS.md](../AGENTS.md). User-facing docs should mention CLI commands, not Python bootstrap internals, except in maintainer sections.

User-facing installation and quickstart docs must not tell users to run package managers, create virtual environments, or restore dependencies from a lock file. GA artifacts are self-contained; dependency provenance is tracked through `pyproject.toml`, the bundled runtime manifest, license inventory, and SBOM.

`rdc_tool/operation_definitions.py` is the only operation-definition source. `spec/tool_catalog.json` and `docs/tool-reference.md` are generated outputs; neither may be patched with a second metadata overlay. Regenerate the catalog with `python -B spec/build_catalog.py`, regenerate the reference with `python -B scripts/generate_tool_reference.py`, and verify both with their `--check` modes. Counts and fingerprints come from the code-owned definition set.

An interface removal may be explained in `tool-interface-upgrade.md`, but that table must not become an alias map or runtime input. Examples, generated references, smoke scripts, and tests must use current names and parameters. Workflow advice and expert judgment belong in agent Skills rather than operation descriptions.

Changes that touch `rd.session.open_preview` or preview geometry must keep `preview_geometry_smoke.py` and the user-facing preview documentation synchronized.

Fixture policy: small public `.rdc` captures may live under `tests/fixtures/` only when source, size, SHA256, and license are documented. Release packages must exclude `.rdc` fixtures and test-only assets.

The default release gate validates the source tree and records package verification as skipped. GA qualification must pass `--release-package <zip>` for one explicit artifact or `--require-release-package` to require and select the newest package under `dist/`. Both GA modes keep checksum, package-manifest, and source-tree matching strict; an unrelated old package under `dist/` must not affect a source-only gate.
