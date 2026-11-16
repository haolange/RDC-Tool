from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from rdc_tool.runtime_paths import HOST_LAYOUTS
from rdc_tool.runtime_requirements import REQUIRED_DEPENDENCIES

ROOT = Path(__file__).resolve().parents[1]


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared() -> set[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return {_canonical(re.split(r"[<>=!~; \[]", requirement, maxsplit=1)[0]) for requirement in project["dependencies"]}


def _lock_entries() -> dict[str, dict]:
    entries: dict[str, dict] = {}
    current = None
    for line in (ROOT / "scripts/runtime-dependencies.lock").read_text(encoding="utf-8").splitlines():
        pinned = re.match(r"^([A-Za-z0-9_.-]+)==([^ \\;]+)", line)
        if pinned:
            current = entries.setdefault(_canonical(pinned.group(1)), {"version": pinned.group(2), "hashes": 0, "via": []})
        elif current is not None and line.strip().startswith("--hash=sha256:"):
            current["hashes"] += 1
        elif current is not None and line.strip().startswith("#"):
            current["via"].append(line.strip())
    return entries


def test_doctor_checks_exactly_the_declared_dependencies():
    assert {_canonical(name) for name, _ in REQUIRED_DEPENDENCIES} == _declared()


def test_lock_pins_every_package_with_hashes_and_its_roots_are_the_declared_dependencies():
    entries = _lock_entries()
    assert entries
    assert all(entry["hashes"] for entry in entries.values())
    roots = {name for name, entry in entries.items() if any("rdc-tool (pyproject.toml)" in via for via in entry["via"])}
    assert roots == _declared()


def test_every_host_layout_has_a_pinned_interpreter_that_provides_its_executable():
    pins = json.loads((ROOT / "scripts/python-runtimes.json").read_text(encoding="utf-8"))
    assert set(pins) == set(HOST_LAYOUTS)
    for target, pin in pins.items():
        assert re.fullmatch(r"[0-9a-f]{64}", pin["source_sha256"]) and pin["source_url"].startswith("https://")
        assert pin["python_version"].startswith("3.14.")
        executable = Path(HOST_LAYOUTS[target].python["executable"]).relative_to("python").as_posix()
        stdlib = Path(HOST_LAYOUTS[target].python["stdlib"]).relative_to("python").as_posix()
        assert any(executable == entry or executable.startswith(entry + "/") for entry in pin["include"]), target
        assert any(stdlib == entry or stdlib.startswith(entry + "/") for entry in pin["include"]), target
