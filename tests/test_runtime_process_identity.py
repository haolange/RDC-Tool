from __future__ import annotations

import asyncio
import os
import sys

import pytest

from rdc_tool import runtime_process_identity as identity
from rdc_tool import server

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("parent", ["", "invalid", "0", "-1", "999999999"])
def test_missing_or_foreign_parent_cannot_establish_continuity(monkeypatch, parent):
    monkeypatch.setenv("RDC_TOOL_DAEMON_PID", parent)
    monkeypatch.setattr(identity.os, "getppid", lambda: 31)
    monkeypatch.setattr(identity, "_process_birth", lambda pid: pytest.fail("must validate parent first"))
    result = identity.runtime_process_identity()
    assert result["status"] == "unavailable"
    assert "daemon" not in result and "worker" not in result


def test_process_birth_failure_is_unknown_not_zero_or_cached_success(monkeypatch):
    monkeypatch.setenv("RDC_TOOL_DAEMON_PID", "31")
    monkeypatch.setattr(identity.os, "getppid", lambda: 31)
    monkeypatch.setattr(identity, "_process_birth", lambda pid: (_ for _ in ()).throw(OSError("access denied")))
    result = identity.runtime_process_identity()
    assert result == {"status": "unavailable", "reason": "process_birth_unavailable", "detail": "access denied"}


def test_same_pid_with_different_birth_is_a_different_process(monkeypatch):
    monkeypatch.setenv("RDC_TOOL_DAEMON_PID", "31")
    monkeypatch.setattr(identity.os, "getppid", lambda: 31)
    monkeypatch.setattr(identity.os, "getpid", lambda: 32)
    births = {31: "birth:100", 32: "birth:200"}
    monkeypatch.setattr(identity, "_process_birth", lambda pid: births[pid])
    baseline = identity.runtime_process_identity()
    assert baseline == identity.runtime_process_identity()
    births[32] = "birth:201"
    replacement = identity.runtime_process_identity()
    assert baseline["worker"]["pid"] == replacement["worker"]["pid"]
    assert baseline["worker"]["start_generation"] != replacement["worker"]["start_generation"]
    assert baseline["daemon"] == replacement["daemon"]


@pytest.mark.skipif(sys.platform != "win32" and not sys.platform.startswith("linux"), reason="no OS birth reader")
def test_actual_os_birth_is_stable_for_live_current_and_parent_processes(monkeypatch):
    monkeypatch.setenv("RDC_TOOL_DAEMON_PID", str(os.getppid()))
    result = identity.runtime_process_identity()
    assert result["status"] == "available"
    assert result["worker"]["pid"] == os.getpid()
    assert result["daemon"]["pid"] == os.getppid()
    assert result["worker"]["start_generation"] != result["daemon"]["start_generation"]
    assert result == identity.runtime_process_identity()


def test_context_and_canonical_results_expose_only_process_births(monkeypatch):
    expected = {"status": "available", "daemon": {"pid": 31, "start_generation": "birth:100"},
                "worker": {"pid": 32, "start_generation": "birth:200"}}
    monkeypatch.setattr(identity, "runtime_process_identity", lambda: expected)
    monkeypatch.setattr(server, "runtime_process_identity", lambda: expected)
    result = asyncio.run(server.dispatch_operation("rd.session.get_context", {}, transport="test"))
    assert result["ok"] is True
    assert result["data"]["process_identity"] == expected
    assert result["meta"]["process_identity"] == expected
    failure = asyncio.run(server.dispatch_operation("rd.nonexistent", {}, transport="test"))
    assert failure["ok"] is False
    assert failure["meta"]["process_identity"] == expected
