"""Check first-party identity without rewriting historical evidence or upstream code."""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    failures = []
    documents = [ROOT / 'README.md', ROOT / 'AGENTS.md', *sorted((ROOT / 'docs').glob('*.md'))]
    for file in documents:
        if file.name == 'tool-convergence-tasks.md':
            continue  # Historical command receipts; current task is appended separately.
        for number, line in enumerate(file.read_text(encoding='utf-8-sig').splitlines(), 1):
            if 'Breaking:' not in line and re.search(r'rdx-tools|`rdx`|bin/rdx|rdx_install', line, re.I):
                failures.append(f'{file.relative_to(ROOT)}:{number}: retired identity')
    for relative in ('rdx', 'bin/rdx', 'bin/rdx.cmd', 'scripts/rdx_install.ps1'):
        if (ROOT / relative).exists():
            failures.append(f'{relative}: retired entry still exists')
    for failure in failures:
        print(failure)
    print(f'[identity] {len(failures)} failures')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
