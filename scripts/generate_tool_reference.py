"""Generate the reader-facing tool reference from code-owned definitions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rdc_tool.runtime_catalog import catalog_payload

DEFAULT_OUTPUT = ROOT / "docs" / "tool-reference.md"


def _cell(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", "<br>").replace("|", "\\|")
    return text or "-"


def _schema_summary(schema: dict[str, Any]) -> str:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") or [])
    rows: list[str] = []
    for name, raw_spec in properties.items():
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        type_name = str(spec.get("type") or "any")
        if type_name == "array":
            items = spec.get("items") if isinstance(spec.get("items"), dict) else {}
            type_name = f"array[{items.get('type', 'any')}]"
        qualifiers = ["必填" if name in required else "可选"]
        if isinstance(spec.get("enum"), list):
            qualifiers.append("enum=" + ",".join(str(item) for item in spec["enum"]))
        if "default" in spec:
            qualifiers.append("default=" + json.dumps(spec["default"], ensure_ascii=False))
        if "minimum" in spec:
            qualifiers.append(f"min={spec['minimum']}")
        if "maximum" in spec:
            qualifiers.append(f"max={spec['maximum']}")
        rows.append(f"`{name}`: {type_name} ({'; '.join(qualifiers)})")
    return "<br>".join(rows) or "-"


def _prerequisites(tool: dict[str, Any]) -> str:
    rows: list[str] = []
    for prereq in tool.get("prerequisites") or []:
        if not isinstance(prereq, dict):
            continue
        requires = str(prereq.get("requires") or "").strip()
        via = ", ".join(str(item) for item in prereq.get("via_tools") or [])
        when = str(prereq.get("when") or "").strip()
        rows.append("; ".join(part for part in (requires, f"经由 {via}" if via else "", f"条件 {when}" if when else "") if part))
    return "<br>".join(rows) or "-"


def _group_tools(payload: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    tools = [item for item in payload.get("tools", []) if isinstance(item, dict)]
    group_names = list(dict.fromkeys(str(tool.get("group") or "Ungrouped") for tool in tools))
    return [(group, [tool for tool in tools if str(tool.get("group") or "Ungrouped") == group]) for group in group_names]


def generate_tool_reference() -> str:
    payload = catalog_payload()
    tools = [item for item in payload.get("tools", []) if isinstance(item, dict)]
    grouped = _group_tools(payload)
    lines: list[str] = [
        "# 工具参考",
        "",
        "本文件由 `rdc_tool/operation_definitions.py` 的结构化定义生成，不要手工编辑；更新时运行 `python -B scripts/generate_tool_reference.py`。",
        "",
        f"- 工具数：{len(tools)}",
        f"- 分组数：{len(grouped)}",
        f"- Catalog fingerprint：`{payload.get('fingerprint', '')}`",
        "- 标准调用：`rdc-tool call <rd.*> --format json`",
        "- Discovery：`rdc-tool tools list`、`rdc-tool tools search <query>`、`rdc-tool tools describe <rd.*>`",
        "",
        "Catalog 声明操作接受什么、可能影响什么；授权仍由嵌入宿主执行，catalog 条目本身不授予访问权。",
        "",
        "## 分组",
        "",
        "| 分组 | 工具数 |",
        "| --- | ---: |",
    ]
    for group, members in grouped:
        lines.append(f"| {_cell(group)} | {len(members)} |")

    for group, members in grouped:
        lines.extend([
            "",
            f"## {group}",
            "",
            "| 工具 | 说明 | 输入 | 结果 | 范围与影响 | 前置条件 |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for tool in members:
            effects = ", ".join(str(item) for item in tool.get("effects") or []) or "none"
            evidence = str(tool.get("evidence_kind") or "none")
            scope_effects = f"scope={tool.get('scope', 'unknown')}; effects={effects}; evidence={evidence}"
            lines.append(
                "| " + _cell(f"`{tool.get('name', '')}`")
                + " | " + _cell(tool.get("description"))
                + " | " + _cell(_schema_summary(tool.get("input_schema") or {}))
                + " | " + _cell(tool.get("returns_raw") or "标准 envelope，`data` 由该操作定义")
                + " | " + _cell(scope_effects)
                + " | " + _cell(_prerequisites(tool)) + " |"
            )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate docs/tool-reference.md from code-owned definitions")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true", help="Fail if the committed output is stale")
    args = parser.parse_args(argv)

    out_path = Path(args.out).resolve()
    rendered = generate_tool_reference()
    if args.check:
        current = out_path.read_text(encoding="utf-8-sig") if out_path.is_file() else ""
        if current != rendered:
            print(f"[tool-reference] stale: {out_path}")
            return 1
        print(f"[tool-reference] fresh: {out_path}")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8-sig")
    print(f"[tool-reference] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
