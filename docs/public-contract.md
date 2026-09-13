# Public Contract

The public user surface is the `rdx` CLI command. Release packages also include platform launcher files such as `rdx.bat`, `bin/rdx`, and `python cli/run_cli.py` for installation diagnostics and maintainer use.

`rdx-tools` keeps the canonical JSON envelope stable while replacing the public operation set. Use `rdx version --json` to inspect the tool version, schema version, platform, entrypoints, and public contract metadata.

The current contract removes obsolete and misleading operations without aliases or forwarding handlers. The code-owned definitions, generated catalog, generated reference, registry, and CLI discovery must describe the same operation set and content fingerprint, derived from code. The migration table in [tool-interface-upgrade.md](tool-interface-upgrade.md) explains replacements; it is documentation and is never consulted at runtime.

`--daemon-context <id>` selects an isolated CLI runtime namespace. It is not an ownership claim or task handoff mechanism; callers choose and manage context ids in their own orchestration layer.

The JSON envelope remains stable across this interface break. Unknown operations and unknown parameters fail before execution; the runtime does not translate old names or ambiguous parameter aliases.

## Android connection ownership

Android connect reuses an existing helper without APK installation, configuration changes or activity launch. If none is running, connect starts its own helper. A helper PID is not evidence of service occupancy: success requires the actual RenderDoc connection and Ping. A single timeout budget covers bootstrap and connection; socket readiness waits no more than 15 seconds. Borrowed services use connection-only shutdown; only verified owned PIDs and ADB forwards may be removed. No additional user mode or versioned interface is introduced.

## Restored data capabilities

Capture thumbnails read embedded capture data without replay. Structured API queries expose captured chunks, typed fields and bounded continuation, not a complete process API trace. Resource details expose recorded initialization chunks and relationships; descriptor stores expose bounded ranges including empty slots and unaccessed descriptors.

Requested pipeline sections preserve viewport/scissor and output-slot indices and native facts. API applicability, missing data and failure remain distinct. Dynamic declarations absent from capture data remain unknown.

Texture and buffer reads distinguish `current` and `capture_initial`. Initial reads require recorded initial-data provenance and restore the original event; unavailable provenance is an error, never a current-data fallback. Restoration failure quarantines the session. Inline bytes are bounded; explicit output requests control persistence.

Whole-frame timing uses GPU timestamps for complete replay on a verified single queue. It excludes initial-state reconstruction and includes replay scheduling gaps. It is not original application frame time, CPU elapsed time or an event-duration sum. Method, range, unit, sampling conditions and individual samples accompany the result. Unsupported backends or incomplete queue coverage cannot produce a valid measurement.
