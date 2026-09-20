from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

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

        worker_state = worker.snapshot()
        assert worker_state["binaries_dir"] == str(source_root.resolve())
        assert worker_state["pymodules_dir"] == str((source_root / "pymodules").resolve())
        removed_fields = {"runtime_" + "id", "cache_" + "root"}
        assert removed_fields.isdisjoint(worker_state)
    finally:
        worker._proc = None
        worker._runtime = None


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
