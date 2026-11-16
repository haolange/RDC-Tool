#!/usr/bin/env python3
"""Digest of a native source tree: the `tree_sha256` a build receipt records.

The digest covers the committed content of one Git revision, so checkout line
endings, untracked files and build directories cannot change it:

    tree_sha256 = sha256 over every entry of `git ls-tree -r <revision>`, sorted by path:
                  "<path>\\0<sha256 of the blob bytes>\\n"   (a submodule: "<path>\\0commit:<oid>\\n")

Without --revision the digest is for HEAD, and the worktree must be clean so
that the digest names exactly what was built.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, check=True).stdout


def tree_digest(repo: Path, revision: str) -> dict[str, object]:
    commit = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
    entries = []
    for record in _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            _, kind, oid = meta.decode().split()
            entries.append((path, kind, oid))
    entries.sort(key=lambda entry: entry[0])
    blobs = [oid for _, kind, oid in entries if kind == "blob"]
    stream = _git(repo, "cat-file", "--batch", stdin="".join(f"{oid}\n" for oid in blobs).encode())
    blob_sha256: dict[str, str] = {}
    at = 0
    for oid in blobs:
        header_end = stream.index(b"\n", at)
        size = int(stream[at:header_end].split()[2])
        blob_sha256[oid] = hashlib.sha256(stream[header_end + 1:header_end + 1 + size]).hexdigest()
        at = header_end + 1 + size + 1
    digest = hashlib.sha256()
    for path, kind, oid in entries:
        digest.update(path + b"\0" + (blob_sha256[oid] if kind == "blob" else f"commit:{oid}").encode() + b"\n")
    return {"revision": commit, "entries": len(entries), "tree_sha256": digest.hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute the source tree digest a native build receipt records")
    parser.add_argument("repository", help="Git checkout of the native source")
    parser.add_argument("--revision", default="", help="Commit to digest (default: HEAD of a clean worktree)")
    args = parser.parse_args(argv)
    repo = Path(args.repository).resolve()
    try:
        if not args.revision and _git(repo, "status", "--porcelain", "--untracked-files=no"):
            print("[digest] worktree has uncommitted changes; commit them or pass --revision", file=sys.stderr)
            return 1
        print(json.dumps(tree_digest(repo, args.revision or "HEAD"), indent=2))
    except subprocess.CalledProcessError as exc:
        print(f"[digest] git failed: {exc.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
