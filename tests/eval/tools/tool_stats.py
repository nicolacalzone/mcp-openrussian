"""Count MCP tool calls and empty or failed results in a subagent transcript (JSONL).

Usage: python tool_stats.py TRANSCRIPT.jsonl > tool_stats.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict


def main() -> None:
    calls: dict[str, str] = {}
    stats = defaultdict(lambda: {"calls": 0, "empty": 0, "errors": 0, "result_chars": 0})
    for line in open(sys.argv[1], encoding="utf-8"):
        content = json.loads(line).get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use" and block["name"].startswith("mcp__"):
                calls[block["id"]] = block["name"].split("__")[-1]
                stats[calls[block["id"]]]["calls"] += 1
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                tool = calls[block["tool_use_id"]]
                body = block.get("content")
                text = (
                    body
                    if isinstance(body, str)
                    else "".join(part.get("text", "") for part in body or [])
                )
                stats[tool]["result_chars"] += len(text)
                if block.get("is_error"):
                    stats[tool]["errors"] += 1
                if '"found":false' in text or '"count":0' in text or '"examples":[]' in text:
                    stats[tool]["empty"] += 1
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
