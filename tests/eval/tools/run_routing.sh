#!/bin/bash
# Run each prompt of a routing prompts file through Claude Code (Haiku) with only the
# openrussian MCP server and no built-in tools. One transcript per prompt in OUT_DIR.
#
# Usage: run_routing.sh PROMPTS.txt OUT_DIR MCP_CONFIG.json
# Then:  cat OUT_DIR/*.jsonl > all.jsonl && python tests/eval/tools/tool_stats.py all.jsonl
set -u
prompts=$1; out=$2; config=$3
mkdir -p "$out"
grep -v '^#' "$prompts" | while IFS='|' read -r id _expected prompt; do
  claude -p "$prompt" --model haiku --mcp-config "$config" --strict-mcp-config \
    --tools "" --allowedTools "mcp__openrussian" --max-turns 10 \
    --output-format stream-json --verbose --no-session-persistence \
    > "$out/$id.jsonl" 2> "$out/$id.err" < /dev/null
done
echo done > "$out/DONE"
