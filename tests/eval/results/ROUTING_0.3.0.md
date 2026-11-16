# Routing and miss-handling check, version 0.3.0

Purpose: check that the changes in 0.3.0 (tool descriptions, hints on misses, comma search,
stress check in `analyze_text`) do not make a client pick the wrong tool, invent ids or answer
a miss from memory. This is a behaviour check of one model, not a quality score: nothing here
is judged 0-10.

- Client: Claude Code, `claude -p`, model Haiku 5.5, only the openrussian MCP server, no
  built-in tools, one fresh session per prompt, at most 10 turns.
- Build 2026-09-21-v3, server 0.3.0.
- Runner: `tests/eval/tools/run_routing.sh`. Prompts: `tests/eval/routing/`.
  Tool counts: `tool_stats.py`, output in `routing_0.3.0/`.
- 2 sets, 38 prompts, one run each (set 1: 18, set 2: 20).

## Pass criteria

1. No English or German query goes to `lookup_entries`.
2. No `entry_id` that did not come from the user or an earlier tool result.
3. A miss is reported to the user as "not in the dictionary", and anything not from the
   dictionary is labelled as such.
4. No tool errors.

## Result

| Criterion | Set 1 (18) | Set 2 (20) |
|---|---|---|
| 1. No non-Russian query to `lookup_entries` | pass, 13 of 13 calls Cyrillic | pass, 13 of 13 calls Cyrillic |
| 2. No invented `entry_id` | pass | pass |
| 3. Misses reported as misses (L4, L5, S5, G1 / M1, M2, G1) | 3 of 4 clean; «карова» overclaimed | 3 of 3 clean |
| 4. Tool errors | 0 | 0 |

Tool calls: set 1 had 22 (lookup 13, search 5, get 2, analyze 2), set 2 had 20 (lookup 13,
analyze 3, get 2, search 1, find_examples 1). Empty results: 7 and 3, all
expected (misses on purpose). 7 of the 38 prompts made no tool call (see problem 1).

## Findings

**Works as intended**
- Stress-marked text goes to `analyze_text` (set 1 T1, T2; set 2 T1) and the mismatches are reported:
  зво́нит, на́чала, тво́рог differ, де́нь and зеле́ный do not.
- A single stress-marked word goes to `lookup_entries` and the model uses `stress_match`
  (set 1 T3, set 2 T5: му́ка and мука́ are told apart).
- Misses: «хайп», «гаджет» and the glass-xylophone item were reported as not in the dictionary,
  with the model's own knowledge labelled as such. «кафэ» went through `analyze_text`, got the
  suggestion кафе́, and the model checked it with `lookup_entries` before answering.
- Comma search: "bread, milk, meat, cheese" in one `search_entries` call returned all four
  words (before 0.3.0 such a query returned nothing).
- A wrong id (99999999, 7777777) was reported as "no entry"; the model offered to look the word
  up instead of guessing.
- Part of speech: «день» as a verb found the imperative of деть, as the dictionary says.
- German and Russian prompts were answered in the language of the question.

**Problems seen (model behaviour, not server errors)**
1. **The model skips the dictionary.** 7 of 38 prompts got no tool call: 6 of the 10
   `search_entries`-type prompts (S1, S3 in set 1; S1, S2, S3, S5 in set 2) and one stress
   check (set 2 T2, a sentence with stress marks, judged correct from memory). One answer
   carried a wrong stress mark (set 2 S2: «ключ́» with the mark on the consonant). The
   descriptions say what each tool is for, but the client decides whether to call it.
2. **Variant stress misread (set 2 T4).** `lookup_entries("тво́рог")` returned the entry with
   `stress_match: false`. The model answered that «тво́рог» "does not match any entry, so the
   dictionary rejects it". The tool found the entry; the stress differs from the dictionary's
   and is an accepted variant. This is the caveat in the README, and the model did not carry
   it over. A tool description that says "differs from the dictionary" did not prevent it.
3. **Hint not followed in full (set 1 L4).** For «карова» the model guessed корова first, then
   said «карова» "isn't a Russian word", although the hint says a miss is not proof.
4. **`get_entry` is rarely the first call.** In 6 of 10 get-entry prompts the model used
   `lookup_entries` with `include_forms` and got the same data. Harmless.

**Not covered**
- Set 2 T1 was meant to contain a wrong stress, but every mark in it is correct (хо́дим is
  right), so it only tests that nothing is flagged wrongly. Detection is covered by set 1 T1 and
  T2 and by `tests/test_fixes.py`.
- One run per prompt and one model. A difference of one or two prompts is noise.
- The client showed `"stress_match":null`, `"hint":null` and similar in tool results, although
  the text content leaves out null fields: Claude Code reads `structuredContent`, which keeps
  them. This was already so for existing fields (`"indeclinable":null`); 0.3.0 adds three more.

## Per-prompt record

Tools in call order. "none" means the model answered without the dictionary.

### Set 1

| Id | Tools | Note |
|---|---|---|
| L1 | lookup | ok |
| L2 | lookup | ok |
| L3 | lookup | ok |
| L4 | lookup, lookup | guessed корова first; "isn't a Russian word" overclaims |
| L5 | lookup, search | miss reported, own knowledge labelled |
| S1 | none | answered from memory |
| S2 | search | ok |
| S3 | none | answered from memory |
| S4 | search | comma query, all four found |
| S5 | search, search, lookup, lookup | miss reported, own knowledge labelled |
| G1 | get_entry | "no entry" reported |
| G2 | lookup | used lookup, not get_entry |
| G3 | lookup, get_entry | id taken from lookup |
| G4 | lookup | used lookup, not get_entry |
| G5 | lookup | used lookup, not get_entry |
| T1 | analyze_text | mismatches reported |
| T2 | analyze_text | тво́рог reported as differing |
| T3 | lookup | stress_match used |

### Set 2

| Id | Tools | Note |
|---|---|---|
| M1 | analyze_text, lookup | suggestion кафе́ verified |
| M2 | lookup, find_examples | miss reported, own knowledge labelled |
| M3 | lookup | part_of_speech=verb found деть |
| M4 | lookup | answered in Russian |
| M5 | lookup | ok |
| S1 | none | answered from memory |
| S2 | none | answered from memory, one wrong stress mark |
| S3 | none | answered from memory |
| S4 | search | ok |
| S5 | none | answered from memory |
| G1 | get_entry | "no entry" reported |
| G2 | lookup | used lookup, not get_entry |
| G3 | lookup, get_entry | id taken from lookup |
| G4 | lookup | used lookup, not get_entry |
| G5 | lookup | used lookup, not get_entry |
| T1 | analyze_text | no false alarm |
| T2 | none | answered from memory; marks judged correct without the tool |
| T3 | analyze_text | typo отвечять found |
| T4 | lookup, lookup | variant stress misread (problem 2) |
| T5 | lookup, lookup | му́ка and мука́ told apart |
