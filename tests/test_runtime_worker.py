from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

from rdc_tool import server
from rdc_tool.daemon import worker as daemon_worker


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _prepare_runtime_source(tmp_path: Path) -> Path:
    bin_root = tmp_path / "source" / "binaries" / "windows" / "x64"
    pymod_root = bin_root / "pymodules"
    pymod_root.mkdir(parents=True, exist_ok=True)
    files = {
        "renderdoc.dll": b"fake-runtime-dll",
        "renderdoc.json": b"{}",
        "pymodules/renderdoc.pyd": b"fake-runtime-pyd",
    }
    entries = []
    for rel, content in files.items():
        path = bin_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries.append(
            {
                "path": rel.replace("\\", "/"),
                "size": len(content),
                "sha256": _sha256(path),
            }
        )
    (bin_root / "manifest.runtime.json").write_text(
        json.dumps({"file_count": len(entries), "files": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return bin_root


def test_worker_uses_source_runtime_directly(tmp_path: Path, monkeypatch) -> None:
    source_root = _prepare_runtime_source(tmp_path)
    monkeypatch.setenv("RDC_TOOL_ROOT", str(ROOT))
    monkeypatch.setattr(daemon_worker, "binaries_root", lambda: source_root)
    monkeypatch.setattr(daemon_worker, "pymodules_dir", lambda: source_root / "pymodules")

    captured: dict[str, object] = {}

    class _FakeProcess:
        pid = 12345
        stdin = io.StringIO()
        stdout = io.StringIO('{"kind":"ready"}\n')

        def poll(self):  # type: ignore[no-untyped-def]
            return None

    def _fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        captured["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(daemon_worker.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(daemon_worker.RuntimeWorkerProcess, "_save_state", lambda self: None)

    worker = daemon_worker.RuntimeWorkerProcess(context_id="pytest-worker")
    worker._spawn()
    try:
        env = captured["env"]
        assert isinstance(env, dict)
        assert env["RDC_TOOL_RUNTIME_DLL_DIR"] == str(source_root.resolve())
        assert env["RDC_TOOL_RENDERDOC_PATH"] == str((source_root / "pymodules").resolve())
        assert env["RDC_TOOL_WORKER_SOURCE_MANIFEST"] == str((source_root / "manifest.runtime.json").resolve())
        assert env["RDC_TOOL_DAEMON_PID"] == str(os.getpid())
        if os.name == "nt":
            options = captured["kwargs"]
            assert options["creationflags"] == (daemon_worker.subprocess.CREATE_NEW_CONSOLE | daemon_worker.subprocess.CREATE_NEW_PROCESS_GROUP)
            assert not options["creationflags"] & (daemon_worker.subprocess.CREATE_NO_WINDOW | daemon_worker.subprocess.DETACHED_PROCESS)
            assert options["startupinfo"].dwFlags & daemon_worker.subprocess.STARTF_USESHOWWINDOW
            assert options["startupinfo"].wShowWindow == daemon_worker.subprocess.SW_HIDE
            assert options["stdin"] == daemon_worker.subprocess.PIPE
            assert options["stdout"] == daemon_worker.subprocess.PIPE

        worker_state = worker.snapshot()
        assert worker_state["binaries_dir"] == str(source_root.resolve())
        assert worker_state["pymodules_dir"] == str((source_root / "pymodules").resolve())
        removed_fields = {"runtime_" + "id", "cache_" + "root"}
        assert removed_fields.isdisjoint(worker_state)
    finally:
        worker._proc = None
        worker._runtime = None


def test_worker_rejects_declared_but_invalid_native_set_before_spawn(tmp_path, monkeypatch):
    import pytest
    source = _prepare_runtime_source(tmp_path)
    manifest = source / "manifest.runtime.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["native_build"] = {"source": {}, "builds": []}
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(daemon_worker, "binaries_root", lambda: source)
    monkeypatch.setattr(daemon_worker.subprocess, "Popen", lambda *a, **kw: pytest.fail("unverified runtime was spawned"))
    worker = daemon_worker.RuntimeWorkerProcess(context_id="invalid-native")
    with pytest.raises(RuntimeError, match="integrity failed before worker"):
        worker._spawn()
    assert worker._proc is None


def test_mixed_loaded_runtime_rejects_new_work_but_keeps_cleanup_available(monkeypatch):
    from types import SimpleNamespace
    import rdc_tool
    from rdc_tool import runtime_identity, runtime_worker
    called = []
    async def dispatch(operation, *args, **kwargs):
        called.append(operation)
        return {"closed": True}
    async def shutdown(**kwargs):
        called.append("shutdown")
    monkeypatch.setattr(rdc_tool, "server", SimpleNamespace(dispatch_operation=dispatch, runtime_shutdown=shutdown))
    monkeypatch.setattr(runtime_identity, "loaded_runtime_identity", lambda *args: {"status": "mismatch"})
    requests = [
        {"id": "query", "method": "exec", "params": {"operation": "rd.texture.get_pixel_history"}},
        {"id": "clear", "method": "clear_context"},
        {"id": "stop", "method": "shutdown"},
    ]
    monkeypatch.setattr(runtime_worker.sys, "stdin", io.StringIO("\n".join(json.dumps(item) for item in requests)))
    outputs = []
    monkeypatch.setattr(runtime_worker, "_emit", outputs.append)
    assert runtime_worker.main(["--context-id", "mixed-runtime"]) == 0
    assert outputs[1]["ok"] is False
    assert "configured runtime" in outputs[1]["error"]["message"]
    assert called == ["rd.core.shutdown", "shutdown"]


def test_worker_keeps_loop_and_native_thread_across_requests_and_shutdown(monkeypatch):
    import asyncio
    import threading
    import time
    from types import SimpleNamespace
    import rdc_tool
    from rdc_tool import runtime_worker
    monkeypatch.setenv("RDC_TOOL_CONTEXT_ID", "default")
    loops=[]
    native_threads=[]
    def native():
        native_threads.append(threading.get_ident())
        time.sleep(0.002)
    async def dispatch(*args, **kwargs):
        loops.append(id(asyncio.get_running_loop()))
        await asyncio.gather(asyncio.to_thread(native), asyncio.to_thread(native))
        return {"success": True}
    async def shutdown(**kwargs):
        loops.append(id(asyncio.get_running_loop()))
        await asyncio.to_thread(native)
    monkeypatch.setattr(rdc_tool, "server", SimpleNamespace(dispatch_operation=dispatch, runtime_shutdown=shutdown))
    requests=[{"id":str(i),"method":method,"params":{"operation":"rd.test"}} for i,method in enumerate(["exec","exec","shutdown"])]
    monkeypatch.setattr(runtime_worker.sys,"stdin",io.StringIO("\n".join(json.dumps(x) for x in requests)))
    outputs=[]
    monkeypatch.setattr(runtime_worker,"_emit",outputs.append)
    assert runtime_worker.main(["--context-id","thread-test"]) == 0
    assert len(loops) == 3 and len(set(loops)) == 1
    assert len(native_threads) == 5 and len(set(native_threads)) == 1
    assert outputs[-1]["result"] == {"stopped": True}


def test_worker_eof_shuts_down_before_thread_executor_closes(monkeypatch):
    from types import SimpleNamespace
    import rdc_tool
    from rdc_tool import runtime_worker
    monkeypatch.setenv("RDC_TOOL_CONTEXT_ID", "default")
    closed=[]
    async def shutdown(**kwargs): closed.append(kwargs)
    monkeypatch.setattr(rdc_tool,"server",SimpleNamespace(runtime_shutdown=shutdown))
    monkeypatch.setattr(runtime_worker.sys,"stdin",io.StringIO(""))
    monkeypatch.setattr(runtime_worker,"_emit",lambda result: None)
    assert runtime_worker.main(["--context-id","eof-test"]) == 0
    assert closed == [{"clear_context_state":False}]


def test_request_does_not_implicitly_spawn_a_missing_worker(monkeypatch):
    import pytest
    worker = daemon_worker.RuntimeWorkerProcess(context_id="owned-context")
    monkeypatch.setattr(worker, "ensure_started", lambda: pytest.fail("request must not replace its controller"))
    with pytest.raises(RuntimeError, match="unavailable"):
        worker.request("exec", {"operation": "rd.export.texture"})


def test_worker_shutdown_uses_real_facade_and_preserves_daemon_context(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import rdc_tool
    from rdc_tool import runtime_worker
    calls, outputs = [], []
    monkeypatch.setenv("RDC_TOOL_CONTEXT_ID", "default")
    async def shutdown(*, clear_context_state: bool = True):
        calls.append(clear_context_state)
    monkeypatch.setattr(server, "_runtime_module", lambda: SimpleNamespace(runtime_shutdown=shutdown))
    monkeypatch.setattr(rdc_tool, "server", server)
    monkeypatch.setattr(runtime_worker.sys, "stdin", io.StringIO('{"id":"stop","method":"shutdown"}\n'))
    monkeypatch.setattr(runtime_worker, "_emit", outputs.append)
    assert runtime_worker.main(["--context-id", "shutdown-facade"]) == 0
    assert outputs[-1] == {"id": "stop", "ok": True, "result": {"stopped": True}}
    assert calls == [False]
    asyncio.run(server.runtime_shutdown())
    assert calls == [False, True]
