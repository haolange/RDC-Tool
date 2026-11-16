from __future__ import annotations

import os
import shutil
import stat
import tempfile
import threading
from pathlib import Path
from multiprocessing import AuthenticationError

import pytest

from rdc_tool.platform import host, ipc


@pytest.fixture
def short_runtime_dir(monkeypatch):
    # Unix socket paths are limited to ~104 bytes; pytest tmp paths can exceed it.
    root = Path(tempfile.mkdtemp(prefix="rdc-ipc-"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(root))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_authenticated_round_trip_and_rejected_key(short_runtime_dir):
    endpoint = ipc.new_endpoint()
    listener = ipc.listen(endpoint, authkey=b"right-key")
    received = []

    def serve():
        for _ in range(2):
            try:
                conn = listener.accept()
            except AuthenticationError:
                received.append("rejected")
                continue
            received.append(conn.recv())
            conn.send({"ok": True})
            conn.close()

    server = threading.Thread(target=serve)
    server.start()
    with pytest.raises(AuthenticationError):
        ipc.connect(endpoint, authkey=b"wrong-key")
    conn = ipc.connect(endpoint, authkey=b"right-key")
    conn.send({"method": "ping"})
    assert conn.recv() == {"ok": True}
    conn.close()
    server.join(10)
    listener.close()
    assert received == ["rejected", {"method": "ping"}]
    if not host.IS_WINDOWS:
        assert not os.path.exists(endpoint.address)


@pytest.mark.skipif(host.IS_WINDOWS, reason="POSIX socket directory")
def test_private_runtime_dir_rejects_shared_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    private = ipc.private_runtime_dir()
    assert stat.S_IMODE(private.lstat().st_mode) == 0o700
    private.chmod(0o755)
    with pytest.raises(PermissionError):
        ipc.private_runtime_dir()


@pytest.mark.skipif(host.IS_WINDOWS, reason="POSIX socket cleanup")
def test_discard_removes_only_sockets_in_private_dir(short_runtime_dir, tmp_path):
    import socket

    endpoint = ipc.new_endpoint()
    stale = socket.socket(socket.AF_UNIX)
    stale.bind(endpoint.address)  # an owner that died without unlinking its socket
    stale.close()
    assert os.path.exists(endpoint.address)
    ipc.discard(endpoint)
    assert not os.path.exists(endpoint.address)
    outside = tmp_path / "other.sock"
    outside.write_text("x")
    ipc.discard(ipc.Endpoint(str(outside)))
    assert outside.exists()


@pytest.mark.skipif(host.IS_WINDOWS, reason="POSIX socket path limit")
def test_overlong_socket_path_fails_instead_of_truncating(monkeypatch, tmp_path):
    deep = tmp_path / ("d" * 80)
    deep.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(deep))
    with pytest.raises(OSError, match="Unix socket limit"):
        ipc.new_endpoint()
