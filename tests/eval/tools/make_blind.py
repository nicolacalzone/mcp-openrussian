"""Build blinded, shuffled A/B pair files for judging, plus a key.

Usage: python make_blind.py RESULTS_DIR OUT_DIR KEY_FILE [SEED]

RESULTS_DIR holds mcp_on/ and mcp_off/ with one file per group (A.md ... J.md). Each item is

    ## ID
    **Prompt:** ...
    **Tools used:** ...        <- never shown to judges
    **Answer:** ...            <- learner-facing answer
    **Data note:** ...         <- optional one line; shown to judges

Keep KEY_FILE away from the judges.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ITEM = re.compile(
    r"^## (\w+)\s*\n\*\*Prompt:\*\*(.*?)\n\*\*Tools used:\*\*.*?\n\*\*Answer:\*\*\s*\n(.*)",
    re.S | re.M,
)


def parse(path: Path) -> dict[str, tuple[str, str]]:
    items = {}
    for block in re.split(r"\n---\s*\n", path.read_text(encoding="utf-8")):
        match = ITEM.match(block.strip() + "\n")
        if match:
            items[match.group(1)] = (match.group(2).strip(), match.group(3).strip())
    return items


def main() -> None:
    results, out, key_file = (Path(arg) for arg in sys.argv[1:4])
    random.seed(int(sys.argv[4]) if len(sys.argv) > 4 else 1)
    out.mkdir(parents=True, exist_ok=True)
    key: dict[str, dict[str, str]] = {}
    for on_file in sorted((results / "mcp_on").glob("*.md")):
        group = on_file.stem
        on, off = parse(on_file), parse(results / "mcp_off" / on_file.name)
        if on.keys() != off.keys():
            sys.exit(f"group {group}: item ids differ between conditions")
        lines = [f"# Group {group} (blind pairs)\n"]
        for item_id in sorted(on):
            first, second = random.sample(["on", "off"], 2)
            key[item_id] = {"Answer 1": first, "Answer 2": second}
            answers = {"on": on[item_id][1], "off": off[item_id][1]}
            lines.append(
                f"## {item_id}\n**Prompt:** {on[item_id][0]}\n\n"
                f"### Answer 1\n{answers[first]}\n\n### Answer 2\n{answers[second]}\n\n---\n"
            )
        (out / f"{group}.md").write_text("\n".join(lines), encoding="utf-8")
    key_file.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(key)} items blinded; key written to {key_file}")


if __name__ == "__main__":
    main()
