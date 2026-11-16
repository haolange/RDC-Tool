from __future__ import annotations

import subprocess
import sys

import pytest

from rdc_tool.platform import host, locks, process


def _sleeper(**kwargs) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)


def test_identity_tracks_birth_and_rejects_reused_pid():
    child = _sleeper()
    try:
        identity = process.identify(child.pid)
        assert process.probe(identity) is process.Liveness.ALIVE
        assert identity.birth
        forged = process.ProcessIdentity(child.pid, identity.birth + "0")
        assert process.probe(forged) is process.Liveness.EXITED
    finally:
        child.kill()
        child.wait(timeout=10)
    assert process.probe(identity) is process.Liveness.EXITED
    assert process.kill_tree(identity) is False


def test_kill_tree_refuses_a_live_pid_without_a_birth_identity(monkeypatch):
    monkeypatch.setattr(process, 'probe', lambda identity: process.Liveness.ALIVE)
    monkeypatch.setattr(process._os, 'kill_tree', lambda pid: pytest.fail('unidentified process must not be terminated'))
    assert process.kill_tree(process.ProcessIdentity(123, '')) is False


def test_exited_child_is_exited_before_reaping():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    identity = process.identify(child.pid)
    assert process.wait_exit(identity, 10)
    child.wait(timeout=10)


@pytest.mark.skipif(host.IS_WINDOWS, reason="procfs is POSIX-only")
def test_a_process_reaped_while_its_stat_is_read_is_exited(monkeypatch):
    from rdc_tool.platform import _posix

    class _ReapedDuringRead:
        def __truediv__(self, part):
            return self

        def is_file(self):
            return True

        def read_text(self, *args, **kwargs):
            raise ProcessLookupError(3, "No such process")

    monkeypatch.setattr(_posix, "_PROC", _ReapedDuringRead())
    assert process.probe(process.ProcessIdentity(4242, "linux-start-ticks:boot:1")) is process.Liveness.EXITED


def test_kill_tree_reaps_the_daemon_group():
    code = "import subprocess, sys, time; c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); print(c.pid, flush=True); time.sleep(60)"
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                              **process.popen_options(process.SpawnProfile.DAEMON))
    try:
        grandchild = process.identify(int(parent.stdout.readline()))
        daemon = process.identify(parent.pid)
        assert process.kill_tree(daemon) is True
        assert process.wait_exit(daemon, 10)
        assert process.wait_exit(grandchild, 10)
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=10)
        parent.stdout.close()


def test_held_lock_is_released_when_the_owner_process_dies(tmp_path):
    path = tmp_path / "owner.lock"
    code = ("import sys, time; from pathlib import Path; from rdc_tool.platform.locks import HeldLock; "
            "held = HeldLock.try_open(Path(sys.argv[1])); print('held' if held else 'busy', flush=True); time.sleep(60)")
    owner = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
    try:
        assert owner.stdout.readline().strip() == "held"
        assert locks.HeldLock.try_open(path) is None
        owner.kill()
        owner.wait(timeout=10)
        reacquired = locks.HeldLock.try_open(path)
        assert reacquired is not None
        reacquired.release()
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=10)
        owner.stdout.close()


def test_memory_reports_a_positive_value_or_none():
    value = process.memory_bytes()
    assert value is None or value > 0


@pytest.mark.skipif(host.IS_WINDOWS, reason="POSIX keeps no raw command line")
def test_posix_has_no_raw_command_line():
    assert process.raw_command_line() is None
