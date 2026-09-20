"""Generate the public catalog from registered code definitions."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from rdc_tool.runtime_catalog import catalog_payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spec/tool_catalog.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    content = json.dumps(catalog_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        return 0 if args.out.is_file() and args.out.read_text(encoding="utf-8") == content else 1
    args.out.write_text(content, encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
