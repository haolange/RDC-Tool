#!/usr/bin/env python3
"""Standalone CLI launcher for rdc-tool."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _bootstrap_tools_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    candidate = script_dir.parent
    env_root = os.environ.get("RDC_TOOL_ROOT", "").strip()
    if env_root:
        env_path = Path(env_root).expanduser().resolve()
        if env_path.is_dir():
            if env_path != candidate:
                print(
                    f"[RDC-Tool][WARN] RDC_TOOL_ROOT overrides launcher root ({candidate}); using {env_path}",
                    file=sys.stderr,
                )
            candidate = env_path
        else:
            print(
                f"[RDC-Tool][WARN] invalid RDC_TOOL_ROOT='{env_path}', fallback to {candidate}",
                file=sys.stderr,
            )

    resolved = candidate.resolve()
    if str(resolved) not in sys.path:
        sys.path.insert(0, str(resolved))
    os.environ.setdefault("RDC_TOOL_ROOT", str(resolved))
    return resolved


TOOLS_ROOT = _bootstrap_tools_root()

from rdc_tool import __version__ as TOOL_VERSION
from rdc_tool.io_utils import safe_json_text, safe_stream_write
from rdc_tool.runtime_requirements import missing_dependencies


def _normalize_context(value: str | None) -> str:
    raw = str(value or "").strip()
    return raw if raw else "default"


def _init_pythonpath() -> Path:
    from rdc_tool.runtime_paths import ensure_tools_root_env, ensure_runtime_dirs

    root = ensure_tools_root_env()
    ensure_runtime_dirs()
    os.environ.setdefault("RDC_TOOL_ROOT", str(root))
    os.environ.setdefault("RDC_TOOL_CONTEXT_ID", _normalize_context(os.environ.get("RDC_TOOL_CONTEXT_ID")))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _check_deps() -> list[str]:
    return missing_dependencies()


def _emit_result(payload: dict[str, object]) -> None:
    safe_stream_write(safe_json_text(payload) + "\n", sys.stdout)


def _write_out(text: str) -> None:
    safe_stream_write(text + "\n", sys.stdout)


def _write_err(text: str) -> None:
    safe_stream_write(text + "\n", sys.stderr)


def _launcher_prog(default: str) -> str:
    return str(os.environ.get("RDC_TOOL_LAUNCHER_PROG") or default).strip() or default


def _print_launcher_help() -> None:
    prog = _launcher_prog("python cli/run_cli.py")
    for line in (
        f"usage: {prog} [--json] [--daemon-context <id>] <command> ...",
        "commands:",
        "  version",
        "  doctor",
        "  tools list|search|describe",
        "  daemon start|stop|status",
        "  context status|update|list|clear",
        "  session preview on|off|status",
        "  completion powershell|bash|zsh|fish",
        "  call <operation> [--args-json ... | --args-file ...] [--format json|tsv] [--remote]",
        "  batch <jsonl> [--remote]",
        "  capture open|status",
        "  vfs ls|cat|tree|resolve",
        "  diff pipeline|image",
        "  assert pipeline|image",
        "",
        "examples:",
        f"  {prog} --version",
        f"  {prog} version --json",
        f"  {prog} --json doctor",
        f"  {prog} completion powershell",
        f"  {prog} tools search pipeline --json",
        f"  {prog} daemon start --daemon-context local",
        f"  {prog} context status --daemon-context local --json",
        f"  {prog} context update --daemon-context local --key notes --value triaged --json",
        f"  {prog} context clear --daemon-context local",
        f"  {prog} capture open --file D:\\path\\capture.rdc --frame-index 0 --preview",
        f"  {prog} session preview on",
        f"  {prog} vfs ls --path / --format tsv",
    ):
        _write_out(line)


def _is_doctor_command(argv: list[str]) -> bool:
    skip_next = False
    for item in argv:
        if skip_next:
            skip_next = False
            continue
        if item in {"--daemon-context", "--context-id"}:
            skip_next = True
            continue
        if item == "doctor":
            return True
        if item.startswith("-"):
            continue
        return False
    return False


def _extract_context(argv: list[str]) -> str:
    for index, item in enumerate(argv):
        if item in {"--daemon-context", "--context-id"} and index + 1 < len(argv):
            return _normalize_context(argv[index + 1])
    return _normalize_context(os.environ.get("RDC_TOOL_CONTEXT_ID"))


def _first_command(argv: list[str]) -> str:
    skip_next = False
    for item in argv:
        if skip_next:
            skip_next = False
            continue
        if item in {"--daemon-context", "--context-id"}:
            skip_next = True
            continue
        if item.startswith("-"):
            continue
        return item
    return ""


def _is_version_command(argv: list[str]) -> bool:
    return "--version" in argv or _first_command(argv) == "version"


def _emit_version(argv: list[str]) -> None:
    root = TOOLS_ROOT.resolve()
    if "--json" not in argv:
        _write_out(f"rdc-tool {TOOL_VERSION}")
        return
    _emit_result(
        {
            "schema_version": "3.0.0",
            "tool_version": TOOL_VERSION,
            "result_kind": "rdc_tool.version",
            "ok": True,
            "data": {
                "tool_version": TOOL_VERSION,
                "schema_version": "3.0.0",
                "platform": "windows-x64" if os.name == "nt" else sys.platform,
                "tools_root": str(root),
                "public_commands": ["rdc-tool"],
                "entrypoints": {
                    "windows_cmd": str(root / "bin/rdc-tool.cmd"),
                    "posix_shell": str(root / "bin" / "rdc-tool"),
                    "python_cli": str(root / "cli" / "run_cli.py"),
                },
                "compatibility": {
                    "stability": "1.x",
                    "json_envelope": "stable",
                },
            },
            "artifacts": [],
            "error": None,
            "meta": {"transport": "cli"},
            "projections": {},
        }
    )


def _emit_minimal_doctor(argv: list[str], missing: list[str]) -> None:
    root = TOOLS_ROOT.resolve()
    payload = {
        "ok": False,
        "result_kind": "rdc_tool.doctor",
        "error_code": "setup_incomplete",
        "error_message": "rdc-tool setup is incomplete",
        "context_id": _extract_context(argv),
        "details": {
            "tools_root": str(root),
            "dependencies": {
                "missing": sorted(missing),
                "auth_required": False,
            },
            "launchers": {
                "windows_cmd": str(root / "bin/rdc-tool.cmd"),
                "windows_cmd_exists": (root / "bin/rdc-tool.cmd").is_file(),
                "posix_shell": str(root / "bin" / "rdc-tool"),
                "posix_shell_exists": (root / "bin" / "rdc-tool").is_file(),
                "python_cli": str(root / "cli" / "run_cli.py"),
                "python_cli_exists": (root / "cli" / "run_cli.py").is_file(),
            },
        },
    }
    _emit_result(payload)


def main(argv: list[str] | None = None) -> int:
    from rdc_tool.environment import validate_environment
    try:
        validate_environment()
    except ValueError as exc:
        _emit_result({"schema_version": "3.0.0", "ok": False, "result_kind": "rdc_tool.cli", "data": {}, "error": {"code": "setup_failure", "category": "validation", "message": str(exc)}})
        return 2
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        _write_err("[RDC-Tool] missing command, use --help for launcher usage.")
        return 2
    if _is_version_command(argv):
        _emit_version(argv)
        return 0
    if "-h" in argv or "--help" in argv:
        _print_launcher_help()
        return 0

    root = _init_pythonpath()
    missing = _check_deps()
    if missing and _is_doctor_command(argv):
        _emit_minimal_doctor(argv, missing)
        return 2
    if missing:
        _write_err(f"[RDC-Tool] missing dependencies: {', '.join(sorted(missing))}")
        _emit_result(
            {
                "ok": False,
                "error_code": "dependencies_missing",
                "error_message": ", ".join(sorted(missing)),
                "context_id": os.environ.get("RDC_TOOL_CONTEXT_ID", "default"),
            }
        )
        return 1

    from rdc_tool.runtime_bootstrap import bootstrap_renderdoc_runtime
    from rdc_tool.runtime_paths import ensure_runtime_dirs

    ensure_runtime_dirs()
    bootstrap_renderdoc_runtime(probe_import=False)

    try:
        from rdc_tool import cli as rdc_tool_cli
    except Exception as exc:
        _write_err(f"[RDC-Tool] startup failed: {exc.__class__.__name__}: {exc}")
        return 1

    try:
        if argv is None:
            return rdc_tool_cli.main()
        return rdc_tool_cli.main()
    except Exception as exc:
        _write_err(f"[RDC-Tool] startup failed: {exc.__class__.__name__}: {exc}")
        _emit_result(
            {
                "ok": False,
                "error_code": "runtime_error",
                "error_message": f"{exc}",
                "context_id": os.environ.get("RDC_TOOL_CONTEXT_ID", "default"),
            }
        )
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _write_err(f"[RDC-Tool] startup failed: {exc.__class__.__name__}: {exc}")
        raise SystemExit(1)
