"""A fake adb and Android device for the capture transfer.

It answers the exact adb command lines the transfer issues, keeps the device
files in memory, and runs the two transfers (adb push and the device-local
writer) as fake client processes polled by the no-progress loop: each poll is
one step of work, so tests can make a transfer grow, stall or be cancelled.
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
import time
from types import SimpleNamespace


def _result(code: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class _TransferClient:
    """A fake adb client process; ``communicate(timeout)`` performs one step of the transfer."""

    def __init__(self, device: "FakeAndroidDevice", argv: list[str], steps) -> None:
        self.device = device
        self.argv = argv
        self.steps = steps
        self.returncode = None
        self.killed = False

    def communicate(self, timeout=None):
        if self.killed:
            self.returncode = -9
            return "", "killed"
        try:
            next(self.steps)
        except StopIteration as finished:
            result = finished.value
            self.returncode = result.returncode
            return result.stdout, result.stderr
        time.sleep(0.005)
        raise subprocess.TimeoutExpired(self.argv, timeout)

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.device.killed.append(self.argv)


class FakeAndroidDevice:
    package = "org.renderdoc.renderdoccmd.arm64"
    private_root = "/data/user/0/" + package
    nonce = "1234567890abcdef1234567890abcdef"
    # Each poll of a "slow" transfer moves this many bytes.
    chunk = 4

    def __init__(self, monkeypatch, tmp_path, *, existing=False, verified=True, window_s=0.2):
        import rdc_tool.core.session_manager as module
        from rdc_tool.core.session_manager import SessionState
        from rdc_tool.models import BackendType
        self.capture = tmp_path / "binary capture.rdc"
        self.content = b"capture\x00\xff\xfe\r\n\x80 with more bytes"
        self.capture.write_bytes(self.content)
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.destination = f"{self.private_root}/files/rdc_tool_captures/{self.digest}.rdc"
        self.shell_dir = f"/data/local/tmp/rdc-tool-transfer-{self.nonce}"
        self.shell_source = self.shell_dir + "/source.rdc"
        self.shell_directories = set()
        self.files = {self.destination: self.content} if existing else {}
        self.commands = []
        self.size_polls = []
        self.killed = []
        self.progress = []
        self.owned = []
        self.verified = verified
        self.writer_mode = "complete"
        self.sync_mode = "complete"
        self.racing_content = None
        self.racing_directory = False
        self.new_file_created = False
        self.cleanup_error = False
        self.shell_cleanup_error = False
        self.on_growth = None
        self.state = SessionState(session_id="copy", backend_type=BackendType.REMOTE,
            remote_server=SimpleNamespace(TakeOwnershipCapture=self.owned.append),
            remote_device_serial="device", remote_bootstrap={"adb_path": "adb", "package_name": self.package,
                "config_remote_path": "/sdcard/Android/media/other/files/renderdoc.conf"},
            transfer_progress=self._progress)
        monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex=self.nonce))
        monkeypatch.setattr(module.process.subprocess, "run", self.run)
        monkeypatch.setattr(module.process.subprocess, "Popen", self.popen)
        monkeypatch.setattr(module.timeout_policy, "cooperative_no_progress_s", lambda budget_ms: window_s)

    def transfer(self):
        from rdc_tool.core.session_manager import SessionManager
        return SessionManager()._copy_android_capture_with_adb(self.state, str(self.capture))

    def _progress(self, stage, fraction):
        self.progress.append((stage, fraction))
        if self.on_growth is not None:
            self.on_growth(fraction)

    def popen(self, argv, **kwargs):
        assert argv[:3] == ["adb", "-s", "device"]
        assert kwargs["stdin"] == subprocess.DEVNULL and "input" not in kwargs
        assert kwargs["stdout"] == subprocess.PIPE and kwargs["stderr"] == subprocess.PIPE and kwargs["text"] is True
        self.commands.append(argv)
        if argv[3] == "push":
            return _TransferClient(self, argv, self._push(argv))
        tokens = shlex.split(argv[4])
        assert argv[3] == "shell" and tokens[0] == "cat"
        return _TransferClient(self, argv, self._write(tokens))

    def _push(self, argv):
        assert argv[4:] == [str(self.capture), self.shell_source]
        data = self.capture.read_bytes()
        if self.sync_mode in {"stall", "failed"}:
            self.files[self.shell_source] = data[:1]
            if self.sync_mode == "failed":
                return _result(1, stderr="device offline")
            while True:
                yield
        if self.sync_mode == "slow":
            for end in range(self.chunk, len(data), self.chunk):
                self.files[self.shell_source] = data[:end]
                yield
        self.files[self.shell_source] = data
        return _result(stdout="" if self.sync_mode == "empty_output" else "1 file pushed")

    def _write(self, tokens):
        assert tokens[:7] == ["cat", self.shell_source, "|", "run-as", self.package, "sh", "-c"]
        assert "set -C; exec 3> " + self.destination in tokens[7]
        if self.racing_directory:
            return _result(1, stderr="Is a directory")
        if self.racing_content is not None:
            self.files[self.destination] = self.racing_content
            return _result(1, stderr="File exists")
        data = self.files[self.shell_source]
        if self.writer_mode == "stall":
            self.files[self.destination] = data[:1]
            self.new_file_created = True
            while True:
                yield
        if self.writer_mode == "slow":
            for end in range(self.chunk, len(data), self.chunk):
                self.files[self.destination] = data[:end]
                yield
        self.files[self.destination] = data
        self.new_file_created = True
        if self.writer_mode == "empty":
            return _result()
        if self.writer_mode == "wrong_nonce":
            return _result(stdout="other:CREATED\nother:DONE:0\n")
        if self.writer_mode == "failed":
            return _result(1, stdout=f"{self.nonce}:CREATED\n{self.nonce}:DONE:1\n", stderr="write failed")
        return _result(stdout=f"{self.nonce}:CREATED\n{self.nonce}:DONE:0\n")

    def _size(self, path):
        self.size_polls.append(path)
        if path not in self.files:
            return _result(1, stderr=f"stat: {path}: No such file or directory")
        return _result(stdout=f"{len(self.files[path])}\n")

    def run(self, argv, **kwargs):
        assert argv[:3] == ["adb", "-s", "device"]
        assert kwargs["stdin"] == subprocess.DEVNULL and "input" not in kwargs
        assert kwargs["text"] is True  # Only diagnostics travel through host stdio.
        if argv[3:7] == ["shell", "stat", "-c", "%s"]:
            return self._size(argv[7])
        if argv[3:6] == ["shell", "run-as", self.package] and argv[6:9] == ["stat", "-c", "%s"]:
            return self._size(argv[9])
        self.commands.append(argv)
        assert argv[3] == "shell"
        assert all("/sdcard" not in arg for arg in argv)
        if argv[4] == "sha256sum":
            assert argv[5] == self.shell_source
            if self.sync_mode == "unreadable":
                return _result(1, stderr="Permission denied")
            if self.sync_mode == "missing":
                return _result(1, stderr=f"sha256sum: {self.shell_source}: No such file or directory")
            data = b"corrupt" if self.sync_mode == "mismatch" else self.files[self.shell_source]
            return _result(stdout=hashlib.sha256(data).hexdigest() + "  " + self.shell_source + "\n")
        if len(argv) == 5:
            script = argv[4]
            if script.startswith("umask"):
                assert f"umask 077; mkdir -m 700 {self.shell_dir}" in script
                self.shell_directories.add(self.shell_dir)
                if self.sync_mode == "dir_collision":
                    self.files[self.shell_dir + "/protected"] = b"keep"
                    return _result(1, stderr="File exists")
                return _result(stdout=f"{self.nonce}:SHELL_CREATED\n")
            tokens = shlex.split(script)
            assert tokens[:6] == ["rm", "-f", self.shell_source, "&&", "rmdir", self.shell_dir]
            if self.shell_cleanup_error:
                return _result(1, stderr="source cleanup denied")
            del self.files[self.shell_source]
            self.shell_directories.remove(self.shell_dir)
            return _result(stdout=f"{self.nonce}:SHELL_REMOVED\n")
        assert argv[4:6] == ["run-as", self.package]
        operation = argv[6:]
        if operation == ["pwd"]:
            return _result(stdout=self.private_root + "\n")
        if operation[0] == "sha256sum":
            path = operation[1]
            if path not in self.files:
                return _result(1, stderr=f"sha256sum: {path}: No such file or directory")
            data = self.files[path] if path != self.destination or self.verified or not self.new_file_created else b"corrupt"
            return _result(stdout=hashlib.sha256(data).hexdigest() + "  " + path + "\n")
        if operation[0] == "mkdir":
            assert operation == ["mkdir", "-p", self.private_root + "/files/rdc_tool_captures"]
            return _result()
        assert operation[:2] == ["sh", "-c"]
        script = shlex.split(operation[2])[0]
        tokens = shlex.split(script)
        assert tokens[:2] == ["rm", "-f"]
        if self.cleanup_error:
            return _result(1, stderr="cleanup denied")
        del self.files[tokens[2]]
        return _result(stdout=f"{self.nonce}:REMOVED\n")
