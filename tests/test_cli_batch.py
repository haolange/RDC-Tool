from __future__ import annotations
import json
import signal
from pathlib import Path
import pytest
from rdx.cli_batch import run_batch
from rdx.core.contracts import canonical_success, canonical_error

OP = "rd.event.get_action_details"

def source(tmp_path, lines):
    p = tmp_path / "batch.jsonl"
    p.write_text("\n".join(json.dumps(line) if not isinstance(line, str) else line for line in lines), encoding="utf-8")
    return str(p)

def item(event=1):
    return {"operation": OP, "args": {"session_id": "s", "event_id": event}}

def test_success_in_order(tmp_path, capsys):
    seen=[]
    def execute(op,args):
        seen.append(args["event_id"])
        return canonical_success(result_kind=op,data={"items":[]},transport="cli")
    assert run_batch(source(tmp_path,[item(1),item(2)]),execute)==0
    rows=[json.loads(s) for s in capsys.readouterr().out.splitlines()]
    assert seen==[1,2]
    assert [r["meta"]["batch"]["index"] for r in rows]==[0,1]
    assert all(r["ok"] and r["result_kind"]==OP and "schema_version" in r for r in rows)

@pytest.mark.parametrize("bad",["{bad", {"operation":"rd.capture.open_replay","args":{"capture_file_id":"f"}}, {"operation":"rd.unknown","args":{}}, {"operation":OP,"args":{"session_id":"s","event_id":1,"unknown":True}}])
def test_validation_stops_without_dispatch(tmp_path,capsys,bad):
    seen=[]
    assert run_batch(source(tmp_path,[bad,item()]),lambda *a:seen.append(a))==1
    assert not seen
    row=json.loads(capsys.readouterr().out)
    assert row["meta"]["batch"]["index"]==0 and not row["ok"]

@pytest.mark.parametrize("transport",[False,True])
def test_first_real_failure_never_retries_or_continues(tmp_path,capsys,transport):
    seen=[]
    def execute(op,args):
        seen.append(args["event_id"])
        if args["event_id"]==2:
            if transport: raise RuntimeError("pipe failed")
            return canonical_error(result_kind=op,code="unsupported",category="runtime",message="unsupported",transport="cli")
        return canonical_success(result_kind=op,data={},transport="cli")
    assert run_batch(source(tmp_path,[item(1),item(2),item(3)]),execute)==1
    assert seen==[1,2]
    rows=[json.loads(s) for s in capsys.readouterr().out.splitlines()]
    assert len(rows)==2 and rows[-1]["meta"]["batch"]=={"index":1,"operation":OP}

def test_cancel_waits_for_current_completion_and_stops(tmp_path,capsys):
    seen=[]
    def execute(op,args):
        seen.append(1)
        signal.getsignal(signal.SIGINT)(signal.SIGINT,None)
        seen.append(2)
        return canonical_success(result_kind=op,data={},transport="cli")
    old=signal.getsignal(signal.SIGINT)
    assert run_batch(source(tmp_path,[item(),item()]),execute)==130
    assert seen==[1,2] and signal.getsignal(signal.SIGINT)==old
    assert json.loads(capsys.readouterr().out)["meta"]["batch"]["cancelled"]


@pytest.mark.parametrize("code", ["context_mismatch", "owner_lease_mismatch", "unsupported"])
def test_first_identity_or_native_error_is_preserved(tmp_path, capsys, code):
    seen = []
    def execute(op, args):
        seen.append(op)
        return canonical_error(result_kind=op, code=code, category="runtime", message="denied", transport="cli")
    assert run_batch(source(tmp_path, [item(), item()]), execute) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert seen == [OP] and len(rows) == 1
    assert rows[0]["error"]["code"] == code


def test_invalid_encoding_has_a_canonical_receipt(tmp_path, capsys):
    path = tmp_path / "invalid.jsonl"
    path.write_bytes(b"\xff\xfe\xff\n")
    seen = []
    assert run_batch(str(path), lambda *args: seen.append(args)) == 1
    assert not seen
    assert json.loads(capsys.readouterr().out)["meta"]["batch"]["index"] == 0
