# How to run and judge the A/B evaluation

Questions: `mcp_ab_questions.md`. Reference data for group G: `ground_truth_G.md`.
Tools: `tools/` (run with the project's Python so that `openrussian_mcp` imports).

## 1. Prepare

1. Rebuild and activate the dictionary (`openrussian-data build ...`, `activate ...`) and
   restart the MCP server, then regenerate `ground_truth_G.md`:
   `python tests/eval/tools/ground_truth_g.py data > tests/eval/ground_truth_G.md`.
2. Make a prompts-only file (no "Expected" column) for the answering agents.

## 1b. Subagent structure (required)

Everything is run by subagents (Agent tool), never by the orchestrating session itself.

**Answering phase** (model: Haiku 5.5, effort high). For each run (`run1`..`run3`) start
exactly **two subagents in parallel**, each answering all 100 items:
- **MCP-on subagent**: openrussian tools enabled.
- **MCP-off subagent**: told to use no openrussian tool, no web and no shell. Its only
  allowed tool calls are one Read of its prompts file and the Writes of its answer files.
  Check from the transcript that it made no other call.

Both get the same prompts-only file (no "Expected" column) and write
`results/<run>/mcp_on|mcp_off/<GROUP>.md`. They must not read the questions file or any
result file.

**Judging phase** (model: Sonnet 5.5, effort medium). For each run start exactly **three
subagents in parallel, all with MCP off**:
- Judge 1: groups A-C
- Judge 2: groups D-F
- Judge 3: groups G-J

Each judge scores every answer on completeness 0-3, correctness 0-3, length 0-3, plus an
optional bonus of 1 for an exceptionally good answer. Judges see only the blind files (answers
in random order, "Tools used" lines stripped), the reference column and `ground_truth_G.md`.
They never see the key or the results folders.

Total per run: 2 answering + 3 judging subagents; 3 runs = 15 subagents.

## 2. Answer format (both conditions)

Each answer file `results/<run>/mcp_on|mcp_off/<GROUP>.md` has one block per item:

    ## ID
    **Prompt:** ...
    **Tools used:** tool(args), ...      (or "none"; never shown to judges)
    **Answer:**
    The answer for a learner. Say what the tools showed only where it matters for the
    answer. Do not describe tool behaviour, failed calls or the dictionary's internals.
    **Data note:** one optional line, only if the dictionary disagrees with the norm or
    looks wrong.
    ---

Answering subagents must: not read the questions file or any result files; for MCP-off, use no
openrussian tool, web or shell. Write the answer as if to a learner, and put dictionary
conflicts in the one-line Data note. Run each condition 3 times (`run1`, `run2`, `run3`).

## 3. Measure the tools

`python tests/eval/tools/tool_stats.py <transcript.jsonl> > results/<run>/tool_stats.json`
gives calls, empty results, errors and result size per tool. Check from the transcript that
the MCP-off agent made no tool calls.

## 4. Blind and judge

1. `python tests/eval/tools/make_blind.py results/<run> results/<run>/blind <key.json> <seed>`
2. Give each judge subagent (see 1b) the blind files for its groups, `mcp_ab_questions.md` (reference column)
   and `ground_truth_G.md`. Judges must not read the results folders or the key.
   Rubric per answer: completeness 0-3, correctness 0-3, length 0-3 (penalise unrelated
   or padded text), bonus 0-1; max 10. Output tables as in `results/judgments/*.md`.
3. `python tests/eval/tools/decode_scores.py results/<run>/judgments <key.json> out.md`
   recomputes totals and reports any total the judge got wrong.
4. Average over the 3 runs. For a difference to count it should be at least about one
   point on an item group and hold in more than one run.
