"""RDC-Tool CLI adapter backed by the daemon-owned runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rdc_tool.platform import process
from rdc_tool.platform import host as platform_host
from rdc_tool.core.assert_service import AssertService
from rdc_tool import __version__ as TOOL_VERSION
from rdc_tool import timeout_policy
from rdc_tool.core.contracts import SCHEMA_VERSION, canonical_error, canonical_success
from rdc_tool.daemon.client import (
    DaemonExecInterrupted,
    attach_client,
    cleanup_stale_daemon_states,
    clear_context,
    daemon_request,
    detach_client,
    ensure_daemon,
    heartbeat_client,
    stop_daemon,
)
from rdc_tool.daemon.state import load_state, public_view
from rdc_tool.io_utils import safe_json_text, safe_stream_write
from rdc_tool.python_runtime import bundled_python_executable, current_python_runtime_details, validate_bundled_python_layout
from rdc_tool.runtime_catalog import SOURCE_PATH, catalog_payload, describe_operation, load_tool_catalog
from rdc_tool.runtime_paths import (
    HOST_LAYOUTS,
    UnsupportedHost,
    android_binaries_root,
    artifacts_dir,
    binaries_root,
    binding_module_path,
    cli_runtime_dir,
    ensure_runtime_dirs,
    host_layout,
    logs_dir,
    native_library_path,
    pymodules_dir,
    runtime_root,
    tools_root,
)
from rdc_tool.runtime_requirements import missing_dependencies
from rdc_tool.runtime_identity import loaded_runtime_identity, native_manifest_status

EXIT_OK = 0
EXIT_ASSERT_FAIL = 1
EXIT_RUNTIME_ERR = 1
EXIT_USAGE_ERR = 2


def _print_json(payload: Dict[str, Any]) -> None:
    safe_stream_write(safe_json_text(payload, indent=2) + "\n", sys.stdout)


def _write_stdout(text: str) -> None:
    safe_stream_write(text + "\n", sys.stdout)


def _exception_error_payload(result_kind: str, exc: Exception, *, transport: str = "cli") -> Dict[str, Any]:
    code = str(getattr(exc, "code", "") or "runtime_error")
    category = str(getattr(exc, "category", "") or "runtime")
    details = getattr(exc, "details", {})
    return canonical_error(
        result_kind=result_kind,
        code=code,
        category=category,
        message=str(exc),
        details=details if isinstance(details, dict) else {},
        transport=transport,
    )


def _parse_json_object(raw: str, *, source: str) -> Dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{source} must be a JSON object")
    return parsed


def _extract_raw_args_json_from_command_line(command_line: str) -> str:
    raw = str(command_line or "")
    if not raw:
        return ""

    match = re.search(r"(?:^|\s)--args-json\b", raw)
    if match is None:
        return ""

    idx = match.end()
    while idx < len(raw) and raw[idx].isspace():
        idx += 1
    if idx < len(raw) and raw[idx] == '"':
        idx += 1
    if idx >= len(raw) or raw[idx] not in "{[":
        return ""

    opening = raw[idx]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    start = idx
    while idx < len(raw):
        ch = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    return raw[start : idx + 1]
        idx += 1
    return ""


def _recover_args_json_from_command_line() -> str:
    return _extract_raw_args_json_from_command_line(process.raw_command_line() or "")


def _load_call_args(*, args_json: Optional[str] = None, args_file: Optional[str] = None) -> Dict[str, Any]:
    raw_json = str(args_json or "")
    raw_file = str(args_file or "").strip()
    has_json = bool(raw_json.strip())
    has_file = bool(raw_file)

    if has_json and has_file:
        raise ValueError("--args-json and --args-file are mutually exclusive")
    if has_file:
        path = Path(raw_file).expanduser()
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ValueError(f"--args-file could not be read: {path}") from exc
        try:
            return _parse_json_object(raw, source="--args-file")
        except json.JSONDecodeError as exc:
            raise ValueError(f"--args-file contains invalid JSON: {exc.msg}") from exc
    if has_json:
        try:
            return _parse_json_object(raw_json, source="--args-json")
        except json.JSONDecodeError as exc:
            recovered = _recover_args_json_from_command_line()
            if recovered and recovered != raw_json:
                try:
                    return _parse_json_object(recovered, source="--args-json")
                except json.JSONDecodeError:
                    pass
            raise ValueError(
                "--args-json contains invalid JSON: "
                f"{exc.msg}. Use --args-file args.json for multiline shader source. "
                "Example: rdc-tool call rd.shader.edit_and_replace --args-file args.json --format json"
            ) from exc
    return {}


def _extract(payload: Dict[str, Any], key: str, default: Any = None) -> Any:
    data = payload.get("data")
    if isinstance(data, dict) and key in data:
        return data.get(key, default)
    return payload.get(key, default)


_cli_owner_pid: Optional[int] = None


def _ensure_daemon_state(context: str) -> Dict[str, Any]:
    ok, message, state = ensure_daemon(context=context, owner_pid=_cli_owner_pid)
    if not ok:
        raise RuntimeError(message)
    if not state:
        raise RuntimeError("daemon did not return state")
    return state


_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def _write_progress_frame(frame: Dict[str, Any]) -> None:
    # Frames go to stderr as NDJSON; stdout carries only the final envelope.
    safe_stream_write(safe_json_text(frame) + "\n", sys.stderr)
    sys.stderr.flush()


def _daemon_exec(
    operation: str,
    args: Dict[str, Any],
    *,
    remote: bool = False,
    context: str = "default",
    request_id: Optional[str] = None,
    no_progress_ms: Optional[int] = None,
    on_frame: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    state = _ensure_daemon_state(context)
    try:
        resp = daemon_request(
            "exec",
            params={"operation": operation, "args": args, "transport": "cli", "remote": remote,
                    "request_id": request_id or _new_request_id(),
                    "no_progress_ms": timeout_policy.DEFAULT_NO_PROGRESS_MS if no_progress_ms is None else no_progress_ms,
                    "stream": on_frame is not None},
            context=context,
            state=state,
            on_frame=on_frame,
        )
    except DaemonExecInterrupted as exc:
        return canonical_error(result_kind=operation, code=exc.code, category=exc.category, message=str(exc),
                               details=exc.details, transport="cli")
    if not bool(resp.get("ok")):
        # The daemon refused the request itself (budget, duplicate id): the
        # operation never ran, and its result kind is still the operation.
        err = resp.get("error") if isinstance(resp.get("error"), dict) else {}
        return canonical_error(result_kind=operation, code=str(err.get("code") or "daemon_error"),
                               category=str(err.get("category") or "runtime"),
                               message=str(err.get("message") or "daemon rejected the request"),
                               details=err.get("details") if isinstance(err.get("details"), dict) else {},
                               transport="cli")
    result = resp.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("daemon returned invalid result payload")
    return result


def _daemon_status_payload(context: str) -> Dict[str, Any]:
    state = load_state(context=context)
    if not state:
        cleanup_stale_daemon_states(context=context)
        state = load_state(context=context)
    if not state:
        return canonical_success(
            result_kind="rdc_tool.daemon.status",
            data={"running": False, "state": {"context_id": context}},
            transport="cli",
        )
    try:
        resp = daemon_request("status", params={}, context=context, state=state)
    except Exception as exc:
        cleaned = cleanup_stale_daemon_states(context=context)
        refreshed = load_state(context=context)
        if not refreshed:
            return canonical_success(
                result_kind="rdc_tool.daemon.status",
                data={"running": False, "state": {"context_id": context}, "cleaned": cleaned},
                transport="cli",
            )
        return canonical_error(
            result_kind="rdc_tool.daemon.status",
            code=str(getattr(exc, "code", "") or "runtime_error"),
            category=str(getattr(exc, "category", "") or "runtime"),
            message="daemon status failed",
            details={
                "state": public_view(refreshed),
                "cleaned": cleaned,
                **(getattr(exc, "details", {}) if isinstance(getattr(exc, "details", {}), dict) else {}),
            },
            transport="cli",
        )
    result = resp.get("result", {}) if isinstance(resp, dict) else {}
    running = bool(result.get("running", True)) if isinstance(result, dict) else True
    daemon_state = result.get("state") if isinstance(result, dict) else {}
    return canonical_success(
        result_kind="rdc_tool.daemon.status",
        data={"running": running, "state": public_view(daemon_state if isinstance(daemon_state, dict) else state)},
        transport="cli",
    )


def _default_session_id(cli_value: Optional[str], context: str = "default") -> str:
    if cli_value:
        return str(cli_value)
    state = _ensure_daemon_state(context)
    resp = daemon_request("get_state", params={}, context=context, state=state)
    if bool(resp.get("ok")):
        daemon_state = resp.get("result", {}).get("state", {})
        if isinstance(daemon_state, dict):
            session_id = str(daemon_state.get("session_id") or "").strip()
            if session_id:
                return session_id
    snapshot = _daemon_exec("rd.session.get_context", {}, context=context)
    runtime_payload = snapshot.get("data", {}).get("runtime", {}) if isinstance(snapshot.get("data"), dict) else {}
    session_id = str(runtime_payload.get("session_id") or "").strip() if isinstance(runtime_payload, dict) else ""
    if session_id:
        return session_id
    raise RuntimeError("No session_id available. Use `rdc-tool capture open --file <rdc>` first or pass --session-id.")


def _tabular_request(output_format: str, call_args: Dict[str, Any]) -> Dict[str, Any]:
    if output_format != "tsv":
        return dict(call_args)
    projection = call_args.get("projection")
    if projection is None:
        normalized_projection: Dict[str, Any] = {}
    elif isinstance(projection, dict):
        normalized_projection = dict(projection)
    else:
        raise ValueError("projection must be a JSON object")
    normalized_projection["kind"] = "tabular"
    normalized_projection["include_tsv_text"] = True
    patched = dict(call_args)
    patched["projection"] = normalized_projection
    return patched


def _render_tabular(payload: Dict[str, Any]) -> None:
    projections = payload.get("projections")
    if not isinstance(projections, dict):
        raise RuntimeError("tool did not return tabular projection")
    tabular = projections.get("tabular")
    if not isinstance(tabular, dict):
        raise RuntimeError("tool did not return tabular projection")
    text = str(tabular.get("tsv_text") or "").strip()
    if text:
        safe_stream_write(text + "\n", sys.stdout)
        return
    columns = tabular.get("columns")
    rows = tabular.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise RuntimeError("tabular projection is missing columns/rows")
    _write_stdout("\t".join(str(col) for col in columns))
    for row in rows:
        if not isinstance(row, list):
            raise RuntimeError("tabular row must be a list")
        _write_stdout("\t".join("" if item is None else str(item) for item in row))


def _tabular_projection_error_payload(payload: Dict[str, Any], message: str) -> Dict[str, Any]:
    result_kind = str(payload.get("result_kind") or "rdc_tool.cli")
    return canonical_error(
        result_kind=result_kind,
        code="tabular_projection_missing",
        category="validation",
        message=message,
        details={
            "requested_format": "tsv",
            "source_result_kind": result_kind,
            "recovery_hint": "Use --format json unless the command documents a tabular projection.",
        },
        transport="cli",
    )


def _render_result(payload: Dict[str, Any], *, output_format: str = "json") -> bool:
    if output_format == "tsv" and bool(payload.get("ok")):
        try:
            _render_tabular(payload)
        except RuntimeError as exc:
            _print_json(_tabular_projection_error_payload(payload, str(exc)))
            return False
        return True
    _print_json(payload)
    return bool(payload.get("ok"))


def _tool_summary(tool: Dict[str, Any]) -> Dict[str, Any]:
    name = str(tool.get("name") or "")
    namespace = name.split(".")[1] if name.startswith("rd.") and len(name.split(".")) > 1 else ""
    return {
        "name": name,
        "namespace": namespace,
        "group": str(tool.get("group") or ""),
        "description": str(tool.get("description") or ""),
        "param_names": list(tool.get("param_names") or []),
        "prerequisites": list(tool.get("prerequisites") or []),
    }


def _cmd_doctor(args: argparse.Namespace) -> int:
    context = str(getattr(args, "daemon_context", "default") or "default")
    root = tools_root().resolve()
    ensure_runtime_dirs()

    try:
        layout = host_layout()
    except UnsupportedHost as exc:
        _print_json(canonical_error(result_kind="rdc_tool.doctor", code=exc.code, category="capability", message=str(exc),
                                    details={"host_target": exc.target, "supported_hosts": sorted(HOST_LAYOUTS)}, transport="cli"))
        return EXIT_RUNTIME_ERR
    dependencies_missing = missing_dependencies()
    python_ok, python_failures, python_details = validate_bundled_python_layout()

    native_library = native_library_path()
    binding_module = binding_module_path()
    renderdoc_failures = [str(path) for path in (native_library, binding_module) if not path.is_file()]

    android_failures = [str(android_binaries_root() / abi / f"org.renderdoc.renderdoccmd.{abi}.apk")
                        for abi in ("arm32", "arm64")
                        if not (android_binaries_root() / abi / f"org.renderdoc.renderdoccmd.{abi}.apk").is_file()]

    catalog = catalog_payload()

    try:
        daemon_status = _daemon_status_payload(context)
    except Exception as exc:  # noqa: BLE001
        daemon_status = canonical_error(
            result_kind="rdc_tool.daemon.status",
            code=str(getattr(exc, "code", "") or "runtime_error"),
            category=str(getattr(exc, "category", "") or "runtime"),
            message=str(exc),
            details=getattr(exc, "details", {}) if isinstance(getattr(exc, "details", {}), dict) else {},
            transport="cli",
        )

    launcher = root / layout.launcher
    python_cli = root / "cli" / "run_cli.py"
    from rdc_tool.host_tools import host_tools_status, validate_bundled_host_tools
    host_tools = host_tools_status()
    host_tools_ok, host_tool_failures = validate_bundled_host_tools()
    spirv_as = host_tools["spirv_as"]["path"]
    spirv_dis = host_tools["spirv_dis"]["path"]
    native_build = native_manifest_status(root)
    loaded_runtime = loaded_runtime_identity(binaries_root(), pymodules_dir())
    bundled_python = bundled_python_executable()
    details = {
        "product": "rdc-tool",
        "host_target": platform_host.host_target(),
        "tools_root": str(root),
        "context_id": context,
        "python": {
            "current": current_python_runtime_details(),
            "bundled": python_details,
            "bundled_python_ok": python_ok,
            "bundled_python_failures": python_failures,
            "bundled_python_executable": str(bundled_python) if bundled_python else None,
        },
        "dependencies": {
            "missing": dependencies_missing,
            "auth_required": False,
        },
        "renderdoc": {
            "native_build": native_build,
            "loaded_runtime": loaded_runtime,
            "layout_ok": not renderdoc_failures,
            "failures": renderdoc_failures,
            "native_library": str(native_library),
            "binding_module": str(binding_module),
        },
        "android_apk_failures": android_failures,
        "host_tools": host_tools,
        "host_tools_failures": host_tool_failures,
        "shader_tools": {
            "spirv_as": {
                "available": bool(spirv_as),
                "path": str(spirv_as or ""),
                "required_for": [
                    "rd.shader.edit_and_replace raw SPIR-V ASM when RenderDoc only accepts SPIRV binary encoding",
                ],
            },
            "spirv_dis": {
                "available": bool(spirv_dis),
                "path": str(spirv_dis or ""),
                "required_for": [
                    "rd.shader.get_disassembly raw SPIR-V ASM fallback when RenderDoc does not expose a raw ASM target",
                ],
            },
        },
        "catalog": {
            "source": SOURCE_PATH,
            "fingerprint": catalog["fingerprint"],
            "tool_count": catalog["tool_count"],
        },
        "runtime_dirs": {
            "runtime_root": str(runtime_root()),
            "cli_runtime_dir": str(cli_runtime_dir()),
            "artifacts_dir": str(artifacts_dir()),
            "logs_dir": str(logs_dir()),
        },
        "launchers": {
            "launcher": str(launcher),
            "launcher_exists": launcher.is_file(),
            "python_cli": str(python_cli),
            "python_cli_exists": python_cli.is_file(),
        },
        "daemon": daemon_status,
    }
    ok = (
        not dependencies_missing
        and python_ok
        and not android_failures
        and host_tools_ok
        and all(item["available"] for item in host_tools.values())
        and not renderdoc_failures
        and native_build["status"] != "invalid"
        and loaded_runtime["status"] != "mismatch"
        and launcher.is_file()
        and python_cli.is_file()
    )
    if ok:
        _print_json(canonical_success(result_kind="rdc_tool.doctor", data=details, transport="cli"))
        return EXIT_OK
    _print_json(
        canonical_error(
            result_kind="rdc_tool.doctor",
            code="setup_incomplete",
            category="environment",
            message="rdc-tool setup is incomplete",
            details=details,
            transport="cli",
        ),
    )
    return EXIT_RUNTIME_ERR


def _version_payload() -> Dict[str, Any]:
    root = tools_root().resolve()
    catalog = catalog_payload()
    return canonical_success(
        result_kind="rdc_tool.version",
        data={
            "tool_version": TOOL_VERSION,
            "schema_version": SCHEMA_VERSION,
            "platform": platform_host.host_target(),
            "tools_root": str(root),
            "public_commands": ["rdc-tool"],
            "entrypoints": {
                "windows_cmd": str(root / "bin/rdc-tool.cmd"),
                "posix_shell": str(root / "bin" / "rdc-tool"),
                "python_cli": str(root / "cli" / "run_cli.py"),
            },
            "compatibility": {
                "stability": "current-contract",
                "json_envelope": "stable",
            },
            # The operation catalog this installation serves; callers pair (tool_version, fingerprint) with the
            # catalog snapshot they were built against.
            "catalog": {
                "schema_version": catalog["schema_version"],
                "fingerprint": catalog["fingerprint"],
                "tool_count": catalog["tool_count"],
            },
        },
        transport="cli",
    )


def _cmd_version(args: argparse.Namespace) -> int:
    if bool(getattr(args, "json", False)):
        _print_json(_version_payload())
    else:
        _write_stdout(f"rdc-tool {TOOL_VERSION}")
    return EXIT_OK


def _parser_words(parser: argparse.ArgumentParser) -> set[str]:
    words: set[str] = set()
    for action in parser._actions:
        words.update(option for option in action.option_strings if option.startswith("--"))
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                words.add(name)
                words |= _parser_words(subparser)
    return words


def _completion_words() -> list[str]:
    """Every subcommand and long option the parser accepts, plus operation names."""
    tool_names = {str(item["name"]) for item in load_tool_catalog()}
    return sorted(_parser_words(_build_parser()) | tool_names)


def _completion_script(shell: str) -> str:
    words = _completion_words()
    if shell == "powershell":
        quoted = ", ".join("'" + word.replace("'", "''") + "'" for word in words)
        return "\n".join(
            [
                "Register-ArgumentCompleter -Native -CommandName rdc-tool -ScriptBlock {",
                "  param($wordToComplete, $commandAst, $cursorPosition)",
                f"  $words = @({quoted})",
                "  $words | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {",
                "    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)",
                "  }",
                "}",
                "",
            ]
        )
    if shell == "bash":
        joined = " ".join(words)
        return "\n".join(
            [
                "_rdc_tool_complete() {",
                "  local cur=\"${COMP_WORDS[COMP_CWORD]}\"",
                f"  COMPREPLY=( $(compgen -W \"{joined}\" -- \"$cur\") )",
                "}",
                "complete -F _rdc_tool_complete rdc-tool",
                "",
            ]
        )
    if shell == "zsh":
        joined = " ".join(words)
        return "\n".join(
            [
                "#compdef rdc-tool",
                "_rdc_tool() {",
                f"  compadd -- {joined}",
                "}",
                "_rdc_tool \"$@\"",
                "",
            ]
        )
    if shell == "fish":
        return "".join(f"complete -c rdc-tool -f -a '{word}'\n" for word in words)
    raise ValueError(f"unsupported completion shell: {shell}")


def _cmd_completion(args: argparse.Namespace) -> int:
    _write_stdout(_completion_script(str(args.shell)))
    return EXIT_OK


def _cmd_tools_list(args: argparse.Namespace) -> int:
    tools = load_tool_catalog() if getattr(args, "full", False) else [_tool_summary(tool) for tool in load_tool_catalog()]
    namespace = str(getattr(args, "namespace", "") or "").strip()
    if namespace:
        tools = [tool for tool in tools if tool.get("namespace") == namespace]
    limit = int(getattr(args, "limit", 0) or 0)
    if limit > 0:
        tools = tools[:limit]
    payload = canonical_success(
        result_kind="rdc_tool.tools.list",
        data={
            "tool_count": len(tools),
            "fingerprint": catalog_payload()["fingerprint"],
            "schema_version": catalog_payload()["schema_version"],
            "tools": tools,
        },
        transport="cli",
    )
    _print_json(payload)
    return EXIT_OK


def _cmd_tools_search(args: argparse.Namespace) -> int:
    query = str(getattr(args, "query", "") or "").strip().lower()
    if not query:
        _print_json(
            canonical_error(
                result_kind="rdc_tool.tools.search",
                code="query_required",
                category="validation",
                message="tools search requires a query",
                transport="cli",
            ),
        )
        return EXIT_RUNTIME_ERR
    results = []
    for tool in (_tool_summary(item) for item in load_tool_catalog()):
        haystack = " ".join(
            str(tool.get(key) or "")
            for key in ("name", "namespace", "group", "description")
        ).lower()
        if query in haystack:
            results.append(tool)
    limit = int(getattr(args, "limit", 20) or 20)
    if limit > 0:
        results = results[:limit]
    payload = canonical_success(
        result_kind="rdc_tool.tools.search",
        data={
            "query": query,
            "tool_count": len(results),
            "tools": results,
        },
        transport="cli",
    )
    _print_json(payload)
    return EXIT_OK


def _extract_error_triplet(payload: Dict[str, Any]) -> tuple[str, str, str]:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    return (
        str(error.get("code") or "runtime_error"),
        str(error.get("category") or "runtime"),
        str(error.get("message") or "runtime error"),
    )


def _safe_capture_open_context_snapshot(context: str) -> Dict[str, Any]:
    try:
        payload = _daemon_exec("rd.session.get_context", {}, context=context)
    except Exception as exc:  # noqa: BLE001
        nested = _exception_error_payload("rd.session.get_context", exc, transport="cli")
        return {"ok": False, "error": nested.get("error"), "meta": nested.get("meta", {})}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return {"ok": bool(payload.get("ok")), "data": data, "error": payload.get("error"), "meta": payload.get("meta", {})}


def _parse_context_value(raw: str) -> Any:
    text = str(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _cmd_context_status(args: argparse.Namespace) -> int:
    context = str(getattr(args, "daemon_context", "default") or "default")
    payload = _daemon_exec("rd.session.get_context", {}, context=context)
    _print_json(payload)
    return EXIT_OK if bool(payload.get("ok")) else EXIT_RUNTIME_ERR


def _cmd_context_update(args: argparse.Namespace) -> int:
    context = str(getattr(args, "daemon_context", "default") or "default")
    call_args = {"key": str(args.key), "value": _parse_context_value(str(args.value))}
    payload = _daemon_exec("rd.session.update_context", call_args, context=context)
    _print_json(payload)
    return EXIT_OK if bool(payload.get("ok")) else EXIT_RUNTIME_ERR


def _cmd_context_list(args: argparse.Namespace) -> int:
    context = str(getattr(args, "daemon_context", "default") or "default")
    payload = _daemon_exec("rd.session.list_contexts", {}, context=context)
    _print_json(payload)
    return EXIT_OK if bool(payload.get("ok")) else EXIT_RUNTIME_ERR


def _session_required_error_payload(result_kind: str, context: str, message: str) -> Dict[str, Any]:
    return canonical_error(
        result_kind=result_kind,
        code="session_required",
        category="validation",
        message=message,
        details={
            "context_id": context,
            "requires_session": True,
            "recovery_hint": "Open a capture with `rdc-tool capture open --file <rdc>` or pass --session-id.",
        },
        transport="cli",
    )


def _capture_open_error_payload(
    *,
    step: str,
    context: str,
    file_path: str,
    capture_file_id: str = "",
    session_id: str = "",
    active_event_id: int = 0,
    source_payload: Optional[Dict[str, Any]] = None,
    source_exception: Optional[Exception] = None,
) -> Dict[str, Any]:
    if isinstance(source_payload, dict) and not bool(source_payload.get("ok")):
        code, category, message = _extract_error_triplet(source_payload)
        source_details = dict((source_payload.get("error") or {}).get("details") or {})
    elif source_exception is not None:
        nested = _exception_error_payload("rdc_tool.capture.open", source_exception, transport="cli")
        code, category, message = _extract_error_triplet(nested)
        source_details = dict((nested.get("error") or {}).get("details") or {})
    else:
        code, category, message = ("runtime_error", "runtime", f"{step} failed")
        source_details = {}
    try:
        daemon_status = _daemon_status_payload(context)
    except Exception as exc:  # noqa: BLE001
        daemon_status = _exception_error_payload("rdc_tool.daemon.status", exc, transport="cli")
    daemon_state = daemon_status.get("data", {}).get("state", {}) if isinstance(daemon_status.get("data"), dict) else {}
    context_snapshot = _safe_capture_open_context_snapshot(context)
    details = {
        "failed_step": step,
        "context_id": context,
        "file_path": file_path,
        "capture_file_id": str(capture_file_id or ""),
        "session_id": str(session_id or ""),
        "active_event_id": int(active_event_id or 0),
        "step_payload": source_payload if isinstance(source_payload, dict) else {},
        "source_error_details": source_details,
        "daemon_state": daemon_state if isinstance(daemon_state, dict) else {},
        "context_snapshot": context_snapshot,
        "recovery_hint": "Inspect failed_step; if the context still reports an active operation or stale handles, run `rdc-tool context clear` before retrying.",
    }
    return canonical_error(
        result_kind="rdc_tool.capture.open",
        code=code,
        category=category,
        message=f"capture open failed during {step}: {message}",
        details=details,
        transport="cli",
    )


def _execution_options(args: argparse.Namespace, result_kind: str) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """The request's execution options from --no-progress-ms/--request-id/--progress-stream, or a validation error."""
    try:
        no_progress_ms = timeout_policy.validate_no_progress_ms(getattr(args, "no_progress_ms", None))
    except timeout_policy.NoProgressBudgetError as exc:
        return None, canonical_error(result_kind=result_kind, code=exc.code, category=exc.category, message=str(exc),
                                     details=exc.details, transport="cli")
    options: Dict[str, Any] = {"no_progress_ms": no_progress_ms,
                               "on_frame": _write_progress_frame if getattr(args, "progress_stream", False) else None}
    request_id = getattr(args, "request_id", None)
    if request_id is not None:
        if not _REQUEST_ID_RE.fullmatch(str(request_id)):
            return None, canonical_error(result_kind=result_kind, code="invalid_request_id", category="validation",
                                         message="--request-id must be 1-128 characters of [A-Za-z0-9._:-]",
                                         details={"request_id": request_id}, transport="cli")
        options["request_id"] = str(request_id)
    return options, None


async def _cmd_call(args: argparse.Namespace) -> int:
    try:
        definition = describe_operation(args.operation)
    except ValueError as exc:
        _print_json(canonical_error(result_kind=args.operation, code="operation_not_found",
                                    category="not_found", message=str(exc), transport="cli"))
        return EXIT_RUNTIME_ERR
    options, invalid = _execution_options(args, args.operation)
    if invalid is not None:
        _print_json(invalid)
        return EXIT_RUNTIME_ERR
    if str(args.format) == "tsv" and definition and "projection" not in definition["input_schema"]["properties"]:
        _print_json(_tabular_projection_error_payload({"result_kind": args.operation}, "tool does not support a tabular projection"))
        return EXIT_RUNTIME_ERR
    call_args = _tabular_request(
        str(args.format),
        _load_call_args(
            args_json=getattr(args, "args_json", None),
            args_file=getattr(args, "args_file", None),
        ),
    )
    payload = _daemon_exec(args.operation, call_args, remote=bool(args.remote), context=str(args.daemon_context), **options)
    return EXIT_OK if _render_result(payload, output_format=str(args.format)) else EXIT_RUNTIME_ERR


async def _cmd_vfs(args: argparse.Namespace) -> int:
    if str(args.format) == "tsv" and args.vfs_cmd != "ls":
        _print_json(_facade_projection_not_supported_payload(args, str(args.daemon_context)))
        return EXIT_RUNTIME_ERR
    op = f"rd.vfs.{args.vfs_cmd}"
    call_args: Dict[str, Any] = {"path": str(args.path or "/")}
    if getattr(args, "session_id", None):
        call_args["session_id"] = str(args.session_id)
    if args.vfs_cmd == "tree":
        call_args["depth"] = int(args.depth)
        call_args["max_nodes"] = int(args.max_nodes)
    payload = _daemon_exec(op, _tabular_request(str(args.format), call_args), context=str(args.daemon_context))
    return EXIT_OK if _render_result(payload, output_format=str(args.format)) else EXIT_RUNTIME_ERR


_FACADE_TSV_COMMANDS = {("event", "list"), ("resource", "list")}


def _facade_subcommand(args: argparse.Namespace) -> str:
    for attr in (
        "event_cmd",
        "pipeline_cmd",
        "shader_cmd",
        "export_cmd",
        "pixel_cmd",
        "resource_cmd",
    ):
        value = getattr(args, attr, None)
        if value:
            return str(value)
    return ""


def _facade_result_kind(args: argparse.Namespace) -> str:
    subcommand = _facade_subcommand(args)
    return f"rdc_tool.{args.command}.{subcommand}" if subcommand else f"rdc_tool.{args.command}"


def _facade_projection_not_supported_payload(args: argparse.Namespace, context: str) -> Dict[str, Any]:
    return canonical_error(
        result_kind=_facade_result_kind(args),
        code="projection_not_supported",
        category="validation",
        message="--format tsv is only supported by facade list/projection commands.",
        details={
            "context_id": context,
            "requested_format": "tsv",
            "command": str(args.command),
            "subcommand": _facade_subcommand(args),
            "supported_tsv_commands": ["event list", "resource list", "vfs ls", "call with a tabular tool projection"],
            "recovery_hint": "Use --format json for nested pipeline, shader, export, pixel, and resource-detail payloads.",
        },
        transport="cli",
    )


def _facade_session_id(args: argparse.Namespace, context: str) -> str:
    return _default_session_id(getattr(args, "session_id", None), context=context)


def _add_optional_event_id(target: Dict[str, Any], value: Any) -> None:
    if value is not None:
        target["event_id"] = int(value)


def _facade_request(args: argparse.Namespace, session_id: str) -> tuple[str, Dict[str, Any]]:
    command = str(args.command)
    subcommand = _facade_subcommand(args)

    if command == "event":
        if subcommand == "list":
            return "rd.event.get_action_tree", {"session_id": session_id}
        if subcommand == "show":
            return "rd.event.get_action_details", {"session_id": session_id, "event_id": int(args.event_id)}

    if command == "pipeline":
        call_args: Dict[str, Any] = {"session_id": session_id}
        _add_optional_event_id(call_args, getattr(args, "event_id", None))
        if subcommand == "show":
            call_args["context_id"] = str(args.daemon_context)
            call_args["detail"] = "summary"
            return "rd.pipeline.get_state", call_args
        if subcommand == "section":
            call_args["stage"] = str(args.stage)
            return "rd.pipeline.get_stage_state", call_args

    if command == "shader":
        call_args = {"session_id": session_id, "stage": str(args.stage)}
        _add_optional_event_id(call_args, getattr(args, "event_id", None))
        if subcommand == "source":
            return "rd.shader.get_source", call_args
        if subcommand == "disasm":
            return "rd.shader.get_disassembly", call_args
        if subcommand == "constants":
            call_args["slot"] = int(args.slot)
            return "rd.shader.get_constant_buffer_contents", call_args

    if command == "export":
        call_args = {"session_id": session_id, "output_path": str(Path(args.out).resolve())}
        _add_optional_event_id(call_args, getattr(args, "event_id", None))
        if subcommand == "screenshot":
            return "rd.export.screenshot", call_args
        if subcommand == "texture":
            call_args["texture_id"] = str(args.resource_id)
            return "rd.export.texture", call_args
        if subcommand == "buffer":
            call_args["buffer_id"] = str(args.resource_id)
            return "rd.export.buffer", call_args
        if subcommand == "mesh":
            return "rd.export.mesh", call_args

    if command == "pixel":
        call_args = {
            "session_id": session_id,
            "texture_id": str(args.resource_id),
            "x": int(args.x),
            "y": int(args.y),
        }
        _add_optional_event_id(call_args, getattr(args, "event_id", None))
        if subcommand == "value":
            return "rd.texture.get_pixel_value", call_args
        if subcommand == "history":
            return "rd.texture.get_pixel_history", call_args

    if command == "resource":
        if subcommand == "list":
            return "rd.resource.list_all", {"session_id": session_id}
        call_args = {"session_id": session_id, "resource_id": str(args.resource_id)}
        if subcommand == "show":
            return "rd.resource.get_details", call_args
        if subcommand == "usage":
            return "rd.resource.get_usage", call_args

    raise RuntimeError(f"unsupported facade command: {command} {subcommand}".strip())


async def _cmd_facade(args: argparse.Namespace) -> int:
    context = str(args.daemon_context)
    output_format = str(getattr(args, "format", "json") or "json")
    try:
        session_id = _facade_session_id(args, context)
    except RuntimeError as exc:
        _print_json(_session_required_error_payload(_facade_result_kind(args), context, str(exc)))
        return EXIT_RUNTIME_ERR

    op, call_args = _facade_request(args, session_id)
    if output_format == "tsv" and (str(args.command), _facade_subcommand(args)) not in _FACADE_TSV_COMMANDS:
        _print_json(_facade_projection_not_supported_payload(args, context))
        return EXIT_RUNTIME_ERR

    payload = _daemon_exec(op, _tabular_request(output_format, call_args), context=context)
    return EXIT_OK if _render_result(payload, output_format=output_format) else EXIT_RUNTIME_ERR


async def _cmd_capture_open(args: argparse.Namespace) -> int:
    file_path = str(Path(args.file).resolve())
    context = str(args.daemon_context)
    remote_id = str(getattr(args, "remote_id", "") or "").strip()
    capture_file_id = ""
    session_id = ""
    active_event_id = 0

    def _print_capture_open_error(
        step: str,
        *,
        source_payload: Optional[Dict[str, Any]] = None,
        source_exception: Optional[Exception] = None,
    ) -> int:
        _print_json(
            _capture_open_error_payload(
                step=step,
                context=context,
                file_path=file_path,
                capture_file_id=capture_file_id,
                session_id=session_id,
                active_event_id=active_event_id,
                source_payload=source_payload,
                source_exception=source_exception,
            )
        )
        return EXIT_RUNTIME_ERR

    try:
        init_payload = _daemon_exec(
            "rd.core.init",
            {
                "global_env": {"artifact_dir": str(Path(args.artifact_dir).resolve())},
                "enable_remote": True,
            },
            context=context,
        )
    except Exception as exc:  # noqa: BLE001
        return _print_capture_open_error("init", source_exception=exc)
    if not bool(init_payload.get("ok")):
        return _print_capture_open_error("init", source_payload=init_payload)

    try:
        open_file = _daemon_exec("rd.capture.open_file", {"file_path": file_path, "read_only": True}, context=context)
    except Exception as exc:  # noqa: BLE001
        return _print_capture_open_error("open_file", source_exception=exc)
    if not bool(open_file.get("ok")):
        return _print_capture_open_error("open_file", source_payload=open_file)
    capture_file_id = str(_extract(open_file, "capture_file_id") or "")

    open_replay_options: Dict[str, Any] = {}
    if remote_id:
        # Explicit remote handle — never silent-fallback to local OpenCapture.
        open_replay_options["remote_id"] = remote_id

    try:
        open_replay = _daemon_exec(
            "rd.capture.open_replay",
            {"capture_file_id": capture_file_id, "options": open_replay_options},
            context=context,
        )
    except Exception as exc:  # noqa: BLE001
        return _print_capture_open_error("open_replay", source_exception=exc)
    if not bool(open_replay.get("ok")):
        return _print_capture_open_error("open_replay", source_payload=open_replay)
    session_id = str(_extract(open_replay, "session_id") or "")
    active_event_id = int(_extract(open_replay, "active_event_id", 0) or 0)

    try:
        set_frame = _daemon_exec(
            "rd.replay.set_frame",
            {"session_id": session_id, "frame_index": int(args.frame_index)},
            context=context,
        )
    except Exception as exc:  # noqa: BLE001
        return _print_capture_open_error("set_frame", source_exception=exc)
    if not bool(set_frame.get("ok")):
        return _print_capture_open_error("set_frame", source_payload=set_frame)
    active_event_id = int(_extract(set_frame, "active_event_id", active_event_id) or active_event_id or 0)

    try:
        context_payload = _daemon_exec("rd.session.get_context", {}, context=context)
    except Exception as exc:  # noqa: BLE001
        return _print_capture_open_error("get_context", source_exception=exc)
    if not bool(context_payload.get("ok")):
        return _print_capture_open_error("get_context", source_payload=context_payload)
    if bool(getattr(args, "preview", False)):
        try:
            preview_payload = _daemon_exec("rd.session.open_preview", {}, context=context)
        except Exception as exc:  # noqa: BLE001
            return _print_capture_open_error("open_preview", source_exception=exc)
        if not bool(preview_payload.get("ok")):
            return _print_capture_open_error("open_preview", source_payload=preview_payload)
        try:
            context_payload = _daemon_exec("rd.session.get_context", {}, context=context)
        except Exception as exc:  # noqa: BLE001
            return _print_capture_open_error("get_context_after_preview", source_exception=exc)
        if not bool(context_payload.get("ok")):
            return _print_capture_open_error("get_context_after_preview", source_payload=context_payload)
    runtime_snapshot = context_payload.get("data", {}).get("runtime", {}) if isinstance(context_payload.get("data"), dict) else {}
    context_data = context_payload.get("data") if isinstance(context_payload.get("data"), dict) else {}
    recovery_status = str(_extract(open_replay, "recovery_status", "") or "")
    if not recovery_status and isinstance(runtime_snapshot, dict):
        recovery_status = str(runtime_snapshot.get("recovery_status") or "")
    if not recovery_status and isinstance(context_data, dict):
        current_session_id = str(context_data.get("current_session_id") or session_id)
        for item in context_data.get("sessions", []) or []:
            if isinstance(item, dict) and str(item.get("session_id") or "") == current_session_id:
                recovery = item.get("recovery")
                if isinstance(recovery, dict):
                    recovery_status = str(recovery.get("status") or "")
                break
    payload = canonical_success(
        result_kind="rdc_tool.capture.open",
        data={
            "context_id": context,
            "capture_file_id": capture_file_id,
            "capture_path": file_path,
            "session_id": session_id,
            "active_event_id": active_event_id,
            "recovery_status": recovery_status or "ready",
            "backend": "remote" if remote_id else "local",
            "remote_id": remote_id or None,
            "runtime": runtime_snapshot if isinstance(runtime_snapshot, dict) else {},
            "context": context_data,
        },
        transport="cli",
    )
    _print_json(payload)
    return EXIT_OK


def _cmd_capture_status(args: argparse.Namespace) -> int:
    context = str(args.daemon_context)
    state = _ensure_daemon_state(context)
    daemon_state_resp = daemon_request("get_state", params={}, context=context, state=state)
    daemon_state = daemon_state_resp.get("result", {}).get("state", {}) if isinstance(daemon_state_resp, dict) else {}
    snapshot_payload = _daemon_exec("rd.session.get_context", {}, context=context)
    snapshot = snapshot_payload.get("data") if isinstance(snapshot_payload.get("data"), dict) else {}
    runtime_payload = snapshot.get("runtime", {}) if isinstance(snapshot, dict) else {}
    has_session = bool(str(runtime_payload.get("session_id") or "").strip()) if isinstance(runtime_payload, dict) else False
    payload = canonical_success(
        result_kind="rdc_tool.capture.status",
        data={
            "context_id": context,
            "has_session": has_session,
            "state": daemon_state if isinstance(daemon_state, dict) else {},
            "context": snapshot if isinstance(snapshot, dict) else {},
        },
        transport="cli",
    )
    _print_json(payload)
    return EXIT_OK


async def _cmd_session_preview(args: argparse.Namespace) -> int:
    context = str(args.daemon_context)
    if args.session_preview_cmd == "on":
        call_args: Dict[str, Any] = {}
        if getattr(args, "session_id", None):
            call_args["session_id"] = str(args.session_id)
        payload = _daemon_exec("rd.session.open_preview", call_args, context=context)
        _print_json(payload)
        return EXIT_OK if bool(payload.get("ok")) else EXIT_RUNTIME_ERR
    if args.session_preview_cmd == "off":
        payload = _daemon_exec("rd.session.close_preview", {}, context=context)
        _print_json(payload)
        return EXIT_OK if bool(payload.get("ok")) else EXIT_RUNTIME_ERR
    if args.session_preview_cmd == "status":
        status_payload = _daemon_status_payload(context)
        status_data = status_payload.get("data") if isinstance(status_payload.get("data"), dict) else {}
        if not bool(status_data.get("running")):
            result = canonical_success(
                result_kind="rdc_tool.session.preview.status",
                data={
                    "context_id": context,
                    "running": False,
                    "has_session": False,
                    "current_session_id": "",
                    "preview": {"enabled": False, "available": False},
                    "runtime": {},
                    "daemon": status_data,
                },
                transport="cli",
            )
            _print_json(result)
            return EXIT_OK
        try:
            payload = _daemon_exec("rd.session.get_context", {}, context=context)
        except Exception as exc:  # noqa: BLE001
            _print_json(
                canonical_error(
                    result_kind="rdc_tool.session.preview.status",
                    code=str(getattr(exc, "code", "") or "preview_status_failed"),
                    category=str(getattr(exc, "category", "") or "runtime"),
                    message=f"preview status failed: {exc}",
                    details={"context_id": context, "daemon": status_data},
                    transport="cli",
                ),
            )
            return EXIT_RUNTIME_ERR
        if not bool(payload.get("ok")):
            _print_json(
                canonical_error(
                    result_kind="rdc_tool.session.preview.status",
                    code=str((payload.get("error") or {}).get("code") or "preview_status_failed"),
                    category=str((payload.get("error") or {}).get("category") or "runtime"),
                    message=str((payload.get("error") or {}).get("message") or "preview status failed"),
                    details={"context_id": context, "source": payload},
                    transport="cli",
                ),
            )
            return EXIT_RUNTIME_ERR
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
        result = canonical_success(
            result_kind="rdc_tool.session.preview.status",
            data={
                "context_id": str(data.get("context_id") or context),
                "current_session_id": str(data.get("current_session_id") or ""),
                "preview": dict(data.get("preview") or {}),
                "runtime": dict(runtime),
                "running": True,
                "has_session": bool(str(runtime.get("session_id") or data.get("current_session_id") or "").strip()),
            },
            transport="cli",
        )
        _print_json(result)
        return EXIT_OK
    raise RuntimeError("unsupported session preview command")


async def _cmd_diff_pipeline(args: argparse.Namespace) -> int:
    context = str(args.daemon_context)
    try:
        session_id = _default_session_id(args.session_id, context=context)
    except RuntimeError as exc:
        _print_json(_session_required_error_payload("rdc_tool.diff.pipeline", context, str(exc)))
        return EXIT_RUNTIME_ERR
    payload = _daemon_exec(
        "rd.event.diff_pipeline_state",
        {"session_id": session_id, "event_a": int(args.event_a), "event_b": int(args.event_b)},
        context=context,
    )
    _print_json(payload)
    if not bool(payload.get("ok")):
        return EXIT_RUNTIME_ERR
    changes = _extract(payload, "diff", [])
    has_diff = isinstance(changes, list) and len(changes) > 0
    if args.fail_on_diff and has_diff:
        return EXIT_ASSERT_FAIL
    return EXIT_OK


async def _cmd_diff_image(args: argparse.Namespace) -> int:
    diff_args = {
        "image_a_path": str(Path(args.image_a).resolve()),
        "image_b_path": str(Path(args.image_b).resolve()),
        "output_path": str(Path(args.out).resolve()) if args.out else None,
    }
    payload = _daemon_exec("rd.util.diff_images", diff_args, context=str(args.daemon_context))
    _print_json(payload)
    if not bool(payload.get("ok")):
        return EXIT_RUNTIME_ERR
    if args.threshold is None:
        return EXIT_OK
    metrics = _extract(payload, "metrics", {})
    mse = float(metrics.get("mse", 0.0)) if isinstance(metrics, dict) else 0.0
    return EXIT_OK if mse <= float(args.threshold) else EXIT_ASSERT_FAIL


async def _cmd_assert_pipeline(args: argparse.Namespace) -> int:
    context = str(args.daemon_context)
    try:
        session_id = _default_session_id(args.session_id, context=context)
    except RuntimeError as exc:
        _print_json(_session_required_error_payload("rdc_tool.assert.pipeline", context, str(exc)))
        return EXIT_RUNTIME_ERR
    payload = _daemon_exec(
        "rd.event.diff_pipeline_state",
        {"session_id": session_id, "event_a": int(args.event_a), "event_b": int(args.event_b)},
        context=context,
    )
    if not bool(payload.get("ok")):
        _print_json(
            canonical_error(
                result_kind="rdc_tool.assert.pipeline",
                code="runtime_error",
                category="runtime",
                message=str((payload.get("error") or {}).get("message") or "pipeline diff failed"),
                details={"source": payload},
                transport="cli",
            ),
        )
        return EXIT_RUNTIME_ERR
    outcome = AssertService.assert_pipeline_diff(payload, max_changes=int(args.max_changes))
    result = canonical_success(
        result_kind="rdc_tool.assert.pipeline",
        data={"pass": outcome.passed, "reason": outcome.reason, "details": outcome.details},
        transport="cli",
    )
    _print_json(result)
    return EXIT_OK if outcome.passed else EXIT_ASSERT_FAIL


async def _cmd_assert_image(args: argparse.Namespace) -> int:
    diff_args = {
        "image_a_path": str(Path(args.image_a).resolve()),
        "image_b_path": str(Path(args.image_b).resolve()),
        "output_path": str(Path(args.out).resolve()) if args.out else None,
    }
    payload = _daemon_exec("rd.util.diff_images", diff_args, context=str(args.daemon_context))
    if not bool(payload.get("ok")):
        _print_json(
            canonical_error(
                result_kind="rdc_tool.assert.image",
                code="runtime_error",
                category="runtime",
                message=str((payload.get("error") or {}).get("message") or "image diff failed"),
                details={"source": payload},
                transport="cli",
            ),
        )
        return EXIT_RUNTIME_ERR
    outcome = AssertService.assert_image_metrics(
        payload,
        mse_max=float(args.mse_max) if args.mse_max is not None else None,
        max_abs_max=float(args.max_abs_max) if args.max_abs_max is not None else None,
        psnr_min=float(args.psnr_min) if args.psnr_min is not None else None,
    )
    result = canonical_success(
        result_kind="rdc_tool.assert.image",
        data={"pass": outcome.passed, "reason": outcome.reason, "details": outcome.details},
        transport="cli",
    )
    _print_json(result)
    return EXIT_OK if outcome.passed else EXIT_ASSERT_FAIL


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rdc-tool", description="RDC-Tool daemon-backed CLI")
    parser.add_argument("--version", action="version", version=f"rdc-tool {TOOL_VERSION}")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument("--daemon-context", default="default", help="Daemon state namespace (default: default)")
    parser.add_argument("--owner-pid", type=int, default=None, help="Host process PID used for daemon auto-stop")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_session_arg(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--session-id", default=None)

    def add_format_arg(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--format", choices=("json", "tsv"), default="json")

    def add_event_arg(command_parser: argparse.ArgumentParser, *, required: bool = False) -> None:
        command_parser.add_argument("--event-id", type=int, required=required, default=None)

    p_version = sub.add_parser("version", help="Print version and public contract metadata")
    p_version.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    p_doctor = sub.add_parser("doctor", help="Validate CLI runtime setup")
    p_doctor.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p_tools = sub.add_parser("tools", help="Catalog discovery")
    s_tools = p_tools.add_subparsers(dest="tools_cmd", required=True)
    p_tools_list = s_tools.add_parser("list", help="List catalog-defined rd.* tools")
    p_tools_list.add_argument("--full", action="store_true", help="Include schemas and execution contracts")
    p_tools_list.add_argument("--namespace", default="", help="Filter by rd.* namespace, such as capture or pipeline")
    p_tools_list.add_argument("--limit", type=int, default=0, help="Maximum tools to return; 0 means no limit")
    p_tools_list.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    p_tools_describe = s_tools.add_parser("describe", help="Describe a canonical operation")
    p_tools_describe.add_argument("operation")
    p_tools_describe.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    p_tools_search = s_tools.add_parser("search", help="Search catalog-defined rd.* tools")
    p_tools_search.add_argument("query")
    p_tools_search.add_argument("--limit", type=int, default=20)
    p_tools_search.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p_daemon = sub.add_parser("daemon", help="Daemon lifecycle")
    s_daemon = p_daemon.add_subparsers(dest="daemon_cmd", required=True)
    s_daemon.add_parser("start")
    s_daemon.add_parser("stop")
    s_daemon.add_parser("status")
    p_daemon_attach = s_daemon.add_parser("attach", help=argparse.SUPPRESS)
    p_daemon_attach.add_argument("--client-id", required=True)
    p_daemon_attach.add_argument("--client-type", default="cli")
    p_daemon_attach.add_argument("--pid", type=int, default=0)
    p_daemon_attach.add_argument("--lease-timeout-seconds", type=int, default=120)
    p_daemon_heartbeat = s_daemon.add_parser("heartbeat", help=argparse.SUPPRESS)
    p_daemon_heartbeat.add_argument("--client-id", required=True)
    p_daemon_heartbeat.add_argument("--pid", type=int, default=0)
    p_daemon_detach = s_daemon.add_parser("detach", help=argparse.SUPPRESS)
    p_daemon_detach.add_argument("--client-id", required=True)
    s_daemon.add_parser("cleanup", help=argparse.SUPPRESS)

    p_context = sub.add_parser("context", help="Context state helpers")
    s_context = p_context.add_subparsers(dest="context_cmd", required=True)
    p_context_status = s_context.add_parser("status", help="Print the current runtime context snapshot")
    p_context_status.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    p_context_update = s_context.add_parser("update", help="Update agent-facing context fields")
    p_context_update.add_argument("--key", required=True, choices=("notes", "focus_pixel", "focus_resource_id", "focus_shader_id"))
    p_context_update.add_argument("--value", required=True)
    p_context_update.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    p_context_list = s_context.add_parser("list", help="List known daemon contexts")
    p_context_list.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    p_context_clear = s_context.add_parser("clear")
    p_context_clear.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p_call = sub.add_parser("call", help="Call any rd.* operation")
    p_call.add_argument("operation")
    p_call_args = p_call.add_mutually_exclusive_group()
    p_call_args.add_argument("--args-json", default=None)
    p_call_args.add_argument("--args-file", default=None)
    p_call.add_argument("--format", choices=("json", "tsv"), default="json")
    p_call.add_argument("--remote", action="store_true")
    p_call.add_argument("--request-id", default=None,
                        help="Caller-chosen request identity for progress frames and `daemon cancel`")

    def add_execution_budget_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--no-progress-ms", type=int, default=None,
            help=(f"Treat the operation as stuck after this many milliseconds without progress "
                  f"({timeout_policy.MIN_NO_PROGRESS_MS}-{timeout_policy.MAX_NO_PROGRESS_MS}, "
                  f"default {timeout_policy.DEFAULT_NO_PROGRESS_MS})"))
        command_parser.add_argument("--progress-stream", action="store_true",
                                    help="Write progress, native-call and heartbeat frames to stderr as NDJSON")

    add_execution_budget_args(p_call)

    p_batch = sub.add_parser("batch", help="Execute a JSONL list of read-only operations; stop at first failure")
    p_batch.add_argument("source")
    p_batch.add_argument("--remote", action="store_true")
    add_execution_budget_args(p_batch)

    p_capture = sub.add_parser("capture", help="Capture session helpers")
    s_capture = p_capture.add_subparsers(dest="capture_cmd", required=True)
    p_capture_open = s_capture.add_parser("open")
    p_capture_open.add_argument("--file", required=True)
    p_capture_open.add_argument("--frame-index", type=int, default=0)
    p_capture_open.add_argument("--artifact-dir", default=str(artifacts_dir().resolve()))
    p_capture_open.add_argument(
        "--remote-id",
        default=None,
        help="Live remote handle from rd.remote.connect; when set, open_replay must use that remote backend (no local fallback).",
    )
    p_capture_open.add_argument("--preview", action="store_true")
    s_capture.add_parser("status")

    p_session = sub.add_parser("session", help="Session helpers")
    s_session = p_session.add_subparsers(dest="session_cmd", required=True)
    p_session_preview = s_session.add_parser("preview", help="Human preview controls")
    s_session_preview = p_session_preview.add_subparsers(dest="session_preview_cmd", required=True)
    p_session_preview_on = s_session_preview.add_parser("on")
    p_session_preview_on.add_argument("--session-id", default=None)
    s_session_preview.add_parser("off")
    s_session_preview.add_parser("status")

    p_completion = sub.add_parser("completion", help="Generate shell completion script")
    p_completion.add_argument("shell", choices=("powershell", "bash", "zsh", "fish"))

    p_vfs = sub.add_parser("vfs", help="Read-only VFS navigation helpers")
    s_vfs = p_vfs.add_subparsers(dest="vfs_cmd", required=True)
    for name in ("ls", "cat", "resolve"):
        p_vfs_cmd = s_vfs.add_parser(name)
        p_vfs_cmd.add_argument("--path", default="/")
        p_vfs_cmd.add_argument("--session-id", default=None)
        p_vfs_cmd.add_argument("--format", choices=("json", "tsv"), default="json")
    p_vfs_tree = s_vfs.add_parser("tree")
    p_vfs_tree.add_argument("--path", default="/")
    p_vfs_tree.add_argument("--session-id", default=None)
    p_vfs_tree.add_argument("--depth", type=int, default=2)
    p_vfs_tree.add_argument("--max-nodes", type=int, default=2000)
    p_vfs_tree.add_argument("--format", choices=("json", "tsv"), default="json")

    p_event = sub.add_parser("event", help="Event navigation facade")
    s_event = p_event.add_subparsers(dest="event_cmd", required=True)
    p_event_list = s_event.add_parser("list", help="List event actions")
    add_session_arg(p_event_list)
    add_format_arg(p_event_list)
    p_event_show = s_event.add_parser("show", help="Show event action details")
    add_session_arg(p_event_show)
    add_format_arg(p_event_show)
    add_event_arg(p_event_show, required=True)

    p_pipeline = sub.add_parser("pipeline", help="Pipeline inspection facade")
    s_pipeline = p_pipeline.add_subparsers(dest="pipeline_cmd", required=True)
    p_pipeline_show = s_pipeline.add_parser("show", help="Show pipeline summary")
    add_session_arg(p_pipeline_show)
    add_format_arg(p_pipeline_show)
    add_event_arg(p_pipeline_show)
    p_pipeline_section = s_pipeline.add_parser("section", help="Show one shader-stage pipeline section")
    add_session_arg(p_pipeline_section)
    add_format_arg(p_pipeline_section)
    add_event_arg(p_pipeline_section)
    p_pipeline_section.add_argument("--stage", required=True)

    p_shader = sub.add_parser("shader", help="Shader inspection facade")
    s_shader = p_shader.add_subparsers(dest="shader_cmd", required=True)
    for shader_cmd, help_text in (
        ("source", "Show shader source or source fallback"),
        ("disasm", "Show shader disassembly"),
    ):
        p_shader_cmd = s_shader.add_parser(shader_cmd, help=help_text)
        add_session_arg(p_shader_cmd)
        add_format_arg(p_shader_cmd)
        add_event_arg(p_shader_cmd)
        p_shader_cmd.add_argument("--stage", required=True)
    p_shader_constants = s_shader.add_parser("constants", help="Show shader constant-buffer contents")
    add_session_arg(p_shader_constants)
    add_format_arg(p_shader_constants)
    add_event_arg(p_shader_constants)
    p_shader_constants.add_argument("--stage", required=True)
    p_shader_constants.add_argument("--slot", required=True, type=int)

    p_export = sub.add_parser("export", help="Export facade")
    s_export = p_export.add_subparsers(dest="export_cmd", required=True)
    p_export_screenshot = s_export.add_parser("screenshot", help="Export event output screenshot")
    add_session_arg(p_export_screenshot)
    add_format_arg(p_export_screenshot)
    add_event_arg(p_export_screenshot)
    p_export_screenshot.add_argument("--out", required=True)
    for export_cmd, help_text in (("texture", "Export a texture resource"), ("buffer", "Export a buffer resource")):
        p_export_cmd = s_export.add_parser(export_cmd, help=help_text)
        add_session_arg(p_export_cmd)
        add_format_arg(p_export_cmd)
        p_export_cmd.add_argument("--resource-id", required=True)
        p_export_cmd.add_argument("--out", required=True)
    p_export_mesh = s_export.add_parser("mesh", help="Export event mesh")
    add_session_arg(p_export_mesh)
    add_format_arg(p_export_mesh)
    add_event_arg(p_export_mesh)
    p_export_mesh.add_argument("--out", required=True)

    p_pixel = sub.add_parser("pixel", help="Pixel inspection facade")
    s_pixel = p_pixel.add_subparsers(dest="pixel_cmd", required=True)
    for pixel_cmd, help_text in (("value", "Read one pixel value"), ("history", "Show one pixel history")):
        p_pixel_cmd = s_pixel.add_parser(pixel_cmd, help=help_text)
        add_session_arg(p_pixel_cmd)
        add_format_arg(p_pixel_cmd)
        add_event_arg(p_pixel_cmd)
        p_pixel_cmd.add_argument("--resource-id", required=True)
        p_pixel_cmd.add_argument("--x", required=True, type=int)
        p_pixel_cmd.add_argument("--y", required=True, type=int)

    p_resource = sub.add_parser("resource", help="Resource inspection facade")
    s_resource = p_resource.add_subparsers(dest="resource_cmd", required=True)
    p_resource_list = s_resource.add_parser("list", help="List capture resources")
    add_session_arg(p_resource_list)
    add_format_arg(p_resource_list)
    for resource_cmd, help_text in (("show", "Show resource details"), ("usage", "Show resource usage")):
        p_resource_cmd = s_resource.add_parser(resource_cmd, help=help_text)
        add_session_arg(p_resource_cmd)
        add_format_arg(p_resource_cmd)
        p_resource_cmd.add_argument("--resource-id", required=True)

    p_diff = sub.add_parser("diff", help="Diff commands")
    s_diff = p_diff.add_subparsers(dest="diff_cmd", required=True)
    p_diff_pipeline = s_diff.add_parser("pipeline")
    p_diff_pipeline.add_argument("--session-id", default=None)
    p_diff_pipeline.add_argument("--event-a", required=True, type=int)
    p_diff_pipeline.add_argument("--event-b", required=True, type=int)
    p_diff_pipeline.add_argument("--fail-on-diff", action="store_true", help="Return exit code 1 if any diff exists")
    p_diff_image = s_diff.add_parser("image")
    p_diff_image.add_argument("--image-a", required=True)
    p_diff_image.add_argument("--image-b", required=True)
    p_diff_image.add_argument("--out", default=None)
    p_diff_image.add_argument("--threshold", type=float, default=None)

    p_assert = sub.add_parser("assert", help="Assertion commands")
    s_assert = p_assert.add_subparsers(dest="assert_cmd", required=True)
    p_assert_pipeline = s_assert.add_parser("pipeline")
    p_assert_pipeline.add_argument("--session-id", default=None)
    p_assert_pipeline.add_argument("--event-a", required=True, type=int)
    p_assert_pipeline.add_argument("--event-b", required=True, type=int)
    p_assert_pipeline.add_argument("--max-changes", type=int, default=0)
    p_assert_image = s_assert.add_parser("image")
    p_assert_image.add_argument("--image-a", required=True)
    p_assert_image.add_argument("--image-b", required=True)
    p_assert_image.add_argument("--out", default=None)
    p_assert_image.add_argument("--mse-max", type=float, default=None)
    p_assert_image.add_argument("--max-abs-max", type=float, default=None)
    p_assert_image.add_argument("--psnr-min", type=float, default=None)

    return parser


async def _main_async(args: argparse.Namespace) -> int:
    global _cli_owner_pid
    _cli_owner_pid = args.owner_pid if getattr(args, "owner_pid", None) else None
    ctx = str(args.daemon_context)
    if args.command == "version":
        return _cmd_version(args)

    if args.command == "doctor":
        return _cmd_doctor(args)

    if args.command == "tools":
        if args.tools_cmd == "list":
            return _cmd_tools_list(args)
        if args.tools_cmd == "search":
            return _cmd_tools_search(args)
        if args.tools_cmd == "describe":
            try:
                data = describe_operation(args.operation)
            except ValueError as exc:
                _print_json(canonical_error(result_kind="rdc_tool.tools.describe", code="operation_not_found", category="not_found", message=str(exc), transport="cli"))
                return EXIT_RUNTIME_ERR
            _print_json(canonical_success(result_kind="rdc_tool.tools.describe", data=data, transport="cli"))
            return EXIT_OK

    if args.command == "daemon":
        if args.daemon_cmd == "start":
            ok, message, state = ensure_daemon(
                context=ctx,
                owner_pid=_cli_owner_pid,
            )
            owner_pid = int((state or {}).get("owner_pid") or _cli_owner_pid or 0)
            payload = canonical_success(result_kind="rdc_tool.daemon.start", data={"message": message, "state": public_view(state or {}), "context_id": ctx, "owner_pid": owner_pid}, transport="cli") if ok else canonical_error(result_kind="rdc_tool.daemon.start", code="runtime_error", category="runtime", message=message, transport="cli")
            _print_json(payload)
            return EXIT_OK if ok else EXIT_RUNTIME_ERR
        if args.daemon_cmd == "stop":
            ok, message = stop_daemon(context=ctx)
            payload = canonical_success(result_kind="rdc_tool.daemon.stop", data={"message": message, "context_id": ctx, "stopped": True}, transport="cli") if ok else canonical_error(result_kind="rdc_tool.daemon.stop", code="runtime_error", category="runtime", message=message, transport="cli")
            _print_json(payload)
            return EXIT_OK if ok else EXIT_RUNTIME_ERR
        if args.daemon_cmd == "status":
            payload = _daemon_status_payload(ctx)
            _print_json(payload)
            return EXIT_OK if bool(payload.get("ok")) else EXIT_RUNTIME_ERR
        if args.daemon_cmd == "attach":
            ok, message, state = attach_client(
                context=ctx,
                client_id=str(args.client_id),
                client_type=str(args.client_type),
                pid=int(args.pid or 0),
                lease_timeout_seconds=int(args.lease_timeout_seconds or 120),
                owner_pid=_cli_owner_pid,
            )
            _print_json(canonical_success(result_kind="rdc_tool.daemon.attach_client", data={"message": message, "state": public_view(state)}, transport="cli") if ok else canonical_error(result_kind="rdc_tool.daemon.attach_client", code="runtime_error", category="runtime", message=message, details={"state": public_view(state)}, transport="cli"))
            return EXIT_OK if ok else EXIT_RUNTIME_ERR
        if args.daemon_cmd == "heartbeat":
            ok, message, state = heartbeat_client(
                context=ctx,
                client_id=str(args.client_id),
                pid=int(args.pid or 0),
            )
            _print_json(canonical_success(result_kind="rdc_tool.daemon.heartbeat", data={"message": message, "state": public_view(state)}, transport="cli") if ok else canonical_error(result_kind="rdc_tool.daemon.heartbeat", code="runtime_error", category="runtime", message=message, details={"state": public_view(state)}, transport="cli"))
            return EXIT_OK if ok else EXIT_RUNTIME_ERR
        if args.daemon_cmd == "detach":
            ok, message, state = detach_client(
                context=ctx,
                client_id=str(args.client_id),
            )
            _print_json(canonical_success(result_kind="rdc_tool.daemon.detach_client", data={"message": message, "state": public_view(state)}, transport="cli") if ok else canonical_error(result_kind="rdc_tool.daemon.detach_client", code="runtime_error", category="runtime", message=message, details={"state": public_view(state)}, transport="cli"))
            return EXIT_OK if ok else EXIT_RUNTIME_ERR
        if args.daemon_cmd == "cleanup":
            cleaned = cleanup_stale_daemon_states()
            _print_json(canonical_success(result_kind="rdc_tool.daemon.cleanup", data={"cleaned": cleaned}, transport="cli"))
            return EXIT_OK

    if args.command == "context":
        if args.context_cmd == "status":
            return _cmd_context_status(args)
        if args.context_cmd == "update":
            return _cmd_context_update(args)
        if args.context_cmd == "list":
            return _cmd_context_list(args)
        if args.context_cmd == "clear":
            ok, message, details = clear_context(context=ctx)
            details = dict(details) if isinstance(details, dict) else {}
            if isinstance(details.get("state"), dict):
                details["state"] = public_view(details["state"])
            if not ok:
                _print_json(
                    canonical_error(
                        result_kind="rdc_tool.context.clear",
                        code="runtime_error",
                        category="runtime",
                        message=message,
                        details=details if isinstance(details, dict) else {},
                        transport="cli",
                    ),
                )
                return EXIT_RUNTIME_ERR
            _print_json(
                canonical_success(
                    result_kind="rdc_tool.context.clear",
                    data={"message": message, "cleared": details, "context_id": ctx},
                    transport="cli",
                ),
            )
            return EXIT_OK

    if args.command == "batch":
        from rdc_tool.cli_batch import run_batch
        options, invalid = _execution_options(args, "rdc_tool.batch")
        if invalid is not None:
            _print_json(invalid)
            return EXIT_RUNTIME_ERR
        return run_batch(args.source, lambda operation, arguments: _daemon_exec(
            operation, arguments, remote=bool(args.remote), context=ctx, **options))

    if args.command == "call":
        return await _cmd_call(args)

    if args.command == "vfs":
        return await _cmd_vfs(args)

    if args.command in {"event", "pipeline", "shader", "export", "pixel", "resource"}:
        return await _cmd_facade(args)

    if args.command == "capture":
        if args.capture_cmd == "open":
            return await _cmd_capture_open(args)
        if args.capture_cmd == "status":
            return _cmd_capture_status(args)

    if args.command == "session":
        if args.session_cmd == "preview":
            return await _cmd_session_preview(args)

    if args.command == "completion":
        return _cmd_completion(args)

    if args.command == "diff":
        if args.diff_cmd == "pipeline":
            return await _cmd_diff_pipeline(args)
        if args.diff_cmd == "image":
            return await _cmd_diff_image(args)

    if args.command == "assert":
        if args.assert_cmd == "pipeline":
            return await _cmd_assert_pipeline(args)
        if args.assert_cmd == "image":
            return await _cmd_assert_image(args)

    raise RuntimeError("unsupported command")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = _build_parser()
    args = parser.parse_args()
    logging.getLogger().setLevel(getattr(logging, os.environ.get("RDC_TOOL_LOG_LEVEL", "WARNING").upper(), logging.WARNING))
    try:
        code = asyncio.run(_main_async(args))
    except Exception as exc:  # noqa: BLE001
        _print_json(_exception_error_payload("rdc_tool.cli", exc, transport="cli"))
        code = EXIT_RUNTIME_ERR
    finally:
        global _cli_owner_pid
        _cli_owner_pid = None
    raise SystemExit(int(code))


if __name__ == "__main__":
    main()
