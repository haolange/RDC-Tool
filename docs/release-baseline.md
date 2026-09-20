# Release Baseline

Before release, run:

```bat
python spec/validate_catalog.py
python scripts/generate_tool_reference.py --check
python -m pytest tests -q
python scripts/check_markdown_health.py
python scripts/package_release.py
python scripts/release_gate.py --require-smoke-reports --require-release-package
```

Run smoke directly through bash before the release gate when smoke evidence is required:

```bash
bash scripts/smoke_cli.sh --context release-smoke
bash scripts/smoke_cli.sh --rdc "C:/path/sample.rdc" --context release-smoke
```

Agent platforms should see each CLI command and result in the bash output. The smoke entry writes `intermediate/logs/smoke_cli.log`; `release_gate.py --require-smoke-reports` checks that log for `[smoke] PASS`. `preview_geometry_smoke.py` may produce JSON or markdown evidence for preview geometry, but that evidence is separate from the release gate smoke report. Full release smoke uses an explicit `.rdc` sample before tagging; committed repository fixtures are test-only and release packages do not bundle capture samples.

## RenderDoc runtime baseline

The current assembled and verified baseline is **RenderDoc 1.45**. RDC-Tool does not track every upstream minor release: a newer runtime becomes the baseline only after matching runtime packaging, catalog checks, tests and release gates pass. RenderDoc 1.44 and earlier official GUI releases are not separate assembly targets. Use the replay path matching this bundled runtime. Capture-format compatibility follows upstream RenderDoc.

RDC-Agent **0.6.x** pairs with RDC-Tool **1.0.0** and the current RenderDoc **1.45** runtime. Catalog definitions and fingerprints, not package version numbers, authorize operations. Local PNG export does not prove Android device presentation.
