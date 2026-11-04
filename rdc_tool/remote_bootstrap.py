"""Android remote bootstrap helpers for standalone `rdc-tool`."""

from __future__ import annotations

import os
import hashlib
import json
import struct
import zipfile
import contextvars
import threading
import re
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from rdc_tool.runtime_paths import android_binaries_root, runtime_root
from rdc_tool.android_apk_identity import read_apk_identity
from rdc_tool.android_install_state import parse_active_install_sessions
from rdc_tool.timeout_policy import DEFAULT_DAEMON_REQUEST_TIMEOUT_S

DEFAULT_ANDROID_REMOTE_PORT = 38920
DEFAULT_ANDROID_TIMEOUT_MS = 120000
_PACKAGE_MAP = {
    "arm32": "org.renderdoc.renderdoccmd.arm32",
    "arm64": "org.renderdoc.renderdoccmd.arm64",
}
_REMOTE_SOCKET_TEMPLATE = "renderdoc_{port}"
_REMOTE_SOCKET_RE = re.compile(r"@renderdoc_(\d+)")
# RenderDoc globalconfig.h: RenderDoc_FirstTargetControlPort and
# RenderDoc_LastTargetControlPort; Android maps these to renderdoc_<port>
# abstract sockets (android_process.cpp). The replay-server socket is separate.
_ANDROID_TARGET_CONTROL_PORTS = range(38920, 38928)


class AndroidRemoteBootstrapError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Optional[dict[str, object]] = None) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})


class ConnectionBudget:
    """One deadline and cancellation signal for one remote connection attempt."""
    def __init__(self, timeout_ms: int, cancelled: Optional[threading.Event] = None):
        self.deadline = time.monotonic() + max(timeout_ms, 1) / 1000
        self.cancelled = cancelled or threading.Event()

    def remaining(self, maximum: float = float("inf")) -> float:
        if self.cancelled.is_set():
            raise AndroidRemoteBootstrapError("remote_connect_cancelled", "Remote connection cancelled")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AndroidRemoteBootstrapError("remote_connect_timeout", "Remote connection deadline exceeded")
        return min(maximum, remaining)


_connection_budget: contextvars.ContextVar[Optional[ConnectionBudget]] = contextvars.ContextVar("android_connection_budget", default=None)


def _remaining(maximum: float) -> float:
    budget = _connection_budget.get()
    return budget.remaining(maximum) if budget else maximum


def _run_process(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    if os.name == "nt":
        # ADB needs normal redirected stdio, not CREATE_NO_WINDOW or an
        # explicitly allocated console. Hide any console Windows creates.
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs.setdefault("startupinfo", startup)
        kwargs.setdefault("creationflags", subprocess.CREATE_NEW_PROCESS_GROUP)
    budget = _connection_budget.get()
    if budget is None:
        return subprocess.run(cmd, **kwargs)
    deadline = time.monotonic() + budget.remaining(float(kwargs.pop("timeout", 10)))
    kwargs.pop("check", None)
    kwargs.pop("capture_output", None)
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs) as proc:
        try:
            while True:
                timeout = min(0.25, budget.remaining(), max(0.001, deadline - time.monotonic()))
                try:
                    out, err = proc.communicate(timeout=timeout)
                    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise
        except BaseException:
            proc.kill()
            proc.communicate()
            raise


@dataclass
class AdbDevice:
    serial: str
    state: str
    detail: str = ""


@dataclass
class AndroidBootstrapResult:
    adb_path: str
    device_serial: str
    package_name: str
    activity_name: str
    abi: str
    host: str
    port: int
    remote_port: int
    apk_path: str
    forward_spec: str
    config_local_path: str = ""
    config_remote_path: str = ""
    started_activity: bool = False
    owned_pids: list[int] = field(default_factory=list)
    installed_apk: bool = False
    pushed_config: bool = False
    created_forward: bool = False
    install_mode: str = ""
    install_reason: str = ""
    uninstalled_existing: bool = False
    cleanup_actions: list[str] = field(default_factory=list)
    stage: str = "checking"
    expected_version: str = ""
    apk_sha256: str = ""
    installed_apk_path: str = ""
    installed_apk_sha256: str = ""
    apk_identity_status: str = "unavailable"
    apk_identity_reason: str = "not_observed"
    installed_identity: str = ""
    service_identity: list[str] = field(default_factory=list)


@dataclass
class AndroidBootstrapOptions:
    device_serial: str = ""
    local_port: int = 0
    expected_version: str = ""
    progress: Optional[Callable[[str], None]] = None
    push_config: bool = True




def resolve_adb_path() -> str:
    from rdc_tool.host_tools import resolve_host_tool, HostToolUnavailableError
    try:
        return str(resolve_host_tool("adb"))
    except HostToolUnavailableError as error:
        raise AndroidRemoteBootstrapError("adb_unavailable", str(error)) from error


def _run_subprocess(
    cmd: list[str],
    *,
    timeout_s: float,
    error_code: str,
    error_message: str,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = _run_process(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AndroidRemoteBootstrapError(error_code, error_message, details={"command": cmd, "reason": str(exc)}) from exc
    except subprocess.TimeoutExpired as exc:
        raise AndroidRemoteBootstrapError(
            error_code,
            f"{error_message}: timed out after {timeout_s:.1f}s",
            details={"command": cmd},
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise AndroidRemoteBootstrapError(
            error_code,
            f"{error_message}: {stderr or 'command failed'}",
            details={"command": cmd, "returncode": proc.returncode,
                "stdout": str(proc.stdout or "")[:4096], "stderr": str(proc.stderr or "")[:4096]},
        )
    return proc


def _helper_snapshot(result: AndroidBootstrapResult) -> dict[str, object]:
    """Observe identities without mutating the existing package or service."""
    probe = _adb_shell(result.adb_path, result.device_serial, "dumpsys", "package", result.package_name,
        timeout_s=15.0, error_code="android_package_probe_failed", error_message="Failed to inspect Android helper identity")
    text = str(probe.stdout or "")
    if str(probe.stderr or "").strip():
        raise AndroidRemoteBootstrapError("android_package_probe_failed", "Android helper identity is unavailable")
    version = re.search(r"(?m)^\s*versionName=(\S+)", text)
    code = re.search(r"(?m)^\s*versionCode=(\d+)", text)
    # Hash immutable installed package facts, not timestamps or process counters.
    facts = re.findall(r"(?m)^\s*(?:versionCode|versionName|codePath|firstInstallTime|lastUpdateTime|signatures|apkSigningVersion)=[^\r\n]+", text)
    installed = hashlib.sha256("\n".join(line.strip() for line in facts).encode()).hexdigest() if facts else ""
    identities: list[str] = []
    for pid in _package_pids(result.adb_path, result.device_serial, result.package_name):
        stat = _adb_shell(result.adb_path, result.device_serial, "cat", f"/proc/{pid}/stat",
            timeout_s=10.0, error_code="android_helper_state_unknown", error_message="Failed to verify Android helper process identity")
        fields = str(stat.stdout or "").rsplit(")", 1)
        tail = fields[1].split() if len(fields) == 2 else []
        if len(tail) < 20 or not tail[19].isdigit():
            raise AndroidRemoteBootstrapError("android_helper_state_unknown", "Android helper process birth identity is unavailable")
        identities.append(f"{pid}:{tail[19]}")
    if not result.apk_path:
        arch = next(key for key, name in _PACKAGE_MAP.items() if name == result.package_name)
        _, target_path = select_android_package(arch)
        result.apk_path = str(target_path)
    apk = Path(result.apk_path)
    if not apk.is_file():
        raise AndroidRemoteBootstrapError("android_apk_missing", "Matching Android RenderDoc helper APK is missing", details={"apk_path": str(apk)})
    try:
        target = read_apk_identity(str(apk))
    except (ValueError, OSError, KeyError, IndexError, zipfile.BadZipFile, struct.error) as exc:
        raise AndroidRemoteBootstrapError("android_apk_invalid", "Matching Android helper APK identity is invalid") from exc
    if target["package_name"] != result.package_name:
        raise AndroidRemoteBootstrapError("android_apk_invalid", "APK package identity does not match selected helper")
    return {"package_name": result.package_name, "device_serial": result.device_serial,
        "apk_sha256": target["apk_sha256"], "target_version_code": target["version_code"],
        "installed_version_code": int(code.group(1)) if code else None, "installed_identity": installed,
        "service_identity": identities, "expected_version": result.expected_version,
        "actual_version": version.group(1) if version else ""}


def _assert_helper_identity(result: AndroidBootstrapResult) -> dict[str, object]:
    """Automatic replacement is limited to the selected, observed helper package."""
    facts = _helper_snapshot(result)
    if (result.package_name not in _PACKAGE_MAP.values() or not facts["installed_identity"]
            or facts["package_name"] != result.package_name or facts["device_serial"] != result.device_serial):
        raise AndroidRemoteBootstrapError("android_helper_state_unknown", "Cannot identify the selected Android helper")
    result.apk_sha256 = str(facts["apk_sha256"])
    return facts


def _device_install_action(result: AndroidBootstrapResult, sessions: list[dict[str, object]], observation: str) -> dict[str, object]:
    return {"kind": "android_install", "state": "unconfirmed", "device_serial": result.device_serial,
        "package_name": result.package_name, "apk_sha256": result.apk_sha256, "sessions": sessions, "observation": observation}


def _inspect_android_install_state(result: AndroidBootstrapResult) -> dict[str, object]:
    try:
        probe = _adb_shell(result.adb_path, result.device_serial, "dumpsys", "package", "installs",
            timeout_s=15.0, error_code="android_install_state_unknown", error_message="Failed to inspect PackageManager active installs")
        if str(probe.stderr or "").strip():
            raise ValueError("PackageManager returned diagnostic output")
        active = parse_active_install_sessions(probe.stdout)
    except (AndroidRemoteBootstrapError, ValueError) as error:
        if isinstance(error, AndroidRemoteBootstrapError) and error.code in {"remote_connect_cancelled", "remote_connect_timeout"}:
            raise
        return {"installation_state": "unknown", "observation": "unreadable", "sessions": [], "diagnostic": str(error)[:4096]}
    blocking = [session for session in active if session["package_name"] in (None, result.package_name)]
    return {"installation_state": "pending" if blocking else "clear", "observation": "pending" if blocking else "verified", "sessions": blocking}


def _wait_for_android_install(result: AndroidBootstrapResult, *, require_target: bool,
                            receipt: Optional[dict[str, object]] = None) -> None:
    """Resolve device-side completion inside the original connection budget, without reinstalling."""
    observed = None
    deadline = time.monotonic() + DEFAULT_ANDROID_TIMEOUT_MS / 1000
    def remaining():
        value = _remaining(1.0)
        if _connection_budget.get() is None:
            value = min(value, deadline - time.monotonic())
            if value <= 0:
                raise AndroidRemoteBootstrapError("remote_connect_timeout", "Installation verification deadline exceeded")
        return value
    try:
        while True:
            remaining()
            observed = _inspect_android_install_state(result)
            if observed["installation_state"] == "clear":
                if not require_target:
                    return
                _observe_installed_apk(result)
                if result.apk_identity_status == "matched":
                    return
            time.sleep(remaining())
    except AndroidRemoteBootstrapError as error:
        if error.code not in {"remote_connect_timeout", "remote_connect_cancelled"}:
            raise
        if not require_target and observed is None:
            raise
        observed = observed or {"sessions": [], "observation": "unreadable"}
        details = {**(receipt or {}), "device_action": _device_install_action(
            result, observed["sessions"], str(observed["observation"])),
            "installed_apk_identity": result.apk_identity_status, "reason": error.code}
        raise AndroidRemoteBootstrapError("remote_install_unconfirmed",
            "Android installation could not be verified within the connection budget", details=details) from error


def _preflight_android_install(result: AndroidBootstrapResult) -> None:
    _wait_for_android_install(result, require_target=False)


def _read_android_helper_apk(result: AndroidBootstrapResult) -> dict[str, object]:
    if not Path(result.apk_path).is_file():
        raise AndroidRemoteBootstrapError("android_apk_missing", f"Missing Android RenderDocCmd APK: {result.apk_path}")
    try:
        target = read_apk_identity(result.apk_path)
    except (ValueError, OSError, KeyError, IndexError, zipfile.BadZipFile, struct.error) as error:
        raise AndroidRemoteBootstrapError("android_apk_invalid", "Android helper APK identity is invalid") from error
    if target["package_name"] != result.package_name:
        raise AndroidRemoteBootstrapError("android_apk_invalid", "APK package identity does not match requested helper")
    result.apk_sha256 = str(target["apk_sha256"])
    return target


def _install_android_helper(result: AndroidBootstrapResult, opts: AndroidBootstrapOptions, *, update: bool = False, downgrade: bool = False) -> None:
    _read_android_helper_apk(result)
    _preflight_android_install(result)
    result.stage = "installing"
    if opts.progress: opts.progress("installing")
    command = _adb_base_cmd(result.adb_path, result.device_serial) + ["install"]
    if update: command.append("-r")
    if downgrade: command.append("-d")
    command += ["-g", "--force-queryable", result.apk_path]
    # PackageManager commit is joined even if cancellation arrives. Record a
    # successful installation before observing the cancelled intent.
    timeout = _remaining(180.0)
    token = _connection_budget.set(None)
    try:
        proc = _run_process(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        # The ADB client has joined, but PackageManager may still own a sealed
        # device-side session. Never claim rollback or device-side completion.
        stdout = error.stdout.decode("utf-8", errors="replace") if isinstance(error.stdout, bytes) else str(error.stdout or "")
        stderr = error.stderr.decode("utf-8", errors="replace") if isinstance(error.stderr, bytes) else str(error.stderr or "")
        _connection_budget.reset(token)
        token = _connection_budget.set(_connection_budget.get())
        _wait_for_android_install(result, require_target=True, receipt={"timeout_seconds": timeout,
            "stdout": stdout[:4096], "stderr": stderr[:4096]})
        proc = subprocess.CompletedProcess(command, 0, "Success", "")
    finally:
        _connection_budget.reset(token)
    stdout, stderr = str(proc.stdout or ""), str(proc.stderr or "")
    diagnostic = "\n".join(part.strip() for part in (stderr, stdout) if part.strip())
    succeeded = bool(re.search(r"(?m)^Success\s*$", stdout))
    failed = bool(re.search(r"\b(?:INSTALL_FAILED_|INSTALL_PARSE_FAILED_)[A-Z0-9_]+\b|^\s*Failure\s*\[[^\r\n]+\]", diagnostic, re.MULTILINE))
    if (not succeeded and not failed) or (succeeded and (failed or proc.returncode != 0)):
        _wait_for_android_install(result, require_target=True, receipt={
            "returncode": proc.returncode, "stdout": stdout[:4096], "stderr": stderr[:4096]})
        failed = False
    if failed:
        if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in diagnostic and update:
            _preflight_android_install(result)
            _assert_helper_identity(result)
            _remaining(1.0)
            token = _connection_budget.set(None)
            try:
                removed = _adb_shell(result.adb_path, result.device_serial, "pm", "uninstall", result.package_name,
                    timeout_s=30.0, error_code="android_apk_uninstall_failed", error_message="Failed to remove confirmed conflicting helper")
            finally:
                _connection_budget.reset(token)
            if str(removed.stdout or "").strip() != "Success":
                raise AndroidRemoteBootstrapError("android_apk_uninstall_failed", "PackageManager did not confirm helper removal")
            result.uninstalled_existing = True
            _remaining(1.0)
            _install_android_helper(result, AndroidBootstrapOptions(expected_version=opts.expected_version, progress=opts.progress))
            result.install_mode = "force_replace"
            return
        if "INSTALL_FAILED_VERSION_DOWNGRADE" in diagnostic and update and not downgrade:
            _assert_helper_identity(result)
            _install_android_helper(result, opts, update=True, downgrade=True)
            return
        raise AndroidRemoteBootstrapError("android_apk_install_failed", f"Failed to install Android helper: {diagnostic}", details={"returncode": proc.returncode})
    result.installed_apk = True
    result.install_mode = "update" if update else "install"
    result.install_reason = "incompatible_helper" if update else "missing_helper"
    result.cleanup_actions.append("apk-installed")
    _remaining(1.0)


def _ensure_android_helper_installed(result: AndroidBootstrapResult, opts: AndroidBootstrapOptions) -> None:
    adb_path, device_serial, package_name = result.adb_path, result.device_serial, result.package_name
    probe = _adb_shell(adb_path, device_serial, "pm", "list", "packages", package_name,
        timeout_s=15.0, error_code="android_package_probe_failed", error_message="Failed to determine whether the Android helper is installed")
    packages = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if getattr(probe, "stderr", "").strip() or any(re.fullmatch(r"package:[A-Za-z0-9_.]+", line) is None for line in packages):
        raise AndroidRemoteBootstrapError("android_package_probe_failed", "Android package query returned an unknown state")
    if f"package:{package_name}" not in packages:
        _install_android_helper(result, opts)
        return
    result.install_mode, result.install_reason = "existing", "installed_helper_preserved"
    if not result.expected_version:
        return
    facts = _helper_snapshot(result)
    result.installed_identity, result.apk_sha256 = str(facts["installed_identity"]), str(facts["apk_sha256"])
    installed, expected = facts["installed_version_code"], facts["target_version_code"]
    if installed is None or installed == expected:
        return  # Native handshake remains the authority, not versionName.
    _assert_helper_identity(result)
    _install_android_helper(result, opts, update=True, downgrade=installed > expected)


def repair_incompatible_android_helper(result: AndroidBootstrapResult, opts: AndroidBootstrapOptions) -> None:
    """Repair only after native incompatibility; never used for a busy server."""
    if not result.started_activity:
        _assert_helper_identity(result)
        _adb_shell(result.adb_path, result.device_serial, "am", "force-stop", result.package_name,
            timeout_s=15.0, error_code="android_remote_stop_failed", error_message="Failed to stop incompatible helper")
    errors = cleanup_android_remote(result)
    if errors:
        raise AndroidRemoteBootstrapError("android_cleanup_failed", "Could not release helper before repair", details={"cleanup_errors": errors})
    if _package_pids(result.adb_path, result.device_serial, result.package_name):
        raise AndroidRemoteBootstrapError("remote_repair_state_changed", "Helper restarted before repair")
    _install_android_helper(result, opts, update=True)


def _adb_base_cmd(adb_path: str, device_serial: str = "") -> list[str]:
    cmd = [adb_path]
    if device_serial:
        cmd.extend(["-s", device_serial])
    return cmd


def parse_adb_devices(output: str) -> list[AdbDevice]:
    devices: list[AdbDevice] = []
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0].strip()
        state = parts[1].strip()
        detail = " ".join(parts[2:]).strip()
        devices.append(AdbDevice(serial=serial, state=state, detail=detail))
    return devices


def choose_adb_device(devices: list[AdbDevice], requested_serial: str = "") -> AdbDevice:
    requested_serial = str(requested_serial or "").strip()
    if requested_serial:
        for device in devices:
            if device.serial == requested_serial:
                if device.state != "device":
                    raise AndroidRemoteBootstrapError(
                        "adb_device_unavailable",
                        f"adb device {requested_serial} is not ready: {device.state}",
                        details={"serial": requested_serial, "state": device.state},
                    )
                return device
        raise AndroidRemoteBootstrapError(
            "adb_device_not_found",
            f"adb device {requested_serial} was not found.",
            details={"serial": requested_serial},
        )

    ready = [device for device in devices if device.state == "device"]
    if not ready:
        raise AndroidRemoteBootstrapError("adb_no_device", "No Android device is available in `adb devices -l`.")
    if len(ready) > 1:
        serials = ", ".join(device.serial for device in ready)
        raise AndroidRemoteBootstrapError(
            "adb_multiple_devices",
            "Multiple Android devices are connected; specify `options.device_serial`.",
            details={"serials": serials},
        )
    return ready[0]


def normalize_android_arch(abi_value: str) -> tuple[str, str]:
    abi = str(abi_value or "").strip()
    lowered = abi.lower()
    if "arm64" in lowered:
        return "arm64", abi
    if "armeabi" in lowered or lowered.startswith("arm"):
        return "arm32", abi
    raise AndroidRemoteBootstrapError(
        "android_abi_unsupported",
        f"Unsupported Android ABI for packaged RenderDocCmd APKs: {abi or 'unknown'}",
        details={"abi": abi},
    )


def select_android_package(arch: str) -> tuple[str, Path]:
    key = str(arch or "").strip().lower()
    package = _PACKAGE_MAP.get(key)
    if not package:
        raise AndroidRemoteBootstrapError(
            "android_arch_unsupported",
            f"Unsupported Android RenderDocCmd package arch: {arch}",
            details={"arch": arch},
        )
    apk_path = android_binaries_root() / key / f"{package}.apk"
    return package, apk_path


def allocate_local_port(requested_port: int = 0) -> int:
    if int(requested_port or 0) > 0:
        return int(requested_port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _config_workspace() -> Path:
    path = runtime_root() / "android_remote"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_renderdoc_conf(package_name: str) -> Path:
    config_path = _config_workspace() / f"{package_name}.renderdoc.conf"
    config_path.write_text("", encoding="utf-8")
    return config_path


def _ensure_renderdoc_conf(result: AndroidBootstrapResult) -> None:
    sdk_probe = _adb_shell(
        result.adb_path,
        result.device_serial,
        "getprop",
        "ro.build.version.sdk",
        timeout_s=10.0,
        error_code="android_sdk_probe_failed",
        error_message="Failed to query Android SDK level for RenderDoc config path",
    )
    sdk_text = sdk_probe.stdout.strip()
    if not sdk_text.isascii() or not sdk_text.isdigit() or int(sdk_text) < 1:
        raise AndroidRemoteBootstrapError(
            "android_sdk_probe_failed",
            "Android SDK level is missing or invalid",
            details={"sdk_level": sdk_text},
        )
    # Match RenderDoc's Android FileIO::GetTempRootPath: SDK 30+ uses Android/media.
    storage_dir = "media" if int(sdk_text) >= 30 else "data"
    remote_dir = f"/sdcard/Android/{storage_dir}/{result.package_name}/files"
    remote_conf = f"{remote_dir}/renderdoc.conf"
    quoted_path = shlex.quote(remote_conf)
    probe = _adb_shell(
        result.adb_path,
        result.device_serial,
        f"if [ -f {quoted_path} ]; then printf existing; "
        f"elif [ -e {quoted_path} ]; then printf invalid; else printf missing; fi",
        timeout_s=15.0,
        error_code="android_config_probe_failed",
        error_message="Failed to inspect remote RenderDoc config",
    )
    state = probe.stdout.strip()
    if state == "existing":
        result.config_remote_path = remote_conf
        return
    if state != "missing":
        raise AndroidRemoteBootstrapError(
            "android_config_probe_failed",
            "Remote RenderDoc config is not a regular file or its state is unknown",
            details={"config_remote_path": remote_conf, "state": state},
        )

    config_path = _write_renderdoc_conf(result.package_name)
    result.config_local_path = str(config_path)
    _adb_shell(
        result.adb_path,
        result.device_serial,
        "mkdir",
        "-p",
        remote_dir,
        timeout_s=15.0,
        error_code="android_config_push_failed",
        error_message="Failed to create remote RenderDoc config directory",
    )
    _run_subprocess(
        _adb_base_cmd(result.adb_path, result.device_serial) + ["push", str(config_path), remote_conf],
        timeout_s=30.0,
        error_code="android_config_push_failed",
        error_message="Failed to push renderdoc.conf to Android device",
    )
    result.config_remote_path = remote_conf
    result.pushed_config = True
    result.cleanup_actions.append("config-pushed")


def _adb_shell(adb_path: str, device_serial: str, *args: str, timeout_s: float, error_code: str, error_message: str) -> subprocess.CompletedProcess[str]:
    cmd = _adb_base_cmd(adb_path, device_serial)
    cmd.extend(["shell", *args])
    return _run_subprocess(cmd, timeout_s=timeout_s, error_code=error_code, error_message=error_message)


def _observe_installed_apk(result: AndroidBootstrapResult) -> None:
    """Read the selected package's bytes without changing preparation policy."""
    result.installed_apk_path = result.installed_apk_sha256 = ""
    result.apk_identity_status, result.apk_identity_reason = "unavailable", "not_observed"
    try:
        probe = _adb_shell(result.adb_path, result.device_serial, "pm", "path", result.package_name,
            timeout_s=_remaining(5.0), error_code="android_package_probe_failed",
            error_message="Failed to observe installed helper APK path")
        _remaining(1.0)
        lines = [line.strip() for line in str(probe.stdout or "").splitlines() if line.strip()]
        if str(probe.stderr or "").strip():
            result.apk_identity_reason = "installed_apk_path_unreadable"
            return
        if len(lines) != 1:
            result.apk_identity_reason = "installed_apk_missing" if not lines else "installed_apk_split_or_ambiguous"
            return
        match = re.fullmatch(r"package:(/[^\s\x00]+/base\.apk)", lines[0])
        if not match:
            result.apk_identity_reason = "installed_apk_path_invalid"
            return
        result.installed_apk_path = match.group(1)
        digest = _adb_shell(result.adb_path, result.device_serial, "sha256sum", shlex.quote(result.installed_apk_path),
            timeout_s=_remaining(5.0), error_code="android_package_probe_failed",
            error_message="Failed to observe installed helper APK hash")
        _remaining(1.0)
        match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?(/[^\r\n\x00]+)", str(digest.stdout or "").strip())
        if str(digest.stderr or "").strip() or not match or match.group(2) != result.installed_apk_path:
            result.apk_identity_reason = "installed_apk_hash_unreadable"
            return
        result.installed_apk_sha256 = match.group(1).lower()
        if not result.apk_sha256:
            # Borrowing a running helper still does not require a local APK.
            # Read the optional same-install target only for this comparison.
            arch = next((arch for arch, package in _PACKAGE_MAP.items() if package == result.package_name), "")
            target_path = Path(result.apk_path) if result.apk_path else android_binaries_root() / arch / f"{result.package_name}.apk"
            target = read_apk_identity(str(target_path))
            _remaining(1.0)
            if target["package_name"] == result.package_name:
                result.apk_sha256 = str(target["apk_sha256"])
        if not re.fullmatch(r"[0-9a-fA-F]{64}", result.apk_sha256):
            result.apk_identity_reason = "target_apk_identity_unavailable"
            return
        matched = result.installed_apk_sha256 == result.apk_sha256.lower()
        result.apk_identity_status = "matched" if matched else "different"
        result.apk_identity_reason = "installed_apk_matches_target" if matched else "installed_apk_differs_from_target"
    except AndroidRemoteBootstrapError as exc:
        if exc.code in {"remote_connect_cancelled", "remote_connect_timeout"}:
            raise
        _remaining(1.0)
        result.apk_identity_reason = "installed_apk_probe_failed"
    except (OSError, ValueError, KeyError, IndexError, zipfile.BadZipFile, struct.error):
        _remaining(1.0)
        result.apk_identity_reason = "target_apk_identity_unavailable"


def detect_device_arch(adb_path: str, device_serial: str) -> tuple[str, str]:
    for prop in ("ro.product.cpu.abilist64", "ro.product.cpu.abilist", "ro.product.cpu.abi"):
        proc = _adb_shell(
            adb_path,
            device_serial,
            "getprop",
            prop,
            timeout_s=10.0,
            error_code="android_abi_probe_failed",
            error_message=f"Failed to query Android ABI via {prop}",
        )
        values = [item.strip() for item in (proc.stdout or "").replace(",", "\n").splitlines() if item.strip()]
        for value in values:
            try:
                return normalize_android_arch(value)
            except AndroidRemoteBootstrapError:
                continue
    raise AndroidRemoteBootstrapError(
        "android_abi_unknown",
        "Unable to determine Android device ABI from adb properties.",
        details={"serial": device_serial},
    )


def _package_pids(adb_path: str, device_serial: str, package_name: str) -> list[int]:
    try:
        proc = _run_process(
            _adb_base_cmd(adb_path, device_serial) + ["shell", "pidof", package_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10.0,
            check=False,
        )
    except AndroidRemoteBootstrapError:
        raise
    except Exception as exc:
        raise AndroidRemoteBootstrapError("android_helper_state_unknown", "Unable to verify Android helper ownership") from exc
    stdout, stderr = str(proc.stdout or "").strip(), str(proc.stderr or "").strip()
    if proc.returncode == 1 and not stdout and not stderr:
        return []
    if proc.returncode == 0 and stdout and all(part.isdigit() for part in stdout.split()):
        return sorted(int(part) for part in stdout.split())
    raise AndroidRemoteBootstrapError("android_helper_state_unknown", "Unable to verify Android helper ownership")

def _list_renderdoc_socket_ports(adb_path: str, device_serial: str) -> list[int]:
    try:
        proc = _adb_shell(
            adb_path,
            device_serial,
            "cat",
            "/proc/net/unix",
            timeout_s=10.0,
            error_code="android_socket_probe_failed",
            error_message="Failed to inspect Android unix sockets",
        )
    except AndroidRemoteBootstrapError:
        raise
    lines = str(proc.stdout or "").splitlines()
    if (proc.returncode != 0 or str(proc.stderr or "").strip() or not lines
            or lines[0].split() != ["Num", "RefCount", "Protocol", "Flags", "Type", "St", "Inode", "Path"]):
        raise AndroidRemoteBootstrapError(
            "android_socket_probe_failed", "Android unix socket listing is unreadable or malformed"
        )
    ports: list[int] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 7 or not re.fullmatch(r"[0-9a-fA-F]+:", fields[0]):
            raise AndroidRemoteBootstrapError("android_socket_probe_failed", "Malformed Android unix socket row")
        match = _REMOTE_SOCKET_RE.fullmatch(fields[7]) if len(fields) == 8 else None
        if not match:
            continue
        try:
            ports.append(int(match.group(1)))
        except Exception:
            continue
    return sorted(set(ports))


def list_android_target_idents(adb_path: str, device_serial: str) -> list[int]:
    return [port for port in _list_renderdoc_socket_ports(adb_path, device_serial)
            if port in _ANDROID_TARGET_CONTROL_PORTS]


def forward_android_target(adb_path: str, device_serial: str, ident: int) -> AndroidBootstrapResult:
    if int(ident) not in _ANDROID_TARGET_CONTROL_PORTS:
        raise AndroidRemoteBootstrapError("android_target_invalid", "Invalid Android target control ident")
    local_port = allocate_local_port()
    result = AndroidBootstrapResult(
        adb_path=adb_path, device_serial=device_serial, package_name="", activity_name="", abi="",
        host="127.0.0.1", port=local_port, remote_port=int(ident), apk_path="",
        forward_spec=f"tcp:{local_port}",
    )
    _run_subprocess(
        _adb_base_cmd(adb_path, device_serial)
        + ["forward", "--no-rebind", result.forward_spec, f"localabstract:renderdoc_{ident}"],
        timeout_s=10.0, error_code="adb_forward_failed",
        error_message="Failed to establish Android target control forward",
    )
    result.created_forward = True
    return result


def _select_remote_socket_port(requested_port: int, before_ports: list[int], after_ports: list[int]) -> int:
    requested = int(requested_port or 0)
    if requested > 0 and requested in after_ports:
        return requested
    if len(after_ports) == 1:
        return int(after_ports[0])
    if not after_ports:
        raise AndroidRemoteBootstrapError(
            "android_remote_socket_missing",
            f"RenderDoc remote socket renderdoc_{requested} was not found on Android device.",
            details={"requested_port": requested, "discovered_ports": list(after_ports)},
        )
    raise AndroidRemoteBootstrapError(
        "android_remote_socket_ambiguous",
        "Unable to determine Android RenderDoc remote socket port.",
        details={"requested_port": requested, "discovered_ports": list(after_ports)},
    )


def _select_android_device(adb_path: str, requested_serial: str) -> AdbDevice:
    requested_serial = str(requested_serial or "").strip()
    if requested_serial:
        command = [adb_path, "-s", requested_serial, "get-state"]
        probe = _run_subprocess(command, timeout_s=10.0,
            error_code="adb_device_query_failed", error_message="Failed to query selected Android device")
        state = probe.stdout.strip()
        if not re.fullmatch(r"[a-z][a-z_-]{0,31}", state):
            raise AndroidRemoteBootstrapError("adb_device_invalid_response", "Selected Android device query returned an invalid state",
                details={"stage": "adb_device_state", "command": command, "returncode": probe.returncode,
                    "stdout": str(probe.stdout or "")[:4096], "stderr": str(probe.stderr or "")[:4096]})
        device = choose_adb_device([AdbDevice(requested_serial, state)], requested_serial)
    else:
        command = [adb_path, "devices", "-l"]
        device_proc = _run_subprocess(command, timeout_s=10.0,
            error_code="adb_devices_failed", error_message="Failed to query adb devices")
        if not device_proc.stdout.lstrip().startswith("List of devices attached"):
            raise AndroidRemoteBootstrapError("adb_devices_invalid_response", "ADB device query returned an invalid response",
                details={"stage": "adb_device_state", "command": command, "returncode": device_proc.returncode,
                    "stdout": str(device_proc.stdout or "")[:4096], "stderr": str(device_proc.stderr or "")[:4096]})
        device = choose_adb_device(parse_adb_devices(device_proc.stdout))
    return device


def inspect_android_installation(device_serial: str) -> dict[str, object]:
    """Inspect only: no APK install, helper start, forward, connection or abandon."""
    if not device_serial or any(char.isspace() for char in device_serial):
        raise AndroidRemoteBootstrapError("adb_device_serial_invalid", "Installation inspection requires an exact device serial")
    token = None
    if _connection_budget.get() is None:
        token = _connection_budget.set(ConnectionBudget(int(DEFAULT_DAEMON_REQUEST_TIMEOUT_S * 1000)))
    try:
        adb_path = resolve_adb_path()
        device = _select_android_device(adb_path, device_serial)
        arch, abi = detect_device_arch(adb_path, device.serial)
        package, apk = select_android_package(arch)
        result = AndroidBootstrapResult(adb_path, device.serial, package, "", abi, "127.0.0.1", 0,
            DEFAULT_ANDROID_REMOTE_PORT, str(apk), "")
        _read_android_helper_apk(result)
        return {"device_serial": result.device_serial, "package_name": result.package_name,
            "apk_sha256": result.apk_sha256, **_inspect_android_install_state(result)}
    finally:
        if token is not None:
            _connection_budget.reset(token)


def bootstrap_android_remote(*, remote_port: int = DEFAULT_ANDROID_REMOTE_PORT, options: Optional[AndroidBootstrapOptions] = None) -> AndroidBootstrapResult:
    token = None
    if _connection_budget.get() is None:
        token = _connection_budget.set(ConnectionBudget(DEFAULT_ANDROID_TIMEOUT_MS))
    try:
        return _bootstrap_android_remote(remote_port=remote_port, options=options)
    finally:
        if token is not None:
            _connection_budget.reset(token)


def _bootstrap_android_remote(
    *,
    remote_port: int = DEFAULT_ANDROID_REMOTE_PORT,
    options: Optional[AndroidBootstrapOptions] = None,
) -> AndroidBootstrapResult:
    opts = options or AndroidBootstrapOptions()
    adb_path = resolve_adb_path()
    _run_subprocess(
        [adb_path, "start-server"], timeout_s=10.0,
        error_code="adb_server_start_failed", error_message="Failed to start adb server",
    )
    device = _select_android_device(adb_path, opts.device_serial)
    arch, abi = detect_device_arch(adb_path, device.serial)
    running = {helper: _package_pids(adb_path, device.serial, helper) for helper in _PACKAGE_MAP.values()}
    borrowed = any(running.values())
    package_name = next((helper for helper, pids in running.items() if pids), _PACKAGE_MAP[arch])
    apk_path = ""
    if not borrowed:
        package_name, apk_path = select_android_package(arch)
    activity_name = f"{package_name}.Loader"
    activity_component = f"{package_name}/.Loader"
    local_port = allocate_local_port(opts.local_port)
    forward_spec = f"tcp:{local_port}"
    result = AndroidBootstrapResult(
        adb_path=adb_path,
        device_serial=device.serial,
        package_name=package_name,
        activity_name=activity_name,
        abi=abi,
        host="127.0.0.1",
        port=local_port,
        remote_port=int(remote_port),
        apk_path=str(apk_path),
        forward_spec=forward_spec,
        expected_version=opts.expected_version,
    )
    if opts.progress: opts.progress("checking")
    return _prepare_android_service(result, opts, borrowed, activity_component)


def _prepare_android_service(result: AndroidBootstrapResult, opts: AndroidBootstrapOptions, borrowed: bool, activity_component: str) -> AndroidBootstrapResult:
    try:
        return _prepare_android_service_steps(result, opts, borrowed, activity_component)
    except BaseException as exc:
        token = _connection_budget.set(None)
        try:
            errors = cleanup_android_remote(result)
        finally:
            _connection_budget.reset(token)
        if isinstance(exc, AndroidRemoteBootstrapError):
            exc.details.setdefault("remote", {"stage": result.stage, "code": exc.code, "device_serial": result.device_serial})
            exc.details["installation"] = {"installed_apk": result.installed_apk, "uninstalled_existing": result.uninstalled_existing, "install_mode": result.install_mode}
        if errors:
            if isinstance(exc, AndroidRemoteBootstrapError):
                exc.details["cleanup_errors"] = errors
            else:
                raise AndroidRemoteBootstrapError("android_bootstrap_failed", str(exc), details={"cleanup_errors": errors}) from exc
        raise


def _start_android_helper(result: AndroidBootstrapResult, activity_component: str, opts: AndroidBootstrapOptions) -> None:
    adb_path, package_name = result.adb_path, result.package_name
    device = AdbDevice(serial=result.device_serial, state="device", detail="")
    budget = _connection_budget.get()
    deadline = budget.deadline if budget else time.monotonic() + DEFAULT_ANDROID_TIMEOUT_MS / 1000
    result.stage = "starting"
    if opts.progress: opts.progress("starting")
    launch_error: AndroidRemoteBootstrapError | None = None
    try:
        _adb_shell(
            adb_path,
            device.serial,
            "am",
            "start",
            "-W",
            "-n",
            activity_component,
            '-e',
            'renderdoccmd',
            'remoteserver',
            timeout_s=_remaining(max(0.001, deadline - time.monotonic())),
            error_code="android_remote_launch_failed",
            error_message="Failed to launch RenderDocCmd activity",
        )
    except AndroidRemoteBootstrapError as exc:
        launch_error = exc
    finally:
        token = _connection_budget.set(None)
        try:
            result.owned_pids = _package_pids(adb_path, device.serial, package_name)
            result.started_activity = bool(result.owned_pids)
        finally:
            _connection_budget.reset(token)

    if launch_error and not result.started_activity:
        raise launch_error
    while not result.started_activity:
        _remaining(1.0)
        if time.monotonic() >= deadline:
            raise AndroidRemoteBootstrapError("android_remote_launch_failed", "Device service did not start before the connection deadline")
        result.owned_pids = _package_pids(adb_path, device.serial, package_name)
        result.started_activity = bool(result.owned_pids)
        if not result.started_activity:
            time.sleep(min(1.0, _remaining(max(0.001, deadline - time.monotonic()))))

    result.cleanup_actions.append("activity-started")



def _prepare_android_service_steps(result: AndroidBootstrapResult, opts: AndroidBootstrapOptions, borrowed: bool, activity_component: str) -> AndroidBootstrapResult:
    adb_path, package_name = result.adb_path, result.package_name
    device = AdbDevice(serial=result.device_serial, state="device", detail="")
    remote_port, forward_spec = result.remote_port, result.forward_spec
    existing_socket_ports = _list_renderdoc_socket_ports(adb_path, device.serial)

    if not borrowed:
        if not result.installed_apk:
            _ensure_android_helper_installed(result, opts)

        if opts.push_config and result.installed_apk:
            _ensure_renderdoc_conf(result)


        _start_android_helper(result, activity_component, opts)

    socket_deadline = time.monotonic() + _remaining(15.0)
    ports = _list_renderdoc_socket_ports(adb_path, device.serial)
    while not ports and time.monotonic() < socket_deadline:
        time.sleep(min(0.25, _remaining(0.25)))
        ports = _list_renderdoc_socket_ports(adb_path, device.serial)
    remote_socket_port = _select_remote_socket_port(
        int(remote_port),
        existing_socket_ports,
        ports,
    )
    result.remote_port = int(remote_socket_port)

    # Join this bounded mutation before observing cancellation, so an acquired
    # mapping is recorded and can be rolled back by the transaction above.
    timeout_s = _remaining(10.0)
    token = _connection_budget.set(None)
    try:
        _run_subprocess(
            _adb_base_cmd(adb_path, device.serial)
            + ["forward", "--no-rebind", forward_spec, f"localabstract:{_REMOTE_SOCKET_TEMPLATE.format(port=int(remote_socket_port))}"],
            timeout_s=timeout_s,
            error_code="adb_forward_failed",
            error_message="Failed to establish adb forward for RenderDoc remote socket",
        )
        result.created_forward = True
    finally:
        _connection_budget.reset(token)
    _remaining(1.0)
    result.cleanup_actions.append("adb-forward")
    _observe_installed_apk(result)
    return result


def _adb_server_endpoint() -> tuple[str, int]:
    """Resolve the server exactly as an adb client without explicit -H/-P/-L."""
    spec = os.environ.get("ADB_SERVER_SOCKET")
    if spec is None:
        address = os.environ.get("ANDROID_ADB_SERVER_ADDRESS")
        port = os.environ.get("ANDROID_ADB_SERVER_PORT") or "5037"
        if not re.fullmatch(r"[+]?[0-9]+", port) or not 1 <= int(port) <= 65535:
            raise AndroidRemoteBootstrapError("adb_forward_cleanup_unconfirmed",
                "ADB forward cleanup unconfirmed: invalid ANDROID_ADB_SERVER_PORT")
        spec = f"tcp:{address}:{port}" if address is not None else f"tcp:{port}"
    try:
        if not spec.startswith("tcp:"):
            raise ValueError("only TCP ADB server endpoints are supported")
        address = spec[4:]
        if re.fullmatch(r"[+-]?\d+", address):
            host, port = "localhost", int(address)
        elif address.startswith("["):
            match = re.fullmatch(r"\[([^\[\]]+)\]:(\d+)", address)
            if match is None:
                raise ValueError("invalid bracketed TCP server endpoint")
            host, port = match[1], int(match[2])
            socket.inet_pton(socket.AF_INET6, host)
        elif address.count(":") >= 2:
            # ADB ParseNetAddress treats an unbracketed IPv6 address as a host
            # with the default local-transport port, not a host:port pair.
            socket.inet_pton(socket.AF_INET6, address)
            host, port = address, 5555
        elif ":" in address:
            host, value = address.split(":")
            if not value.isdecimal():
                raise ValueError("invalid TCP server port")
            port = int(value)
        else:
            host, port = address, 5555
        if not host or re.search(r"[\s/\x00\[\]]", host) or not 1 <= port <= 65535:
            raise ValueError("invalid TCP server endpoint")
        return host, port
    except (ValueError, OSError) as exc:
        raise AndroidRemoteBootstrapError("adb_forward_cleanup_unconfirmed",
            f"ADB forward cleanup unconfirmed: {exc}") from exc


def _list_adb_forwards_for_cleanup(endpoint: tuple[str, int]) -> list[list[str]]:
    # The CLI can return an incomplete list even with a terminal newline. The
    # server's OKAY/length/payload frame is the sole forward-list authority.
    deadline = time.monotonic() + 10.0

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("ADB forward query deadline exceeded")
        return value

    try:
        with socket.create_connection(endpoint, timeout=remaining()) as connection:
            def read_exact(length: int) -> bytes:
                data = bytearray()
                while len(data) < length:
                    connection.settimeout(remaining())
                    part = connection.recv(length - len(data))
                    if not part:
                        raise OSError("ADB forward query ended before its complete frame")
                    data.extend(part)
                remaining()
                return bytes(data)

            def read_payload() -> bytes:
                header = read_exact(4)
                if re.fullmatch(rb"[0-9a-fA-F]{4}", header) is None:
                    raise ValueError("invalid ADB forward payload length")
                # Four hexadecimal digits bound the payload to 65535 bytes.
                return read_exact(int(header, 16))

            connection.settimeout(remaining())
            connection.sendall(b"0011host:list-forward")
            status = read_exact(4)
            if status == b"FAIL":
                reason = read_payload().decode("utf-8")
                raise OSError(f"ADB server rejected forward query: {reason}")
            if status != b"OKAY":
                raise ValueError("invalid ADB forward query status")
            payload = read_payload().decode("utf-8")
        if payload and not payload.endswith("\n"):
            raise ValueError("unterminated ADB forward row")
        rows = [line.split() for line in payload.splitlines()]
        if any(len(row) != 3 for row in rows):
            raise ValueError("malformed ADB forward listing")
        return rows
    except (OSError, ValueError) as exc:
        raise AndroidRemoteBootstrapError("adb_forward_cleanup_unconfirmed",
            f"ADB forward cleanup unconfirmed: {exc}") from exc


def cleanup_android_remote(result: AndroidBootstrapResult) -> list[str]:
    errors: list[str] = []
    if result.created_forward:
        try:
            endpoint = _adb_server_endpoint()
            rows = _list_adb_forwards_for_cleanup(endpoint)
            matches = [row for row in rows if row[1] == result.forward_spec]
            expected = [result.device_serial, result.forward_spec, f"localabstract:renderdoc_{result.remote_port}"]
            if matches and matches != [expected]:
                raise AndroidRemoteBootstrapError("adb_forward_ownership_changed", "ADB forward identity changed; refusing to remove it")
            if not matches:
                result.created_forward = False
            else:
                _run_subprocess(
                [result.adb_path, "-H", f"[{endpoint[0]}]" if ":" in endpoint[0] else endpoint[0],
                 "-P", str(endpoint[1]), "-s", result.device_serial, "forward", "--remove", result.forward_spec],
                timeout_s=10.0,
                error_code="adb_forward_remove_failed",
                error_message="Failed to remove adb forward",
                )
                remaining = [row for row in _list_adb_forwards_for_cleanup(endpoint)
                             if row[1] == result.forward_spec]
                if remaining and remaining != [expected]:
                    raise AndroidRemoteBootstrapError("adb_forward_ownership_changed",
                        "ADB forward identity changed; refusing to remove it")
                if remaining:
                    raise AndroidRemoteBootstrapError("adb_forward_cleanup_unconfirmed",
                        "ADB forward cleanup unconfirmed: owned mapping remains after removal")
                result.created_forward = False
        except AndroidRemoteBootstrapError as exc:
            errors.append(exc.message)

    if result.started_activity:
        try:
            current_pids = _package_pids(result.adb_path, result.device_serial, result.package_name)
            if not current_pids:
                result.started_activity = False
            elif not result.owned_pids or current_pids != result.owned_pids:
                raise AndroidRemoteBootstrapError("android_helper_ownership_changed", "Helper process identity changed; refusing to stop it")
            if result.started_activity:
                _adb_shell(
                result.adb_path,
                result.device_serial,
                "am",
                "force-stop",
                result.package_name,
                timeout_s=10.0,
                error_code="android_remote_stop_failed",
                error_message="Failed to stop RenderDocCmd activity",
                )
                result.started_activity = False
                result.owned_pids = []
        except AndroidRemoteBootstrapError as exc:
            errors.append(exc.message)

    if result.config_local_path:
        try:
            Path(result.config_local_path).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Failed to delete local config {result.config_local_path}: {exc}")

    return errors


def retain_android_helper_ownership(result: AndroidBootstrapResult, prior: AndroidBootstrapResult) -> None:
    """Carry an owned helper across a fresh forward only while its PID identity is unchanged."""
    if (
        result.started_activity
        or not prior.started_activity
        or not prior.owned_pids
        or result.device_serial != prior.device_serial
        or result.package_name != prior.package_name
    ):
        return
    if _package_pids(result.adb_path, result.device_serial, result.package_name) == prior.owned_pids:
        result.started_activity = True
        result.owned_pids = list(prior.owned_pids)


def describe_android_remote(result: AndroidBootstrapResult) -> dict[str, object]:
    return {
        "transport": "adb_android",
        "device_serial": result.device_serial,
        "package_name": result.package_name,
        "activity_name": result.activity_name,
        "abi": result.abi,
        "apk_path": result.apk_path,
        "host": result.host,
        "port": result.port,
        "remote_port": result.remote_port,
        "forward_spec": result.forward_spec,
        "config_remote_path": result.config_remote_path,
        "installed_apk": result.installed_apk,
        "pushed_config": result.pushed_config,
        "started_activity": result.started_activity,
        "owned_pids": list(result.owned_pids),
        "created_forward": result.created_forward,
        "install_mode": result.install_mode,
        "install_reason": result.install_reason,
        "uninstalled_existing": result.uninstalled_existing,
        "cleanup_actions": list(result.cleanup_actions),
        "expected_version": result.expected_version,
        "apk_sha256": result.apk_sha256,
        "installed_apk_path": result.installed_apk_path,
        "installed_apk_sha256": result.installed_apk_sha256,
        "apk_identity_status": result.apk_identity_status,
        "apk_identity_reason": result.apk_identity_reason,
    }






