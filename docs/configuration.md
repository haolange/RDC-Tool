# Configuration

## User configuration

For external users, prefer the self-contained Windows x64 release package and `scripts/rdx_install.ps1`. The release package runs without installing Python, creating a virtual environment, running a package manager, or carrying a dependency lock file.

Set `RDX_TOOLS_ROOT` only when launching `bin/rdx` from another directory and the tools root cannot be inferred from the entrypoint location.

## Maintainer configuration

`RDX_PYTHON` is a maintainer/debug override for Python selection. It is not part of the user install path and should not be required by a GA release package.

Runtime artifacts live under `intermediate/runtime`, `intermediate/artifacts`, and `intermediate/logs` during development, tests, and release validation. Set `RDX_INTERMEDIATE_ROOT` for an isolated task-owned test or smoke root; every runtime path derives from it.

`runtime_limits.max_contexts` counts **live occupancy** only: a context occupies a slot when its daemon pid, worker pid, or owner pid is running, or the current process holds a live replay/preview. Persisted `runtime_state_*.json` files are namespaces for recovery and listing; empty or dead records do not consume capacity. `RDX_INTERMEDIATE_ROOT` isolates a root. It does not replace live occupancy accounting.

## preview 运行约束

Preview uses `screen_cap_ratio` to keep the preview window bounded while preserving framebuffer geometry.
