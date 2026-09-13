from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from rdx.runtime_paths import artifacts_dir, logs_dir


DEFAULT_LOCAL_MARKERS = ["RenderGBuffer", "RenderForward"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cli_path() -> Path:
    return _repo_root() / "cli" / "run_cli.py"


def _python_cmd() -> str:
    env_python = str(os.environ.get("RDX_PYTHON") or "").strip()
    if env_python:
        return env_python
    bundled = _repo_root() / "binaries" / "windows" / "x64" / "python" / "python.exe"
    if bundled.is_file():
        return str(bundled)
    return sys.executable


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _artifact_dir_default() -> Path:
    return artifacts_dir() / "preview_geometry_smoke"


def _log_path_default(name: str, suffix: str) -> Path:
    return logs_dir() / f"{name}_{_timestamp()}{suffix}"


def _normalize_name(name: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(name or "").strip())
    return token or "preview"


def _run_cli_raw(context: str, *args: str) -> Dict[str, Any]:
    command = [_python_cmd(), str(_cli_path()), "--daemon-context", context, *args]
    result = subprocess.run(
        command,
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )
    payload: Dict[str, Any]
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
    except Exception:
        payload = {
            "ok": False,
            "error": {
                "code": "cli_output_not_json",
                "message": result.stdout.strip() or result.stderr.strip() or "CLI did not return JSON",
            },
        }
    payload["_returncode"] = int(result.returncode)
    payload["_stderr"] = result.stderr
    payload["_stdout"] = result.stdout
    return payload


def _call(context: str, operation: str, args: Optional[Dict[str, Any]] = None, *, expect_ok: bool = True) -> Dict[str, Any]:
    payload = _run_cli_raw(context, "call", operation, "--args-json", json.dumps(args or {}, ensure_ascii=False), "--format", "json")
    if expect_ok and (payload.get("_returncode") != 0 or not payload.get("ok")):
        raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def _daemon_action(context: str, action: str, *, expect_ok: bool = True) -> Dict[str, Any]:
    payload = _run_cli_raw(context, "daemon", action)
    if expect_ok and (payload.get("_returncode") != 0 or not payload.get("ok")):
        raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def _context_clear(context: str) -> Dict[str, Any]:
    return _run_cli_raw(context, "context", "clear")


def _flatten_actions(nodes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for node in nodes:
        out.append(node)
        out.extend(_flatten_actions(node.get("children") or []))
    return out


def _action_label(action: Dict[str, Any]) -> str:
    return str(action.get("name") or action.get("label") or "")


def _find_marker(flat_nodes: List[Dict[str, Any]], marker_hints: Iterable[str]) -> Optional[Dict[str, Any]]:
    candidates = list(marker_hints)
    for hint in candidates:
        lowered_hint = str(hint or "").strip().lower()
        if not lowered_hint:
            continue
        matched = [node for node in flat_nodes if lowered_hint in _action_label(node).lower()]
        if matched:
            return matched[-1]
    return None


def _draws_under_marker(flat_nodes: List[Dict[str, Any]], marker_event_id: int, marker_depth: int) -> List[Dict[str, Any]]:
    marker_index = -1
    for index, node in enumerate(flat_nodes):
        if int(node.get("event_id") or node.get("eventId") or 0) == int(marker_event_id):
            marker_index = index
            break
    if marker_index < 0:
        return []
    draws: List[Dict[str, Any]] = []
    for node in flat_nodes[marker_index + 1 :]:
        node_depth = int(node.get("depth") or 0)
        if node_depth <= int(marker_depth):
            break
        flags = dict(node.get("flags") or {})
        if bool(flags.get("is_draw")):
            draws.append(node)
    return draws


def _first_draws(flat_nodes: List[Dict[str, Any]], *, max_count: int = 12) -> List[Dict[str, Any]]:
    draws = [node for node in flat_nodes if bool(dict(node.get("flags") or {}).get("is_draw"))]
    return draws[: max(1, int(max_count))]


def _event_id(node: Dict[str, Any]) -> int:
    return int(node.get("event_id") or node.get("eventId") or 0)


def _has_framebuffer_output(draw: Dict[str, Any]) -> bool:
    outputs = list(draw.get("outputs") or [])
    for item in outputs:
        text = str(item or "").strip()
        if text and text not in {"0", "None", "ResourceId::0"}:
            return True
    return False


def _adb_path() -> Optional[str]:
    for candidate in (
        shutil.which("adb"),
        os.path.join(os.environ.get("ANDROID_SDK_ROOT", ""), "platform-tools", "adb.exe"),
        os.path.join(os.environ.get("ANDROID_HOME", ""), "platform-tools", "adb.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
    ):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def _adb_devices() -> Dict[str, Any]:
    adb = _adb_path()
    if not adb:
        return {"available": False, "reason": "adb_not_found", "devices": []}
    result = subprocess.run(
        [adb, "devices", "-l"],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    devices = [line for line in lines[1:] if len(line.split()) >= 2 and line.split()[1] == "device"]
    return {
        "available": True,
        "adb": adb,
        "returncode": int(result.returncode),
        "devices": devices,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _capture_desktop_image(path: Path) -> Optional[str]:
    try:
        from PIL import ImageGrab  # type: ignore[import-untyped]

        path.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(all_screens=False)
        image.save(path)
        return str(path)
    except Exception:
        return None


def _find_preview_window_rect(context_id: str) -> Optional[tuple[int, int, int, int]]:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        rect = ctypes.wintypes.RECT()
        titles: List[tuple[int, str]] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _enum_windows(hwnd, lparam):  # type: ignore[no-untyped-def]
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value or ""
            if title.startswith("RDX Preview [") and f"[{context_id}]" in title:
                titles.append((int(hwnd), title))
            return True

        user32.EnumWindows(_enum_windows, 0)
        if not titles:
            return None
        hwnd = titles[-1][0]
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        return None


def _capture_preview_window(context_id: str, path: Path) -> Optional[str]:
    bbox = _find_preview_window_rect(context_id)
    if bbox is None:
        return None
    try:
        from PIL import ImageGrab  # type: ignore[import-untyped]

        path.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(bbox=bbox, all_screens=False)
        image.save(path)
        return str(path)
    except Exception:
        return None


def _write_report(report: Dict[str, Any], out_json: Path, out_md: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Preview Geometry Smoke",
        "",
        f"- `local.status`: `{report['local']['status']}`",
        f"- `remote.status`: `{report['remote']['status']}`",
        f"- `artifact_dir`: `{report['artifact_dir']}`",
        "",
        "## Local",
        "",
        f"- status: `{report['local']['status']}`",
        f"- message: `{report['local'].get('message', '')}`",
    ]
    for scenario in report["local"].get("scenarios", []):
        lines.extend(
            [
                "",
                f"### {scenario['name']}",
                "",
                f"- status: `{scenario['status']}`",
                f"- marker: `{scenario.get('marker_name', '')}` @ `{scenario.get('marker_event_id', 0)}`",
                f"- draws: `{scenario.get('draw_count', 0)}`",
                f"- final event: `{scenario.get('last_draw_event_id', 0)}`",
                f"- screenshot: `{scenario.get('screenshot_path', '')}`",
                f"- desktop_screenshot: `{scenario.get('desktop_screenshot_path', '')}`",
                f"- preview_window_screenshot: `{scenario.get('preview_window_screenshot_path', '')}`",
            ],
        )
    lines.extend(
        [
            "",
            "## Remote",
            "",
            f"- status: `{report['remote']['status']}`",
            f"- message: `{report['remote'].get('message', '')}`",
        ],
    )
    for scenario in report["remote"].get("scenarios", []):
        lines.extend(
            [
                "",
                f"### {scenario['name']}",
                "",
                f"- status: `{scenario['status']}`",
                f"- draws: `{scenario.get('draw_count', 0)}`",
                f"- final event: `{scenario.get('last_draw_event_id', 0)}`",
                f"- screenshot: `{scenario.get('screenshot_path', '')}`",
                f"- desktop_screenshot: `{scenario.get('desktop_screenshot_path', '')}`",
                f"- preview_window_screenshot: `{scenario.get('preview_window_screenshot_path', '')}`",
            ],
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _set_active(context: str, session_id: str, event_id: int) -> None:
    _call(context, "rd.event.set_active", {"session_id": session_id, "event_id": int(event_id)})


def _preview_status(context: str) -> Dict[str, Any]:
    payload = _call(context, "rd.session.get_context", {})
    return dict(payload.get("data") or {})


def _step_draws(context: str, session_id: str, draws: List[Dict[str, Any]], *, hop_delay_ms: int) -> List[Dict[str, Any]]:
    hop_log: List[Dict[str, Any]] = []
    for draw in draws:
        event_id = int(draw.get("event_id") or draw.get("eventId") or 0)
        if event_id <= 0:
            continue
        payload = _call(context, "rd.event.set_active", {"session_id": session_id, "event_id": event_id})
        hop_log.append(
            {
                "event_id": event_id,
                "active_event_id": int(((payload.get("data") or {}).get("active_event_id") or 0)),
            }
        )
        if hop_delay_ms > 0:
            time.sleep(float(hop_delay_ms) / 1000.0)
    return hop_log


def _export_screenshot_for_draws(
    context: str,
    session_id: str,
    draws: List[Dict[str, Any]],
    output_path: Path,
) -> tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    prioritized = [draw for draw in draws if _has_framebuffer_output(draw)] or list(draws)
    attempts: List[Dict[str, Any]] = []
    for draw in list(reversed(prioritized))[:20]:
        event_id = _event_id(draw)
        if event_id <= 0:
            continue
        payload = _call(
            context,
            "rd.export.screenshot",
            {
                "session_id": session_id,
                "event_id": event_id,
                "output_path": str(output_path),
                "target": {"rt_index": 0},
            },
            expect_ok=False,
        )
        attempts.append(
            {
                "event_id": event_id,
                "ok": bool(payload.get("ok")),
                "error_code": str(((payload.get("error") or {}).get("code") or "")),
            }
        )
        if payload.get("_returncode") == 0 and payload.get("ok"):
            return payload, event_id, attempts
    raise RuntimeError(json.dumps({"error": "no_exportable_screenshot_draw", "attempts": attempts[-8:]}, ensure_ascii=False, indent=2))


def _smoke_preview_draw_sequence(
    *,
    context: str,
    session_id: str,
    draws: List[Dict[str, Any]],
    artifact_dir: Path,
    scenario_name: str,
    hop_delay_ms: int,
    marker: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not draws:
        return {"name": scenario_name, "status": "issue", "message": "no_draws"}
    _set_active(context, session_id, _event_id(draws[0]))
    _call(context, "rd.session.open_preview", {})
    hop_log = _step_draws(context, session_id, draws, hop_delay_ms=hop_delay_ms)
    safe_name = _normalize_name(scenario_name)
    shot_path = artifact_dir / f"{safe_name}_rt0.png"
    screenshot, screenshot_event_id, screenshot_attempts = _export_screenshot_for_draws(context, session_id, draws, shot_path)
    _set_active(context, session_id, screenshot_event_id)
    _call(context, "rd.session.open_preview", {})
    context_snapshot = _preview_status(context)
    preview_state = str((context_snapshot.get("preview") or {}).get("state") or "")
    if preview_state != "live":
        raise RuntimeError(
            json.dumps(
                {
                    "error": "preview_not_live",
                    "scenario": scenario_name,
                    "event_id": screenshot_event_id,
                    "preview": dict(context_snapshot.get("preview") or {}),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    desktop_path = artifact_dir / f"{safe_name}_desktop.png"
    preview_crop_path = artifact_dir / f"{safe_name}_preview.png"
    desktop_screenshot = _capture_desktop_image(desktop_path)
    preview_window_screenshot = _capture_preview_window(context, preview_crop_path)
    scenario: Dict[str, Any] = {
        "name": scenario_name,
        "status": "pass",
        "draw_count": len(draws),
        "first_draw_event_id": _event_id(draws[0]),
        "last_draw_event_id": _event_id(draws[-1]),
        "screenshot_event_id": screenshot_event_id,
        "preview": dict(context_snapshot.get("preview") or {}),
        "runtime": dict(context_snapshot.get("runtime") or {}),
        "screenshot_path": str((screenshot.get("data") or {}).get("saved_path") or shot_path),
        "desktop_screenshot_path": desktop_screenshot,
        "preview_window_screenshot_path": preview_window_screenshot,
        "screenshot_attempts_tail": screenshot_attempts[-8:],
        "hop_log_tail": hop_log[-12:],
    }
    if marker is not None:
        scenario["marker_name"] = _action_label(marker)
        scenario["marker_event_id"] = _event_id(marker)
    return scenario


def _smoke_local(
    *,
    capture_path: Path,
    artifact_dir: Path,
    daemon_context: str,
    marker_hints: List[str],
    hop_delay_ms: int,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "issue", "message": "", "scenarios": []}
    _context_clear(daemon_context)
    _daemon_action(daemon_context, "stop", expect_ok=False)
    try:
        _call(daemon_context, "rd.core.init", {})
        capture = _call(daemon_context, "rd.capture.open_file", {"file_path": str(capture_path)})
        capture_file_id = str((capture.get("data") or {}).get("capture_file_id") or "")
        replay = _call(daemon_context, "rd.capture.open_replay", {"capture_file_id": capture_file_id})
        session_id = str((replay.get("data") or {}).get("session_id") or "")
        tree = _call(daemon_context, "rd.event.get_action_tree", {"session_id": session_id, "max_depth": 32, "max_nodes": 30000})
        root = dict((tree.get("data") or {}).get("root") or {})
        flat_nodes = _flatten_actions(root.get("children") or [])
        scenarios: List[Dict[str, Any]] = []
        for marker_hint in marker_hints:
            marker = _find_marker(flat_nodes, [marker_hint])
            if marker is None:
                scenarios.append({"name": marker_hint, "status": "scope_skip", "message": "marker_not_found"})
                continue
            draws = _draws_under_marker(
                flat_nodes,
                int(marker.get("event_id") or marker.get("eventId") or 0),
                int(marker.get("depth") or 0),
            )
            if not draws:
                scenarios.append({"name": marker_hint, "status": "issue", "message": "no_draws_under_marker"})
                continue
            scenarios.append(
                _smoke_preview_draw_sequence(
                    context=daemon_context,
                    session_id=session_id,
                    draws=draws,
                    artifact_dir=artifact_dir,
                    scenario_name=f"local_{marker_hint}",
                    hop_delay_ms=hop_delay_ms,
                    marker=marker,
                )
            )
        if not any(item.get("status") == "pass" for item in scenarios):
            fallback_draws = _first_draws(flat_nodes, max_count=12)
            if fallback_draws:
                scenarios.append(
                    _smoke_preview_draw_sequence(
                        context=daemon_context,
                        session_id=session_id,
                        draws=fallback_draws,
                        artifact_dir=artifact_dir,
                        scenario_name="local_first_draws_fallback",
                        hop_delay_ms=hop_delay_ms,
                    )
                )
        _call(daemon_context, "rd.session.close_preview", {}, expect_ok=False)
        _call(daemon_context, "rd.core.shutdown", {}, expect_ok=False)
        result["status"] = "pass" if any(item.get("status") == "pass" for item in scenarios) else "issue"
        result["message"] = ""
        result["scenarios"] = scenarios
        return result
    except Exception as exc:
        result["status"] = "issue"
        result["message"] = str(exc)
        return result
    finally:
        _context_clear(daemon_context)
        _daemon_action(daemon_context, "stop", expect_ok=False)


def _smoke_remote(
    *,
    capture_path: Path,
    artifact_dir: Path,
    daemon_context: str,
    hop_delay_ms: int,
    device_serial: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "scope_skip", "message": "", "scenarios": []}
    adb_info = _adb_devices()
    if not adb_info.get("available"):
        result["message"] = str(adb_info.get("reason") or "adb unavailable")
        return result
    devices = list(adb_info.get("devices") or [])
    if not devices:
        result["message"] = "no adb device"
        return result
    selected_serial = str(device_serial or "")
    if not selected_serial:
        if len(devices) != 1:
            result["status"] = "issue"
            result["message"] = "multiple adb devices; pass --remote-device-serial"
            return result
        selected_serial = devices[0].split()[0]
    _context_clear(daemon_context)
    _daemon_action(daemon_context, "stop", expect_ok=False)
    try:
        _call(daemon_context, "rd.core.init", {})
        remote_connect = _call(
            daemon_context,
            "rd.remote.connect",
            {
                "options": {
                    "transport": "adb_android",
                    "device_serial": selected_serial,
                }
            },
        )
        remote_id = str((remote_connect.get("data") or {}).get("remote_id") or "")
        _call(daemon_context, "rd.remote.ping", {"remote_id": remote_id})
        capture = _call(daemon_context, "rd.capture.open_file", {"file_path": str(capture_path)})
        capture_file_id = str((capture.get("data") or {}).get("capture_file_id") or "")
        replay = _call(
            daemon_context,
            "rd.capture.open_replay",
            {"capture_file_id": capture_file_id, "options": {"remote_id": remote_id}},
        )
        session_id = str((replay.get("data") or {}).get("session_id") or "")
        tree = _call(daemon_context, "rd.event.get_action_tree", {"session_id": session_id, "max_depth": 32, "max_nodes": 30000})
        root = dict((tree.get("data") or {}).get("root") or {})
        flat_nodes = _flatten_actions(root.get("children") or [])
        draws = _first_draws(flat_nodes, max_count=10)
        if not draws:
            result["status"] = "issue"
            result["message"] = "no draw found in remote session"
            return result
        scenario = _smoke_preview_draw_sequence(
            context=daemon_context,
            session_id=session_id,
            draws=draws,
            artifact_dir=artifact_dir,
            scenario_name="remote_preview_follow",
            hop_delay_ms=hop_delay_ms,
        )
        scenario["remote_id"] = remote_id
        scenario["device_serial"] = selected_serial
        result["status"] = "pass"
        result["message"] = ""
        result["scenarios"] = [scenario]
        _call(daemon_context, "rd.session.close_preview", {}, expect_ok=False)
        _call(daemon_context, "rd.core.shutdown", {}, expect_ok=False)
        return result
    except Exception as exc:
        result["status"] = "issue"
        result["message"] = str(exc)
        return result
    finally:
        _context_clear(daemon_context)
        _daemon_action(daemon_context, "stop", expect_ok=False)


def _parse_marker_hints(raw: str) -> List[str]:
    items = [item.strip() for item in str(raw or "").split(",")]
    return [item for item in items if item]


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview geometry smoke with local/remote companion flows.")
    parser.add_argument("--local-rdc", default="", help="Local smoke .rdc path")
    parser.add_argument("--remote-rdc", default="", help="Remote smoke .rdc path; defaults to --local-rdc")
    parser.add_argument("--transport", choices=("local", "remote", "both"), default="both")
    parser.add_argument("--artifact-dir", default=str(_artifact_dir_default()))
    parser.add_argument("--out-json", default=str(_log_path_default("preview_geometry_smoke", ".json")))
    parser.add_argument("--out-md", default=str(_log_path_default("preview_geometry_smoke", ".md")))
    parser.add_argument("--daemon-context-prefix", default="preview-geometry-smoke")
    parser.add_argument("--local-marker-hints", default=",".join(DEFAULT_LOCAL_MARKERS))
    parser.add_argument("--hop-delay-ms", type=int, default=50)
    parser.add_argument("--remote-device-serial", default=str(os.environ.get("RDX_REMOTE_DEVICE_SERIAL") or ""))
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.out_json).resolve()
    out_md = Path(args.out_md).resolve()

    local_rdc = Path(args.local_rdc).resolve() if args.local_rdc else None
    remote_rdc = Path(args.remote_rdc).resolve() if args.remote_rdc else local_rdc
    local_context = f"{_normalize_name(args.daemon_context_prefix)}-local"
    remote_context = f"{_normalize_name(args.daemon_context_prefix)}-remote"

    report: Dict[str, Any] = {
        "artifact_dir": str(artifact_dir),
        "local": {"status": "scope_skip", "message": "", "scenarios": []},
        "remote": {"status": "scope_skip", "message": "", "scenarios": []},
        "meta": {
            "transport": args.transport,
            "local_context": local_context,
            "remote_context": remote_context,
            "hop_delay_ms": int(args.hop_delay_ms),
        },
    }

    if args.transport in {"local", "both"}:
        if local_rdc is None or not local_rdc.is_file():
            report["local"] = {"status": "scope_skip", "message": "local_rdc_missing", "scenarios": []}
        else:
            report["local"] = _smoke_local(
                capture_path=local_rdc,
                artifact_dir=artifact_dir,
                daemon_context=local_context,
                marker_hints=_parse_marker_hints(args.local_marker_hints),
                hop_delay_ms=int(args.hop_delay_ms),
            )

    if args.transport in {"remote", "both"}:
        if remote_rdc is None or not remote_rdc.is_file():
            report["remote"] = {"status": "scope_skip", "message": "remote_rdc_missing", "scenarios": []}
        else:
            report["remote"] = _smoke_remote(
                capture_path=remote_rdc,
                artifact_dir=artifact_dir,
                daemon_context=remote_context,
                hop_delay_ms=int(args.hop_delay_ms),
                device_serial=str(args.remote_device_serial or ""),
            )

    _write_report(report, out_json, out_md)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    has_issue = any(str(report[key].get("status") or "") == "issue" for key in ("local", "remote"))
    return 1 if has_issue else 0


if __name__ == "__main__":
    exit_code = int(main())
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(exit_code)
