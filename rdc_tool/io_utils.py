from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import shutil
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TextIO

from rdc_tool.core.errors import CoreError
from rdc_tool.platform.locks import LockTimeout, path_lock

STATE_LOCK_TIMEOUT_S = 10.0


class AtomicWriteError(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


@contextmanager
def state_file_lock(lock_path: Path, context: str) -> Iterator[None]:
    """Serialize a persisted state file across threads and processes."""
    with ExitStack() as stack:
        try:
            stack.enter_context(path_lock(lock_path, timeout=STATE_LOCK_TIMEOUT_S))
        except LockTimeout as exc:
            raise CoreError(
                code="state_lock_timeout",
                message=f"Timed out waiting for the state lock of context {context!r}",
                category="runtime",
                details={"context_id": context, "lock_path": str(lock_path), "waiting_for": exc.stage,
                         "elapsed_seconds": exc.elapsed, "timeout_seconds": exc.timeout,
                         "recovery_hint": "Retry after the concurrent state writer finishes; do not remove the lock file."},
            ) from exc
        yield


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_safe(value: Any, default: Callable[[Any], Any] = str) -> Any:
    """Return ``value`` as plain JSON data.

    Strings with unpaired surrogates are escaped, non-finite floats become
    explicit ``"NaN"``/``"Infinity"`` markers, and any other object is
    replaced by ``default(value)``.
    """
    if isinstance(value, str):
        text = str.__str__(value)
        try:
            text.encode("utf-8")
            return text
        except UnicodeEncodeError:
            return text.encode("utf-8", errors="backslashreplace").decode("utf-8")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if math.isfinite(value):
            return float(value)
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {str(key): json_safe(item, default) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item, default) for item in value]
    return json_safe(default(value), default)


def safe_json_text(
    payload: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
    default: Callable[[Any], Any] = str,
) -> str:
    return json.dumps(json_safe(payload, default), ensure_ascii=False, indent=indent, sort_keys=sort_keys, allow_nan=False)


def safe_stream_write(text: str, stream: TextIO) -> None:
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = str(getattr(stream, "encoding", "") or "utf-8")
        sanitized = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="strict")
        stream.write(sanitized)
    stream.flush()


def _cleanup_path(path: Path) -> None:
    try:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except Exception:
        return


def atomic_swap_path(
    temp_path: Path | str,
    final_path: Path | str,
    *,
    retries: int = 5,
    retry_delay_s: float = 0.05,
) -> None:
    temp = Path(temp_path)
    final = Path(final_path)
    backup = final.with_name(f"{final.name}.{secrets.token_hex(8)}.bak")
    last_error: BaseException | None = None
    promoted = False
    backed_up = False
    try:
        for attempt in range(retries + 1):
            try:
                if temp.is_dir() and final.exists():
                    os.replace(final, backup)
                    backed_up = True
                os.replace(temp, final)
                promoted = True
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if backed_up and not promoted:
                    try:
                        if not final.exists():
                            os.replace(backup, final)
                        backed_up = False
                    except Exception:
                        pass
                if attempt >= retries:
                    break
                time.sleep(retry_delay_s)
        if not promoted:
            details = {
                "temp_path": str(temp),
                "final_path": str(final),
                "retries": int(retries),
            }
            if last_error is not None:
                details["reason"] = str(last_error)
            raise AtomicWriteError("atomic swap failed", details=details)
    finally:
        if promoted and backup.exists():
            _cleanup_path(backup)
        if temp.exists():
            _cleanup_path(temp)


def atomic_write_text(
    path: Path | str,
    text: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
) -> Path:
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{final.name}.", suffix=".tmp", dir=str(final.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as handle:
            handle.write(text)
        atomic_swap_path(tmp_path, final)
        return final
    except Exception:
        _cleanup_path(tmp_path)
        raise


def atomic_write_json(
    path: Path | str,
    payload: Any,
    *,
    indent: int = 2,
    sort_keys: bool = False,
) -> Path:
    text = safe_json_text(payload, indent=indent, sort_keys=sort_keys)
    return atomic_write_text(path, text)


def atomic_append_jsonl(path: Path | str, entry: dict[str, Any]) -> Path:
    final = Path(path)
    existing = ""
    if final.exists():
        existing = final.read_text(encoding="utf-8")
    line = safe_json_text(entry) + "\n"
    if existing:
        text = existing if existing.endswith("\n") else existing + "\n"
        text += line
    else:
        text = line
    return atomic_write_text(final, text)
