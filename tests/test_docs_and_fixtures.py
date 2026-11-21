from __future__ import annotations

import hashlib
import json
from pathlib import Path

from conftest import DEFAULT_FIXTURE_DEVICES
from scripts.generate_tool_reference import generate_tool_reference
from rdc_tool.runtime_catalog import catalog_payload

ROOT = Path(__file__).resolve().parents[1]


def test_tool_reference_is_generated_from_code_owned_definitions() -> None:
    doc_path = ROOT / "docs" / "tool-reference.md"
    payload = catalog_payload()
    tools = payload["tools"]
    groups = {str(tool.get("group") or "") for tool in tools}
    document = doc_path.read_text(encoding="utf-8-sig")

    assert document == generate_tool_reference()
    assert f"- 工具数：{len(tools)}" in document
    assert f"- 分组数：{len(groups)}" in document
    assert f"- Catalog fingerprint：`{payload['fingerprint']}`" in document
    for tool in tools:
        assert str(tool["name"]) in document
        assert str(tool["scope"]) in document


def test_rdc_tool_native_playbook_covers_cli_and_runtime_contracts() -> None:
    text = (ROOT / "docs" / "rdc-tool-native-agent-playbook.md").read_text(encoding="utf-8-sig")
    required_terms = [
        "rdc-tool --json doctor",
        "--daemon-context",
        "rdc-tool context status --json",
        "rdc-tool context update",
        "rdc-tool context clear",
        "capture open --file",
        "event list --format tsv",
        "pipeline show --event-id",
        "resource show --resource-id",
        "export screenshot --event-id",
        "pixel history --event-id",
        "shader source --event-id",
        "preview.display",
        "rd.remote.connect",
        "rd.remote.ping",
        "rd.capture.open_replay",
        "edit_plan",
        "captured_source_editable=false",
        "runtime_full_replace_supported=false",
        "remote_handle_consumed",
        "rd.capture.close_replay",
        "stale_session_requires_restart",
        "--max-nodes",
        "--args-file",
    ]
    for term in required_terms:
        assert term in text, term


def _fixture_manifest() -> list[dict]:
    return json.loads((ROOT / "tests" / "fixtures" / "fixtures.json").read_text(encoding="utf-8"))["fixtures"]


def test_public_rdc_fixtures_match_their_manifest() -> None:
    manifest = _fixture_manifest()
    listed = {entry["name"] for entry in manifest}
    present = {path.name for path in (ROOT / "tests" / "fixtures").glob("*.rdc")}
    assert listed == present, f"fixtures.json must list exactly the committed captures: {sorted(listed ^ present)}"
    for entry in manifest:
        path = ROOT / "tests" / "fixtures" / entry["name"]
        assert path.stat().st_size == entry["size"], entry["name"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["name"]
        assert entry["device"] in {"software-vulkan", "nvidia-vulkan"}, entry["name"]


def test_software_capture_is_not_selected_for_the_default_nvidia_device_class() -> None:
    fixture = next(entry for entry in _fixture_manifest() if entry["name"] == "vkcube_lavapipe.rdc")
    assert fixture["device"] == "software-vulkan"
    assert fixture["device"] not in DEFAULT_FIXTURE_DEVICES.split(",")


def test_fixture_policy_and_third_party_notices_cover_copied_assets() -> None:
    fixture_readme = (ROOT / "tests" / "fixtures" / "README.md").read_text(encoding="utf-8-sig")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8-sig")

    for entry in _fixture_manifest():
        assert entry["name"] in fixture_readme
        assert entry["name"] in notices
    assert "MIT" in notices
    assert "BANANASJIM" in notices
    assert "Apache-2.0" in notices
    assert "不随 `rdc-tool` 发行包分发" in notices


def test_project_license_metadata_is_apache_2() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = { text = "Apache-2.0" }' in pyproject
    assert "Apache License" in (ROOT / "LICENSE").read_text(encoding="utf-8", errors="replace")
