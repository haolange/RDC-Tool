from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(path for path in (ROOT / "scripts").iterdir() if path.is_file())
FORBIDDEN_SNIPPETS = ("Desktop", "platform-tools\\adb.exe", "e38b8019")


def test_every_script_is_documented_in_the_scripts_readme() -> None:
    readme = (ROOT / "scripts" / "README.md").read_text(encoding="utf-8-sig")
    undocumented = [path.name for path in SCRIPTS if path.name != "README.md" and f"`{path.name}`" not in readme]
    assert not undocumented


def test_scripts_do_not_embed_machine_local_defaults() -> None:
    for path in SCRIPTS:
        text = path.read_text(encoding="utf-8-sig")
        lower_text = text.lower()
        assert "path.home()" not in text, path.name
        for snippet in FORBIDDEN_SNIPPETS:
            assert snippet not in text, f"{path.name}: {snippet}"
        assert "c:\\users\\" not in lower_text, path.name
        assert "d:\\utility\\" not in lower_text, path.name
