"""Decode judge tables (Answer 1/2) into MCP-on / MCP-off scores.

Usage: python decode_scores.py JUDGMENTS_DIR KEY_FILE OUT_FILE

Totals are recomputed from the components; any judge total that disagrees is reported.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def row(block: str, name: str) -> tuple[float, float]:
    found = re.search(rf"\|\s*{name}[^|]*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|", block)
    if not found:
        raise ValueError(f"row {name!r} missing")
    return float(found.group(1)), float(found.group(2))


def main() -> None:
    judgments, key_file, out_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    key = json.loads(key_file.read_text(encoding="utf-8"))
    rows, mismatches = [], []
    for path in sorted(judgments.glob("[A-Z].md")):
        for block in re.split(r"\n(?=## )", path.read_text(encoding="utf-8")):
            head = re.match(r"## (\w\d\d)\b", block)
            if not head:
                continue
            item = head.group(1)
            parts = {
                name: row(block, name)
                for name in ("completeness", "correctness", "length", "bonus")
            }
            totals = [sum(parts[name][i] for name in parts) for i in (0, 1)]
            if list(row(block, "total")) != totals:
                mismatches.append((item, row(block, "total"), totals))
            scores = {}
            for i, label in enumerate(("Answer 1", "Answer 2")):
                scores[key[item][label]] = {name[0]: parts[name][i] for name in parts}
                scores[key[item][label]]["t"] = totals[i]
            rows.append((path.stem, item, scores))
    lines = ["# MCP on vs off: decoded scores\n", f"Judge total mismatches: {mismatches}\n"]
    lines += [
        "| Group | n | ON | OFF | wins ON | wins OFF | ties |",
        "|---|---|---|---|---|---|---|",
    ]
    for group in sorted({r[0] for r in rows}) + ["ALL"]:
        sel = [r for r in rows if group in ("ALL", r[0])]
        on = sum(r[2]["on"]["t"] for r in sel) / len(sel)
        off = sum(r[2]["off"]["t"] for r in sel) / len(sel)
        wins = sum(r[2]["on"]["t"] > r[2]["off"]["t"] for r in sel)
        losses = sum(r[2]["on"]["t"] < r[2]["off"]["t"] for r in sel)
        lines.append(
            f"| {group} | {len(sel)} | {on:.2f} | {off:.2f} | {wins} | {losses} "
            f"| {len(sel) - wins - losses} |"
        )
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
