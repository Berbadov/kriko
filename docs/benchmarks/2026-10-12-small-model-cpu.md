# The recommended small model on a CPU — 2026-10-12

The reader: "gotta perfect it the 2b model. only model that could run in a
cpu". This is the run that says where it stood and what changed.

## Setup

- Model: the recommended local model (`localplane.RECOMMENDED_MODEL`), the
  registry's Q6/Q8 GGUF, 3.5 GB.
- Server: llama-cpp-python 0.3.36 (OpenAI surface), 4 CPU threads of an
  Intel Xeon @ 2.80 GHz, 8192-token server context, no GPU.
- Harness: `tools/evaluate_local_pipeline.py --contexts 4096 --openai`, the
  fixed fictional evidence (two documented problems with corroborating
  reports, a positive review carrying an instruction injection; and an
  abstention case with only positive and wrong-model evidence).

## Result

| | Problems recovered | Abstention | Injection obeyed | Evidence case | Model calls |
|---|---:|---|---|---:|---:|
| Before | 1/2 (latch only) | correct | no | 200 s | 18 |
| After | 2/2 | correct | no | 199 s | 15 |

Rows: [before](2026-10-12-small-model-cpu-before.jsonl), [after](2026-10-12-small-model-cpu-after.jsonl).
Recall doubled at the same time and fewer calls.

## What was wrong, and the fix

1. **The model's own check threw out correct findings.** Extraction picked
   exact, correct quotes ("my Aster One ran for 14 minutes … instead of the
   45 minutes it delivered when new"), then the check answered "unclear" for
   identity and support. Code now settles the two it can see: "unclear"
   passes when the quote or page title names the product (`names_subject`)
   and the claim's own words are in the quote (`worded_in`). "Wrong" and
   "unsupported" still reject, and so does the source-kind check.
2. **English was rendered into English.** Candidates are written in English;
   with an English reader every finding still took a render, a language
   check and a second verification. Skipped when the target is English.
   About 80 s of the earlier run.
3. **A server that spells the schema differently lost the constraint.**
   llama-cpp-python refuses `response_format: json_schema` by name and
   takes `json_object` with the schema; the socket now tries that spelling
   before dropping the constraint.

## Still open

- **Corroboration.** The two battery reports stay two cards with one source
  each: the small model's pair check answers "not the same failure" even
  with the claim and quotes alone. Wording proposes the pair now
  (`similar_pairs`); the model still decides, and says no.
- **Speed.** Generation runs at about 5 tokens a second here. Identity (24 s)
  and each page's extraction (20–33 s) dominate. A faster desktop CPU
  shortens every call, not the number of calls.
- Turkish and other non-English answers still go through rendering and were
  not re-measured in this run.
