# Release Baseline

This document is the authority for native runtime identity, release qualification, and delivery. Keep the repository's default `binaries/` tree, generated capability catalog, user documentation, and RDC-Agent consumer contract aligned with each capability change. `intermediate/` candidates support isolated validation; they never replace the repository runtime used by formal packaging.

## Runtime identity and capability scope

- `rdc_tool/operation_definitions.py` is the source for operation contracts. `spec/tool_catalog.json` and `docs/tool-reference.md` are generated from it; the catalog fingerprint is a capability identity, not a package-version substitute.
- `binaries/windows/x64/manifest.runtime.json` is the source of truth for the repository-bundled runtime file set and hashes. Its `native_build` receipt must identify the frozen source tree and paired outputs. `rdc_tool.runtime_identity.native_manifest_status` and `rdc-tool --json doctor` validate the recorded identity; actual loaded-module paths and hashes are separate runtime observations.
- “Latest” means the newest committed release whose advertised capabilities and bundled runtime passed the required checks. It does not mean automatically tracking upstream RenderDoc, nor that every API, capture, driver, or device is supported.
- A capability or behavior change must keep the repository-root `binaries/` runtime set used by default, generated catalog and reference, affected documentation, and RDC-Agent consumer integration aligned. Update affected components; unchanged validated components may retain their recorded identities and evidence. A local candidate or alternate runtime directory is evidence for testing only; it cannot stand in for the root runtime in a release.

## Native runtime changes

When changing RenderDoc or helper runtime content, build from one frozen source tree and pair the Windows DLL/PYD and both Android helper APKs through one build receipt. Record source and upstream revisions, source-tree digest, build configuration/toolchain, output hashes, and runtime manifest identity. The Windows runtime file list must cover the complete native set, including `renderdoc.dll`, `renderdoc.pyd`, `renderdoc.json`, and required support files. Never copy a DLL alone into an older set, combine outputs from different source trees, or add an unverified fallback to PATH, another installation, SDK, or upstream binary.

Verify the repository file identity and, when runtime acceptance is claimed, record which Python, PYD, DLL, and helper APK are actually loaded or used. Build metadata or a disk hash does not prove a runtime was loaded, a device presented an image, or a capture is supported. If a required signing key, build input, device, or other external condition is unavailable, report that acceptance as blocked or unverified; do not treat a candidate, manifest, or local build as a pass for the missing evidence.

## Release qualification and delivery

Formal release packaging uses a clean committed checkout and the repository-root `binaries/` tree. `python scripts/package_release.py` requires a verified paired native manifest, runs the source/repository-runtime gate, builds the complete ZIP, then verifies that staged archive and its identity before accepting the output. It rejects dirty source, stale or incomplete runtime identity, package mismatch, or failed checks. Do not copy individual binaries into the package or mix artifacts from an earlier build.

The required release CI run must pass the full test suite, catalog/document and source gates, formal packaging, and complete package verification before uploading the verified ZIP and its SHA256 checksum as a GitHub Actions artifact. The Actions artifact is package handoff only: CI does not create or publish a GitHub Release. A later authorized Release must use that same verified ZIP and checksum; do not rebuild, repackage, or recombine binaries after CI verification. Publishing still requires explicit authorization.

Local `--candidate-dir` output and `--runtime-root` are for isolated validation. They must not overwrite an existing destination and must carry a verified paired native identity. Passing a candidate check does not qualify it as the formal release package or authorize installation as an upgrade source.

For release smoke evidence, run the CLI smoke directly through bash so commands and results are visible:

```bash
bash scripts/smoke_cli.sh --context release-smoke
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context release-smoke
```

The smoke entry writes `intermediate/logs/smoke_cli.log`; `release_gate.py --require-smoke-reports` requires `[smoke] PASS`. Preview-geometry evidence is separate. Use an explicit `.rdc` sample for full replay smoke; committed repository fixtures are test-only and are not bundled in the release package. Smoke evidence does not replace package verification or device-presentation evidence.
