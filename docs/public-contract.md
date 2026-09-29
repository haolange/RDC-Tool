# Public Contract

The public user surface is the `rdc-tool` CLI command. Release packages also include platform launcher files such as `bin/rdc-tool.cmd`, `bin/rdc-tool`, and `bundled-python cli/run_cli.py` for installation diagnostics and maintainer use.

`rdc-tool` keeps the canonical JSON envelope stable while replacing the public operation set. Use `rdc-tool version --json` to inspect the tool version, schema version, platform, entrypoints, and public contract metadata.

The current contract removes obsolete and misleading operations without aliases or forwarding handlers. The code-owned definitions, generated catalog, generated reference, registry, and CLI discovery must describe the same operation set and content fingerprint, derived from code. The migration table in [tool-interface-upgrade.md](tool-interface-upgrade.md) explains replacements; it is documentation and is never consulted at runtime.

`--daemon-context <id>` selects an isolated CLI runtime namespace. It is not an ownership claim or task handoff mechanism; callers choose and manage context ids in their own orchestration layer.

The JSON envelope remains stable across this interface break. Unknown operations and unknown parameters fail before execution; the runtime does not translate old names or ambiguous parameter aliases.

Canonical JSON never emits the non-standard bare numeric tokens `NaN`, `Infinity`, or `-Infinity`. When native shader or capture data contains a non-finite floating-point value, the corresponding value remains present as the explicit string `"NaN"`, `"Infinity"`, or `"-Infinity"`; finite numbers remain numbers. A marker describes the observed native value, not a substituted zero or a successful measurement. Consumers must treat those strings as non-finite data when interpreting numeric arrays.

## Android connection ownership

Android connect reuses an existing helper without APK installation, configuration changes or activity launch. If none is running, connect starts its own helper. The owned-helper path resolves RenderDoc's config location from the device SDK level (`Android/data` below 30, `Android/media` from 30 onward), preserves an existing `renderdoc.conf`, creates an empty default only when the file is absent, and rejects an unknown SDK or file state instead of overwriting it. A helper PID is not evidence of service occupancy: success requires the actual RenderDoc connection and Ping. A single timeout budget covers bootstrap and connection; socket readiness waits no more than 15 seconds. Borrowed services use connection-only shutdown; only verified owned PIDs and ADB forwards may be removed. No additional user mode or versioned interface is introduced.

Native device presentation is part of `rd.session.observe`, using the owning remote replay connection. Its `remote_display` identifies the applied event, selected texture and fresh completion sequence, with `presented`, `unavailable`, `unsupported`, or `not_applicable` status. No-color observations clear the device surface. PNG output does not establish presentation. Native client/helper protocol and runtime manifests are paired; an incompatible helper is rejected without compatibility forwarding. The reusable Android development signing keystore is retained outside disposable build directories, so future same-install helper upgrades preserve app data.

## Restored data capabilities

Capture thumbnails read embedded capture data without replay. Structured API queries expose captured chunks, typed fields and bounded continuation, not a complete process API trace. Resource details expose recorded initialization chunks and relationships; descriptor stores expose bounded ranges including empty slots and unaccessed descriptors.

Requested pipeline sections preserve viewport/scissor and output-slot indices and native facts. API applicability, missing data and failure remain distinct. Dynamic declarations absent from capture data remain unknown.

Texture and buffer reads distinguish `current` and `capture_initial`. Initial reads require recorded initial-data provenance and restore the original event; unavailable provenance is an error, never a current-data fallback. Restoration failure quarantines the session. Inline bytes are bounded; explicit output requests control persistence.

Whole-frame timing uses GPU timestamps for complete replay on a verified single queue. It excludes initial-state reconstruction and includes replay scheduling gaps. It is not original application frame time, CPU elapsed time or an event-duration sum. Method, range, unit, sampling conditions and individual samples accompany the result. Unsupported backends or incomplete queue coverage cannot produce a valid measurement.

## Mesh and shader provenance

Vertex input queries decode declared formats, offsets, bindings, indices and instance rates in original shader-input coordinates. Values retain their semantic names; unknown or ambiguous semantic mappings remain unsupported. Normalized integer NORMAL data is not automatically a geometric normal. Post-transform signature outputs use independently verified native packing and never substitute input attributes. OBJ normal/UV export requires explicit VS input space and matching float attributes; post-VS OBJ remains positions only.

Shader `resource_name` is the native display name (including autogenerated labels); `debug_name` is a custom shader resource name or null. `debug_source_files` contains source filenames and does not imply a shader debug name. Marker paths preserve parent ordering and duplicate labels.

`rd.shader.get_reflection` exposes RenderDoc's event-bound `debugInfo.debuggable`, `sourceDebugInformation`, and `debugStatus` under `reflection.debug_info`. A missing native field is `null`; an empty status is only an absent explanation. Source debug information and shader debuggability are separate facts, and `debuggable: true` does not guarantee that `DebugPixel` will return a usable debugger handle for a particular pixel. `rd.shader.debug_start` validates the target against Pixel History for the requested Event before accepting a native trace. An explicit target is authoritative; otherwise it selects from that Event's output targets and uses the default output only when none are available. Zero current-Event hits cannot establish a target-bound trace, even if native `debugger` is non-null. `ShaderDebugTrace` has no `valid` field.

`rd.shader.get_disassembly` accepts `auto`, an exact current disassembly target, or the explicit `SPIR-V ASM` raw request. An unavailable target is rejected before applying an event. Its canonical validation error includes the available targets and `effects_attempted: false` with `context_preserved: true`. Those fields certify only that this request did not attempt a replay effect; other disassembly failures still follow the ordinary uncertain-outcome recovery contract.
