# Rerun with the fixed MCP (build 2026-09-21-v3): 3 runs per condition

Answers: Haiku 5.5 (high), 2 subagents per run (MCP on / off), 100 items each.
Judges: Sonnet 5.5 (medium), 3 blind subagents per run (A-C, D-F, G-J), MCP off.
Max 10 per answer. Judge totals recomputed from components (no mismatches).
Per-run tables: `run*/SUMMARY_decoded.md`. Tool stats: `run*/tool_stats.json`.

## Mean of 3 runs

| Group | ON | OFF | ON - OFF | First evaluation (1 run) ON - OFF |
|---|---|---|---|---|
| A spelling | 8.70 | 8.33 | +0.37 | -0.20 |
| B stress | 8.77 | 7.90 | +0.87 | 0.00 |
| C inflection | 9.00 | 8.60 | +0.40 | 0.00 |
| D aspect | 8.70 | 8.03 | +0.67 | +0.20 |
| E government | 8.83 | 8.33 | +0.50 | -0.10 |
| F lexis | 8.90 | 8.57 | +0.33 | +0.20 |
| G frequency, CEFR | 8.53 | 5.17 | **+3.37** | +0.90 |
| H examples | 8.33 | 8.83 | **-0.50** | -0.75 |
| I correction | 8.93 | 8.97 | -0.03 | -0.20 |
| J C2 | 8.28 | 8.22 | +0.06 | +0.84 |
| ALL | 8.70 | 8.08 | +0.62 | +0.12 (8.62 vs 8.50) |

Per run, ALL: run1 8.71 vs 8.05, run2 8.62 vs 8.21, run3 8.76 vs 7.99. ON wins 37/25/39
items, OFF wins 8/15/12. ON is ahead in every run.

## Caveats

- Not a like-for-like comparison with the first evaluation: new answering model (Haiku), new
  answer format, and the judges now have `ground_truth_G.md`. The G jump mostly reflects
  that the judges could check ranks and levels; OFF answers on G are from memory.
- The agreed bar (>= 1 point on a group, in more than one run) is met only by G. B (+0.87) is
  consistently positive in all 3 runs but below the bar.
- One run3 MCP-on agent used Edit for typo fixes after writing; two OFF agents reported
  small typos they could not fix (left in on purpose).

## What did not improve

- H (examples): ON loses in all three runs. Causes in the answers: `find_examples` with
  `exact_form=true` on «ходил» returns masculine-only sentences (H08, all runs); very short
  Tatoeba sentences read as thin next to OFF answers; padding with the adjective
  «обязательное» (H05). The agent chose exact_form itself; the tool did not force it.
- J (C2): the earlier +0.84 is gone (+0.06). J is the control group, so no gain is expected.
- D10 («Не открывай» / «Не открой»): ON and OFF both lose points in different runs; the
  error is the model's reading of the perfective as a warning, not a tool error.
