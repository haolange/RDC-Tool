from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts import native_source_digest


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "core.autocrlf=false", *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "native source"
    (repo / "renderdoc").mkdir(parents=True)
    (repo / "renderdoc/api.cpp").write_bytes(b"int api();\n")
    (repo / "README.md").write_bytes(b"readme\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def test_digest_is_the_documented_record_hash_of_committed_blobs(tmp_path):
    repo = _repo(tmp_path)
    expected = hashlib.sha256()
    for path, data in sorted({"README.md": b"readme\n", "renderdoc/api.cpp": b"int api();\n"}.items()):
        expected.update(path.encode() + b"\0" + hashlib.sha256(data).hexdigest().encode() + b"\n")
    result = native_source_digest.tree_digest(repo, "HEAD")
    assert result["tree_sha256"] == expected.hexdigest()
    assert result["entries"] == 2 and len(result["revision"]) == 40


def test_worktree_bytes_and_untracked_files_do_not_change_a_revision_digest(tmp_path, capsys):
    repo = _repo(tmp_path)
    committed = native_source_digest.tree_digest(repo, "HEAD")["tree_sha256"]
    (repo / "build").mkdir()
    (repo / "build/librenderdoc.so").write_bytes(b"untracked build output")
    assert native_source_digest.main([str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["tree_sha256"] == committed
    (repo / "README.md").write_bytes(b"readme\r\n")
    assert native_source_digest.main([str(repo)]) == 1
    assert "uncommitted changes" in capsys.readouterr().err
    assert native_source_digest.main([str(repo), "--revision", "HEAD"]) == 0
    assert json.loads(capsys.readouterr().out)["tree_sha256"] == committed
