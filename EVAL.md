# MCP on vs off: evaluation by subagents

Protocol: [tests/eval/RUN_PROTOCOL.md](tests/eval/RUN_PROTOCOL.md).
Full results: [tests/eval/results/SUMMARY_rerun.md](tests/eval/results/SUMMARY_rerun.md)
(build 2026-09-21-v3, 3 runs per condition, 100 items each).

## Subagents

15 subagents, all started by the orchestrating session (none answered or judged directly).

| Phase | Model | Per run | Total |
|---|---|---|---|
| Answering | Haiku 5.5 (high) | 2: one MCP-on, one MCP-off, 100 items each | 6 |
| Judging | Sonnet 5.5 (medium), MCP off, blind | 3: groups A-C, D-F, G-J | 9 |

Judges scored each answer 0-10 (completeness 0-3, correctness 0-3, length 0-3, bonus 0-1).
They saw only shuffled answers with the "Tools used" lines removed. Judge totals were recomputed
from the components and no mismatch was found.

## Token usage

Figures are taken from the subagent panel (tokens as shown there).

**Answering (100 items per agent)**

| Run | MCP on | MCP off |
|---|---|---|
| Run 1 | 271.2k, 8m 37s | 82.2k, 3m 28s |
| Run 2 | 254.9k, 8m 53s | 86.2k, 3m 46s |
| Run 3 | 255.2k, 8m 48s | 85.4k, 3m 39s |
| **Mean** | **260.4k, about 8m 46s** | **84.6k, about 3m 38s** |

- MCP on costs about **3.1x the tokens** and **2.4x the time** of MCP off: roughly 2.6k vs 0.85k
  tokens per item.
- The extra tokens are tool results. Each MCP-on agent made 139-146 calls (about 90-98 of them
  `lookup_entries`) and received 250-295k characters of results, with 1-5 empty results and no
  errors.

**Judging (same for both conditions, since each judge sees both)**

| Judge | Tokens per run | Time per run |
|---|---|---|
| A-C | 51-52k | 42-53s |
| D-F | 52k | 39-46s |
| G-J | 63-65k | 65s-1m 29s |
| **Per run** | about 168k | |

Judging adds about 503k tokens over 3 runs. All 15 subagents together used about 1.54M tokens
(MCP-on answering 781k, MCP-off answering 254k, judging 503k).

## Which behaved better?

**MCP on, on quality. MCP off, on cost.**

Mean score of 3 runs (max 10):

| | ON | OFF | ON - OFF |
|---|---|---|---|
| ALL | 8.70 | 8.08 | **+0.62** |
| G frequency, CEFR | 8.53 | 5.17 | **+3.37** |
| B stress | 8.77 | 7.90 | +0.87 |
| H examples | 8.33 | 8.83 | **-0.50** |
| Other 7 groups | 8.28-9.00 | 8.22-8.97 | -0.03 to +0.67 |

- ON was ahead overall in every run (8.71 vs 8.05, 8.62 vs 8.21, 8.76 vs 7.99) and won more
  items in every run (37/25/39 against 8/15/12 for OFF).
- **The gain comes almost entirely from G.** Frequency ranks and CEFR levels are data a model
  cannot recall; the OFF agent answered from memory and scored 5.17. G is the only group that
  meets the agreed bar (at least 1 point, in more than one run).
- Without G, the gap is small: about +0.3 (unweighted mean of the other nine group means).
  Stress (B) is positive in all 3 runs but stays below the bar. Spelling, inflection, aspect,
  government and lexis are within +0.3 to +0.7. Haiku already handles them well without a
  dictionary.
- **MCP off was better on H (examples), -0.50 in all 3 runs.** `find_examples` with
  `exact_form=true` returned masculine-only sentences for «ходил», very short Tatoeba sentences
  read as thin, and one answer was padded with «обязательное». The agent chose `exact_form`
  itself.
- I (correction) is a tie (-0.03) and J (C2, control group) is a tie (+0.06), as expected.

**Verdict:** MCP on is the better setup when the question needs dictionary data (frequency, level,
and to a lesser extent stress). It costs about 3x the tokens, and for questions the model can
already answer it gives little extra. The price is worth paying for G and probably B, and not
for general language questions. The H result is a tool-usage problem to fix, not a reason to turn
the MCP off.

## Caveats

- This is not a like-for-like comparison with the first evaluation (one run, different model, old
  answer format, judges without `ground_truth_G.md`). The G jump is partly because the judges can
  now check ranks and levels.
- Differences below about 1 point per group are within run-to-run noise.
- One run3 MCP-on agent used Edit for typo fixes after writing, and two OFF agents reported
  typos they could not fix (left in).
- D10 («Не открывай» / «Не открой») cost both conditions points in different runs. The cause is
  the model reading the perfective as a warning, not the tool.
