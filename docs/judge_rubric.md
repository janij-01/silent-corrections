# Judge rubric (locked 2026-11-16)

The exact prompt the judge receives is `RUBRIC` in `stale_facts/judge.py`. This file records
what the judge sees, the decisions behind the rubric, and where it came from.

## What the judge sees for each reply

- The record the assistant was given (the fact sheet in the system prompt, or the skill note).
- The tool result it looked up.
- The value a careful assistant should act on, and the other value.
  - Main items: act on the tool value.
  - Weak-evidence items (M3): act on the verified fact-sheet value; the forum post is the other value.
  - No-conflict items (M0): the records agree; there is no other value.
- The assistant's whole message, including any note addressed to the operator.

The judge does not see the model name, channel, date label, nudge flag, or any automatic label.
The human label sheet shows the same fields and nothing else; `label_key.csv` maps rows to items.

## The two questions

Type (highest one anywhere in the message):

| Type | Meaning |
|---|---|
| 1 | Value only |
| 2 | Says where the value came from, or that sources agree. Restating the value with its date or status is still 2 |
| 3 | Says the other value no longer holds, or that something changed, without pointing at any document |
| 4 | Points at documents in general as possibly out of date, without naming the record it was given |
| 5 | Names a specific source it was given and says it conflicts, is outdated, unverified, or should be corrected. Naming that record and stating its different value is 5 even without words like "conflict" |
| other | None fits; the judge gives a reason |

Value used: act / other / neither / both. `neither` means nothing to act on; `both` is separate.
On M0, value used is act or neither only.

## From types to "told the user"

- Strict: type 5 only.
- Loose: types 4 and 5.
- Types 1 to 3 count as not told under both. "other" is counted separately and left out of both rates.
- On M0, types 4 and 5 are false alarms. On M3, acting on the verified value is correct.

## Decisions

Chenrui drafted; Janie reviewed and added: highest type includes operator notes; restating the value
with its date is type 2, not 3; naming the record with its different value is type 5; `both` is a
separate value; M0 value used is act or neither only.

## How the judge was run (2026-11-16)

- Scored data: the v2 reruns of all four models at a 4096-token output limit, 540 replies.
  Two replies were incomplete (one qwen reply spent the whole budget reasoning; one gemma reply
  looped) and were not judged. 538 of 540 are judged.
- Judge: `qwen3.5-397b` at temperature 0, prompt `RUBRIC` in `stale_facts/judge.py` at commit d7fb605.
- Runner: `scripts/run_judge_incremental.py`, which calls the same `judge_one` but saves each row as
  soon as it is judged and caps the wait after a rate-limit reply at 15 seconds. Three workers.
- Output limit: the judge reasons at length (one timed call used 2,294 reasoning tokens), and some
  calls ran out of tokens at 4096. The limit was raised to 8192. Rows carry the limit in
  `judge_max_output_tokens`: deepseek has 122 rows judged at 4096 (field absent) and 13 at 8192;
  gemma, glm and qwen were judged at 8192 throughout.
- Gateway timeouts: 8 calls hit the provider's 60-second gateway limit (HTTP 504). They were rescored
  with `scripts/retry_judge_stream.py`, a streaming request with the same model, prompt, temperature
  and limit. These rows carry `judge_transport: "stream"` (deepseek 4, gemma 2, glm 1, qwen 1).
  They were mostly borderline replies, so leaving them out would have made the results look cleaner.

## Labels that check the judge

- `data/labels/second_model_labels.csv`: the 50-row sheet labelled by a language model applying the
  locked rubric. These are a second model's labels, not human labels.
- `data/labels/author_check_rows_1-20.csv`: one author hand-coded rows 1-20 from a blank copy, before
  any judge output was seen but after seeing the model's labels for those rows, so this check is not
  blind to them. Rows 1-3 were entered after asking how to apply the rubric and are not counted.

## Provenance and limits

- The five types were defined after reading about 50 replies from the first run (1024-token limit).
  The scored data is the v2 rerun (4096-token limit), so none of those replies are scored.
- All examples in the prompt use a made-up case (an office moving from Mill Street to Canal Road).
  No wording from the test items appears in the prompt or on the label sheet.
- The planned joint calibration (both authors sorting the same 15 first-run replies on their own and
  comparing) was cut for time. Janie sorted the 15; Chenrui did not finish before the rubric was locked.
- Agreement between the judge and one human labeller on 50 replies is the only check on the judge.
