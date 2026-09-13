from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from rdx import server
from rdx.core.session_manager import SessionManager, SessionState, _map_graphics_api
from rdx.context_snapshot import clear_context_snapshot
from rdx.models import BackendType


class DummyRemoteServer:
    def __init__(self) -> None:
        self.shutdown_called = False

    def Ping(self) -> SimpleNamespace:
        return SimpleNamespace(OK=lambda: True, Message=lambda: "Succeeded")

    def DriverName(self) -> str:
        return "Android Vulkan"

    def RemoteSupportedReplays(self) -> list[str]:
        return ["Vulkan"]

    def ShutdownConnection(self) -> None:
        self.shutdown_called = True


class _OkStatus:
    def OK(self) -> bool:
        return True

    def Message(self) -> str:
        return "Success"


class _FreshRemoteServer:
    def __init__(self) -> None:
        self.copied: list[str] = []
        self.opened: list[str] = []

    def CopyCaptureToRemote(self, filename: str, _progress: object) -> str:
        self.copied.append(filename)
        return "/remote/copied.rdc"

    def OpenCapture(self, _proxyid: int, logfile: str, _opts: object, _progress: object) -> tuple[_OkStatus, object]:
        self.opened.append(logfile)
        return _OkStatus(), object()


class _FakeRenderDocModule:
    NoPreference = 0

    class ReplayOptions:
        pass

    def __init__(self, remote: _FreshRemoteServer) -> None:
        self.remote = remote
        self.connections: list[str] = []

    def CreateRemoteServerConnection(self, url: str) -> tuple[_OkStatus, _FreshRemoteServer]:
        self.connections.append(url)
        return _OkStatus(), self.remote


def test_remote_open_reuses_owning_connection_and_native_remote_copy(monkeypatch) -> None:
    remote = _FreshRemoteServer()
    fake_renderdoc = _FakeRenderDocModule(remote)
    monkeypatch.setitem(sys.modules, "renderdoc", fake_renderdoc)

    state = SessionState(
        session_id="sess_remote",
        backend_type=BackendType.REMOTE,
        remote_server=remote,
        remote_host="127.0.0.1",
        remote_port=64590,
        remote_transport="renderdoc",
    )

    opened_remote, remote_path, controller = SessionManager()._open_remote_capture_sync(state, "C:/captures/WhiteHair.rdc")

    assert opened_remote is remote
    assert controller is not None
    assert remote_path == "/remote/copied.rdc"
    assert fake_renderdoc.connections == []
    assert remote.copied == ["C:/captures/WhiteHair.rdc"]
    assert remote.opened == ["/remote/copied.rdc"]


class FailingExecuteStatus:
    def OK(self) -> bool:
        return False

    def Message(self) -> str:
        return "Couldn't connect to target program"


class FailingExecuteResult:
    def __init__(self) -> None:
        self.result = FailingExecuteStatus()
        self.ident = 0


class LaunchFailRemoteServer(DummyRemoteServer):
    def ExecuteAndInject(self, app: str, working_dir: str, cmdline: str, env: list[object], opts: object) -> FailingExecuteResult:
        return FailingExecuteResult()


class FakeController:
    def GetRootActions(self) -> list[SimpleNamespace]:
        return []

    def GetAPIProperties(self) -> SimpleNamespace:
        return SimpleNamespace(pipelineType="Vulkan")


class FakeSessionManager:
    def __init__(self) -> None:
        self.backend_config: dict[str, object] | None = None
        self.closed: list[str] = []
        self.controller = FakeController()
        self.controller_calls = 0

    async def create_session(self, *, backend_config: dict[str, object], replay_config: dict[str, object]) -> SimpleNamespace:
        self.backend_config = dict(backend_config)
        return SimpleNamespace(session_id="sess_demo")

    async def open_capture(self, session_id: str, path: str) -> SimpleNamespace:
        return SimpleNamespace(frame_count=2)

    async def close_session(self, session_id: str) -> None:
        self.closed.append(session_id)

    def get_controller(self, session_id: str) -> FakeController:
        self.controller_calls += 1
        return self.controller


class FakeMeshFormat:
    type = 1
    compCount = 4
    compByteWidth = 4
    compType = 1
    special = False
    bgraOrder = False
    srgbCorrected = False


class FakeMesh:
    def __init__(self, *, vertex_resource_id: object = "ResourceId::123", stride: int = 16) -> None:
        self.vertexResourceId = vertex_resource_id
        self.vertexByteOffset = 0
        self.vertexByteSize = stride * 2
        self.vertexByteStride = stride
        self.indexResourceId = "ResourceId::0"
        self.indexByteOffset = 0
        self.indexByteSize = 0
        self.indexByteStride = 0
        self.numIndices = 2
        self.topology = 3
        self.status = ""
        self.format = FakeMeshFormat()


class FakeMeshController:
    def __init__(self, mesh: FakeMesh) -> None:
        self.mesh = mesh

    def GetPostVSData(self, instance: int, view_index: int, stage: object) -> FakeMesh:
        return self.mesh

    def GetBufferData(self, resource_id: object, offset: int, size: int) -> bytes:
        return bytes.fromhex("0000803f000000400000404000008040") * 2


class FakeMeshOutput:
    def GetShader(self, stage: object) -> None:
        return None


def test_dispatch_remote_connect_returns_live_handle_and_server_info(monkeypatch) -> None:
    original_remotes = dict(server._runtime.remotes)
    original_enable_remote = server._runtime.enable_remote

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_wait_for_remote_endpoint", lambda url, timeout_ms: None)
    monkeypatch.setattr(server.server_runtime, "_create_remote_server_connection", lambda url: DummyRemoteServer())

    server._runtime.remotes.clear()
    server._runtime.enable_remote = True
    clear_context_snapshot()
    server._runtime.context_snapshots.clear()
    try:
        payload = json.loads(
            asyncio.run(server._dispatch_remote("connect", {"host": "127.0.0.1", "port": 38920, "timeout_ms": 1000}))
        )
        assert payload["success"] is True
        assert payload["detail"]["connected"] is True
        assert payload["server_info"]["capabilities"]["supported_replays"] == ["Vulkan"]
        remote_id = payload["remote_id"]
        assert server._runtime.remotes[remote_id].connected is True
    finally:
        clear_context_snapshot()
        server._runtime.context_snapshots.clear()
        server._runtime.remotes.clear()
        server._runtime.remotes.update(original_remotes)
        server._runtime.enable_remote = original_enable_remote


def test_dispatch_remote_connect_failure_does_not_allocate_remote_id(monkeypatch) -> None:
    original_remotes = dict(server._runtime.remotes)
    original_enable_remote = server._runtime.enable_remote

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_wait_for_remote_endpoint", lambda url, timeout_ms: None)

    def _boom(url: str) -> DummyRemoteServer:
        raise RuntimeError("boom")

    monkeypatch.setattr(server.server_runtime, "_create_remote_server_connection", _boom)

    server._runtime.remotes.clear()
    server._runtime.enable_remote = True
    try:
        payload = json.loads(
            asyncio.run(server._dispatch_remote("connect", {"host": "127.0.0.1", "port": 38920, "timeout_ms": 1000}))
        )
        assert payload["success"] is False
        assert "remote_id" not in payload
        assert server._runtime.remotes == {}
    finally:
        server._runtime.remotes.clear()
        server._runtime.remotes.update(original_remotes)
        server._runtime.enable_remote = original_enable_remote


def test_dispatch_remote_connect_allows_omitting_host_for_adb_android(monkeypatch) -> None:
    original_remotes = dict(server._runtime.remotes)
    original_enable_remote = server._runtime.enable_remote

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_wait_for_remote_endpoint", lambda url, timeout_ms: None)
    monkeypatch.setattr(server.server_runtime, "_create_remote_server_connection", lambda url: DummyRemoteServer())
    monkeypatch.setattr(
        server.server_runtime,
        "bootstrap_android_remote",
        lambda remote_port, options: SimpleNamespace(host="127.0.0.1", port=39920, serial="e38b8019"),
    )
    monkeypatch.setattr(
        server.server_runtime,
        "describe_android_remote",
        lambda result: {"serial": "e38b8019", "endpoint": f"{result.host}:{result.port}"},
    )

    server._runtime.remotes.clear()
    server._runtime.enable_remote = True
    clear_context_snapshot()
    server._runtime.context_snapshots.clear()
    try:
        payload = json.loads(
            asyncio.run(
                server._dispatch_remote(
                    "connect",
                    {
                        "options": {
                            "transport": "adb_android",
                            "device_serial": "e38b8019",
                        },
                        "timeout_ms": 1000,
                    },
                )
            )
        )
        assert payload["success"] is True
        assert payload["detail"]["transport"] == "adb_android"
        assert payload["detail"]["endpoint"] == "127.0.0.1:39920"
        remote_id = payload["remote_id"]
        assert server._runtime.remotes[remote_id].requested_host == "127.0.0.1"
    finally:
        clear_context_snapshot()
        server._runtime.context_snapshots.clear()
        server._runtime.remotes.clear()
        server._runtime.remotes.update(original_remotes)
        server._runtime.enable_remote = original_enable_remote


def test_dispatch_capture_open_replay_keeps_live_remote_handle(monkeypatch) -> None:
    original_session_manager = server.server_runtime._session_manager
    original_captures = dict(server._runtime.captures)
    original_replays = dict(server._runtime.replays)
    original_remotes = dict(server._runtime.remotes)
    original_session_owned = dict(server._runtime.session_owned_remotes)
    original_consumed = dict(server._runtime.consumed_remotes)
    fake_manager = FakeSessionManager()

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(
        server.server_runtime,
        "_get_controller",
        lambda session_id: (_ for _ in ()).throw(AssertionError("_dispatch_capture.open_replay should use SessionManager.get_controller directly")),
    )

    server.server_runtime._session_manager = fake_manager
    server._runtime.captures = {
        "capf_demo": server.CaptureFileHandle(capture_file_id="capf_demo", file_path="capture.rdc", read_only=True)
    }
    server._runtime.replays = {}
    server._runtime.remotes = {
        "remote_demo": server.RemoteHandle(
            remote_id="remote_demo",
            host="127.0.0.1",
            port=38960,
            connected=True,
            transport="adb_android",
            remote_server=DummyRemoteServer(),
        )
    }
    server._runtime.session_owned_remotes = {}
    server._runtime.consumed_remotes = {}
    clear_context_snapshot()
    server._runtime.context_snapshots.clear()

    try:
        payload = json.loads(
            asyncio.run(
                server._dispatch_capture(
                    "open_replay",
                    {"capture_file_id": "capf_demo", "options": {"remote_id": "remote_demo"}},
                )
            )
        )
        assert payload["success"] is True
        assert fake_manager.backend_config is not None
        assert fake_manager.backend_config["type"] == "remote"
        assert fake_manager.backend_config["host"] == "127.0.0.1"
        assert fake_manager.backend_config["port"] == 38960
        assert fake_manager.backend_config["remote_id"] == "remote_demo"
        assert isinstance(fake_manager.backend_config["remote_server"], DummyRemoteServer)
        assert server._runtime.remotes["remote_demo"].transport == "adb_android"
        assert server._runtime.remotes["remote_demo"].leased_session_ids == ["sess_demo"]
        assert server._runtime.session_owned_remotes["sess_demo"].transport == "adb_android"
        assert "remote_demo" not in server._runtime.consumed_remotes

        controller_calls_after_open_replay = fake_manager.controller_calls
        context_payload = json.loads(asyncio.run(server._dispatch_session("get_context", {})))
        assert context_payload["success"] is True
        assert context_payload["runtime"]["session_id"] == "sess_demo"
        assert context_payload["remote"]["state"] == "live_handle"
        assert context_payload["remote"]["origin_remote_id"] == "remote_demo"
        assert context_payload["remote"]["active_session_ids"] == ["sess_demo"]
        assert context_payload["remote"]["context_locality"] == "strict"
        assert context_payload["remote"]["reuse_policy"] == "must_reconnect"
        assert context_payload["remote_handle_origin_context"] == "default"
        assert context_payload["remote_capability_matrix"]["endpoint"]["status"] == "verified"
        assert context_payload["remote_capability_matrix"]["fix_verification"]["status"] == "not_currently_probed"
        assert fake_manager.controller_calls == controller_calls_after_open_replay
    finally:
        clear_context_snapshot()
        server._runtime.context_snapshots.clear()
        server.server_runtime._session_manager = original_session_manager
        server._runtime.captures = original_captures
        server._runtime.replays = original_replays
        server._runtime.remotes = original_remotes
        server._runtime.session_owned_remotes = original_session_owned
        server._runtime.consumed_remotes = original_consumed


def test_remote_handle_reuse_across_contexts_fails(monkeypatch) -> None:
    original_remotes = dict(server._runtime.remotes)
    token = server.server_runtime._CURRENT_CONTEXT_ID.set("ctx_b")
    server._runtime.remotes = {
        "remote_demo": server.RemoteHandle(
            remote_id="remote_demo",
            host="127.0.0.1",
            port=38960,
            connected=True,
            origin_context_id="ctx_a",
            transport="adb_android",
            remote_server=DummyRemoteServer(),
        )
    }
    try:
        payload = json.loads(asyncio.run(server._dispatch_remote("ping", {"remote_id": "remote_demo"})))
        assert payload["success"] is False
        assert payload["code"] == "remote_handle_context_mismatch"
        assert payload["details"]["origin_context_id"] == "ctx_a"
        assert payload["details"]["current_context_id"] == "ctx_b"
    finally:
        server.server_runtime._CURRENT_CONTEXT_ID.reset(token)
        server._runtime.remotes = original_remotes


def test_consumed_remote_handle_reports_lifecycle_error() -> None:
    original_consumed = dict(server._runtime.consumed_remotes)
    server._runtime.consumed_remotes = {
        "remote_demo": server.ConsumedRemoteHandle(
            remote_id="remote_demo",
            endpoint="127.0.0.1:38960",
            consumed_by_session_id="sess_demo",
        )
    }
    try:
        payload = json.loads(asyncio.run(server._dispatch_remote("ping", {"remote_id": "remote_demo"})))
        assert payload["success"] is False
        assert payload["code"] == "remote_handle_consumed"
        assert payload["details"]["consumed_by_session_id"] == "sess_demo"
    finally:
        server._runtime.consumed_remotes = original_consumed


def test_session_manager_maps_numeric_graphics_api_values() -> None:
    assert _map_graphics_api(SimpleNamespace(pipelineType=3)).value == "Vulkan"


def test_dispatch_remote_launch_app_surfaces_execute_and_inject_status(monkeypatch) -> None:
    original_remotes = dict(server._runtime.remotes)
    original_enable_remote = server._runtime.enable_remote

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)

    server._runtime.remotes = {
        "remote_demo": server.RemoteHandle(
            remote_id="remote_demo",
            host="127.0.0.1",
            port=38960,
            connected=True,
            transport="adb_android",
            remote_server=LaunchFailRemoteServer(),
        )
    }
    server._runtime.enable_remote = True
    try:
        payload = json.loads(
            asyncio.run(
                server._dispatch_remote(
                    "launch_app",
                    {"remote_id": "remote_demo", "exe_path": "com.android.settings", "working_dir": "", "cmdline": "", "env": {}, "capture_options": {}},
                )
            )
        )
        assert payload["success"] is False
        assert payload["code"] == "remote_launch_failed"
        assert "Couldn't connect to target program" in payload["error_message"]
    finally:
        server._runtime.remotes = original_remotes
        server._runtime.enable_remote = original_enable_remote


def test_dispatch_mesh_post_transform_gs_returns_empty_payload_when_stage_not_bound(monkeypatch) -> None:
    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str) -> FakeMeshController:
        return FakeMeshController(FakeMesh(vertex_resource_id=None))

    async def _fake_get_output(session_id: str) -> FakeMeshOutput:
        return FakeMeshOutput()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 0)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(server.server_runtime, "_get_output", _fake_get_output)
    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(server.server_runtime, "_get_rd", lambda: SimpleNamespace(MeshDataStage=SimpleNamespace(VSOut="vs", GSOut="gs")))

    payload = json.loads(
        asyncio.run(
            server._dispatch_mesh(
                "get_post_transform_data",
                {"session_id": "sess_demo", "event_id": 314, "stage": "gs", "instance": 0, "max_vertices": 64},
            )
        )
    )

    assert payload["success"] is True
    mesh = payload["mesh_data"]
    assert mesh["stage"] == "GS"
    assert mesh["stage_bound"] is False
    assert mesh["vertex_count"] == 0


def test_dispatch_mesh_post_transform_vs_serializes_format_payload(monkeypatch) -> None:
    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str) -> FakeMeshController:
        return FakeMeshController(FakeMesh())

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 0)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_get_rd", lambda: SimpleNamespace(MeshDataStage=SimpleNamespace(VSOut="vs", GSOut="gs")))

    payload = json.loads(
        asyncio.run(
            server._dispatch_mesh(
                "get_post_transform_data",
                {"session_id": "sess_demo", "event_id": 314, "stage": "vs", "instance": 0, "view_index": 0, "max_vertices": 8},
            )
        )
    )

    assert payload["success"] is True
    mesh = payload["mesh_data"]
    assert mesh["vertex_count"] == 2
    assert mesh["mesh_format"]["format"]["compCount"] == 4
    assert mesh["mesh_format"]["format"]["compByteWidth"] == 4


def test_export_mesh_writes_real_indexed_obj_and_rejects_unsupported_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _IndexedMesh:
        vertexResourceId = "ResourceId::vertices"
        vertexByteOffset = 0
        vertexByteSize = 48
        vertexByteStride = 16
        indexResourceId = "ResourceId::indices"
        indexByteOffset = 0
        indexByteStride = 2
        numIndices = 3
        baseVertex = 0
        topology = 3
        format = FakeMeshFormat()

    class _IndexedController:
        def GetPostVSData(self, instance: int, view_index: int, stage: object) -> _IndexedMesh:
            return _IndexedMesh()

        def GetBufferData(self, resource_id: object, offset: int, size: int) -> bytes:
            if str(resource_id) == "ResourceId::vertices":
                return b"".join(
                    struct.pack("<ffff", *position)
                    for position in ((0.0, 0.0, 0.0, 1.0), (1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0))
                )
            return struct.pack("<HHH", 0, 1, 2)

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str) -> _IndexedController:
        return _IndexedController()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 17)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(
        server.server_runtime,
        "_get_rd",
        lambda: SimpleNamespace(
            MeshDataStage=SimpleNamespace(VSOut="vs"),
            CompType=SimpleNamespace(Float=1),
            Topology=SimpleNamespace(TriangleList=3, TriangleStrip=4, LineList=1, PointList=0),
        ),
    )
    monkeypatch.setattr(server.server_runtime, "_is_null_resource_id", lambda rid: str(rid) in {"", "0", "ResourceId::0"})

    output_path = tmp_path / "triangle.obj"
    payload = json.loads(
        asyncio.run(
            server._dispatch_export(
                "mesh",
                {
                    "session_id": "sess_demo",
                    "event_id": 17,
                    "output_path": str(output_path),
                    "format": "obj",
                    "space": "postvs",
                    "include_attributes": False,
                },
            )
        )
    )
    rejected_path = tmp_path / "unsupported.ply"
    rejected = json.loads(
        asyncio.run(
            server._dispatch_export(
                "mesh",
                {"session_id": "sess_demo", "output_path": str(rejected_path), "format": "ply"},
            )
        )
    )

    assert payload["success"] is True
    assert payload["vertex_count"] == 3
    assert payload["primitive_count"] == 1
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "# RDX post-VS positions, event 17",
        "v 0 0 0",
        "v 1 0 0",
        "v 0 1 0",
        "f 1 2 3",
    ]
    assert rejected["success"] is False
    assert rejected["code"] == "mesh_export_unsupported"
    assert not rejected_path.exists()


def test_buffer_base64_read_stays_in_memory_without_an_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    restored = []
    class _BufferController:
        def GetBuffers(self):
            return [SimpleNamespace(resourceId="ResourceId::buffer", length=3)]

        def SetFrameEvent(self, event, force):
            restored.append(event)

        def GetBufferData(self, resource_id: object, offset: int, size: int) -> bytes:
            return b"\x01\x02\x03"

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str) -> _BufferController:
        return _BufferController()

    async def _fake_resolve_resource_id(session_id: str, resource_id: object) -> str:
        return str(resource_id)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(server.server_runtime, "_resolve_resource_id", _fake_resolve_resource_id)
    monkeypatch.setattr(server.server_runtime, "_active_event", lambda _: 11)

    payload = json.loads(
        asyncio.run(
            server._dispatch_buffer(
                "get_data",
                {"session_id": "sess_demo", "buffer_id": "ResourceId::buffer", "as_base64": True},
            )
        )
    )

    assert payload == {"success": True, "byte_size": 3, "base64": "AQID", "buffer_id": "ResourceId::buffer",
                       "state": "current", "resolved_event_id": 11, "restored_event_id": 11,
                       "replay_state_restored": True, "initial_provenance": None}
    assert restored == [11, 11]
    assert "artifact_path" not in payload


def test_capture_copy_reports_actual_native_progress(monkeypatch):
    import rdx.core.session_manager as manager_module
    progress = []
    def copy(path, callback):
        callback(0.25)
        callback(0.75)
        return '/remote/capture.rdc'
    remote = SimpleNamespace(CopyCaptureToRemote=copy, OpenCapture=lambda *a: (True, object()))
    monkeypatch.setattr(manager_module, '_get_rd', lambda: SimpleNamespace(ReplayOptions=lambda: None))
    monkeypatch.setattr(manager_module, '_check_status', lambda *a, **k: None)
    state = SessionState(session_id='progress', backend_type=BackendType.REMOTE, remote_server=remote,
                         transfer_progress=lambda stage, fraction: progress.append((stage, fraction)))
    manager = object.__new__(SessionManager)
    manager._open_remote_capture_sync(state, 'capture.rdc')
    assert progress == [('capture_transfer_started', 0.0), ('capture_transfer_progress', 0.25),
                        ('capture_transfer_progress', 0.75), ('capture_transfer_done', 1.0)]


def test_remote_ping_failure_releases_acquired_connection(monkeypatch):
    runtime = server.server_runtime
    remote = DummyRemoteServer()
    remote.Ping = lambda: SimpleNamespace(OK=lambda: False, Message=lambda: 'Ping failed')
    monkeypatch.setattr(runtime, '_wait_for_remote_endpoint', lambda *a: None)
    monkeypatch.setattr(runtime, '_create_remote_server_connection', lambda *a: remote)
    with pytest.raises(Exception, match='Ping'):
        asyncio.run(runtime._connect_remote_endpoint('host', 1, 'renderdoc', {}, 1000))
    assert remote.shutdown_called


def test_borrowed_disconnect_never_shuts_down_remote_service(monkeypatch):
    runtime = server.server_runtime
    remote = DummyRemoteServer()
    remote.ShutdownServerAndConnection = lambda: pytest.fail('must never stop borrowed server')
    handle = SimpleNamespace(remote_server=remote, transport='adb_android', bootstrap_result=None)
    assert runtime._disconnect_remote_handle_sync(handle) == []
    assert remote.shutdown_called


def test_remote_connect_cancel_joins_worker_and_releases_late_connection(monkeypatch):
    import threading
    runtime = server.server_runtime
    remote = DummyRemoteServer()
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(runtime, '_wait_for_remote_endpoint', lambda *a: None)
    def create(*a):
        entered.set()
        assert release.wait(2)
        return remote
    monkeypatch.setattr(runtime, '_create_remote_server_connection', create)
    async def run():
        task = asyncio.create_task(runtime._connect_remote_endpoint('host', 1, 'renderdoc', {}, 3000))
        while not entered.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert remote.shutdown_called
    asyncio.run(run())


@pytest.mark.parametrize('message', ['Remote side of network connection is busy', 'Incompatible remote version'])
def test_native_terminal_connection_status_does_not_retry(monkeypatch, message):
    runtime = server.server_runtime
    status = SimpleNamespace(OK=lambda: False, Message=lambda: message)
    monkeypatch.setattr(runtime, '_get_rd', lambda: SimpleNamespace(CheckRemoteServerConnection=lambda *a: status))
    monkeypatch.setattr(runtime.time, 'sleep', lambda *a: pytest.fail('terminal status must not retry'))
    with pytest.raises(Exception, match=message):
        runtime._wait_for_remote_endpoint('host:1', 10000)


def test_remote_capture_keeps_runtime_connection_ownership(monkeypatch):
    manager = SessionManager()
    remote = _FreshRemoteServer()
    state = SessionState(session_id='owned', backend_type=BackendType.REMOTE, remote_server=remote, remote_server_owned=False)
    async def offload(fn, *args): return fn(*args)
    async def output(*args): pass
    monkeypatch.setattr(manager, '_offload', offload)
    monkeypatch.setattr(manager, '_create_headless_output', output)
    monkeypatch.setattr(manager, '_open_remote_capture_sync', lambda *args: (remote, '/remote/capture.rdc', object()))
    asyncio.run(manager._open_remote_capture(state, 'capture.rdc'))
    assert state.remote_server is remote
    assert state.remote_server_owned is False


@pytest.mark.parametrize('cleanup_errors', [[], ['forward identity changed']])
def test_clear_context_closes_only_owned_remotes_and_retains_failed_ownership(monkeypatch, cleanup_errors):
    runtime = server.server_runtime
    owned = SimpleNamespace(origin_context_id='clear-test')
    foreign = SimpleNamespace(origin_context_id='foreign')
    monkeypatch.setattr(runtime._runtime, 'remotes', {'owned': owned, 'foreign': foreign})
    monkeypatch.setattr(runtime, '_runtime_context_id', lambda: 'clear-test')
    monkeypatch.setattr(runtime, '_context_state', lambda *a: {'sessions': {}})
    async def noop(*a): pass
    async def offload(fn, *args): return fn(*args)
    monkeypatch.setattr(runtime, '_close_preview_binding', noop)
    monkeypatch.setattr(runtime, '_offload', offload)
    def disconnect(handle):
        assert handle is owned
        return cleanup_errors
    monkeypatch.setattr(runtime, '_disconnect_remote_handle_sync', disconnect)
    resets = []
    monkeypatch.setattr(runtime, '_reset_context_snapshot', lambda ctx: resets.append(ctx) or {'context_id': ctx})
    result = json.loads(asyncio.run(runtime._dispatch_session('clear_context', {})))
    assert result['success'] is (not cleanup_errors)
    assert runtime._runtime.remotes['foreign'] is foreign
    assert ('owned' in runtime._runtime.remotes) is bool(cleanup_errors)
    assert resets == ([] if cleanup_errors else ['clear-test'])


def test_android_transfer_does_not_break_rpc_with_native_copy_attempt(monkeypatch):
    remote = _FreshRemoteServer()
    monkeypatch.setitem(sys.modules, "renderdoc", _FakeRenderDocModule(remote))
    manager = SessionManager()
    state = SessionState(session_id="adb-copy", backend_type=BackendType.REMOTE, remote_server=remote, remote_transport="adb_android")
    monkeypatch.setattr(manager, "_copy_android_capture_with_adb", lambda *a: "/verified/capture.rdc")
    _, path, _ = manager._open_remote_capture_sync(state, "capture.rdc")
    assert path == "/verified/capture.rdc"
    assert remote.copied == []
    assert remote.opened == [path]


def test_native_copy_failure_does_not_attempt_fallback_or_open(monkeypatch):
    remote = _FreshRemoteServer()
    remote.CopyCaptureToRemote = lambda *a: ""
    monkeypatch.setitem(sys.modules, "renderdoc", _FakeRenderDocModule(remote))
    manager = SessionManager()
    monkeypatch.setattr(manager, "_copy_android_capture_with_adb", lambda *a: pytest.fail("no fallback"))
    state = SessionState(session_id="failed-copy", backend_type=BackendType.REMOTE, remote_server=remote)
    with pytest.raises(Exception, match="Capture transfer"):
        manager._open_remote_capture_sync(state, "capture.rdc")
    assert remote.opened == []


@pytest.mark.parametrize("existing,verified,success", [(True, True, True), (False, True, True), (False, False, False)])
def test_android_transfer_verifies_content_and_owns_only_new_paths(monkeypatch, tmp_path, existing, verified, success):
    import hashlib
    import rdx.core.session_manager as module
    capture=tmp_path / "tiny.rdc"
    capture.write_bytes(b"capture")
    digest=hashlib.sha256(b"capture").hexdigest()
    commands=[]
    owned=[]
    probes=0
    def run(argv, **kwargs):
        nonlocal probes
        commands.append(argv)
        if "sha256sum" in argv:
            probes += 1
            found=existing or (probes > 1 and verified)
            return SimpleNamespace(returncode=0 if found else 1, stdout=digest+" file" if found else "", stderr="" if found else "No such file or directory")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(module.subprocess,"run",run)
    state=SessionState(session_id="copy",backend_type=BackendType.REMOTE,
        remote_server=SimpleNamespace(TakeOwnershipCapture=owned.append),
        remote_device_serial="device",remote_bootstrap={"adb_path":"adb", "package_name":"org.renderdoc.renderdoccmd.arm64"})
    if success:
        assert SessionManager()._copy_android_capture_with_adb(state,str(capture)).endswith(digest+".rdc")
    else:
        with pytest.raises(RuntimeError,match="SHA256"):
            SessionManager()._copy_android_capture_with_adb(state,str(capture))
    assert bool(owned) is (not existing)
    assert sum("push" in cmd for cmd in commands) == (0 if existing else 1)
    assert any("rm" in cmd for cmd in commands) is (not success)


@pytest.mark.parametrize("error", ["device offline", "Permission denied", ""])
def test_android_transfer_refuses_unverifiable_existing_path(monkeypatch, tmp_path, error):
    import rdx.core.session_manager as module
    capture = tmp_path / "tiny.rdc"
    capture.write_bytes(b"capture")
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=1, stdout="", stderr=error)
    monkeypatch.setattr(module.subprocess, "run", run)
    state = SessionState(session_id="copy", backend_type=BackendType.REMOTE,
        remote_server=SimpleNamespace(TakeOwnershipCapture=lambda p: pytest.fail("unverified ownership")),
        remote_device_serial="device", remote_bootstrap={"adb_path": "adb", "package_name": "org.renderdoc.renderdoccmd.arm64"})
    with pytest.raises(RuntimeError, match="Cannot verify"):
        SessionManager()._copy_android_capture_with_adb(state, str(capture))
    assert len(commands) == 1 and "sha256sum" in commands[0]


def test_texture_save_keeps_native_readback_failure_message(monkeypatch):
    from rdx.core import render_service
    monkeypatch.setattr(render_service, "_get_rd", lambda: SimpleNamespace(ResultCode=SimpleNamespace(Succeeded=0)))
    result = SimpleNamespace(code=29, Message=lambda: "Couldn't readback bytes for mip 2, slice 1, sample 0")
    ok, detail = render_service._save_texture_result(result)
    assert not ok
    assert detail["status_text"] == result.Message()
    assert detail["result_code_raw"] == "29"


def test_android_failed_transfer_preserves_cleanup_failure(monkeypatch, tmp_path):
    import rdx.core.session_manager as module
    capture = tmp_path / "tiny.rdc"
    capture.write_bytes(b"capture")
    def run(argv, **kwargs):
        if "sha256sum" in argv:
            return SimpleNamespace(returncode=1, stdout="", stderr="No such file or directory")
        if "push" in argv:
            raise RuntimeError("transfer disconnected")
        return SimpleNamespace(returncode=1 if "rm" in argv else 0, stdout="", stderr="cleanup denied")
    monkeypatch.setattr(module.subprocess, "run", run)
    state = SessionState(session_id="copy", backend_type=BackendType.REMOTE,
        remote_server=SimpleNamespace(TakeOwnershipCapture=lambda p: None),
        remote_device_serial="device", remote_bootstrap={"adb_path": "adb", "package_name": "org.renderdoc.renderdoccmd.arm64"})
    with pytest.raises(RuntimeError, match="transfer disconnected; owned capture cleanup failed: cleanup denied"):
        SessionManager()._copy_android_capture_with_adb(state, str(capture))
