# Research benchmarks on the release computer

Measured on **9 October 2026**, using Kriko 1.1.0's real research adapters on Windows 11, Python 3.13.7, and an **NVIDIA GeForce RTX 3060 Laptop GPU (6 GB VRAM)**.

Each configuration attempted the first three cases from the shipped `kriko-fixed` set, version `2026.10.1`: Dyson V15 Detect, PlayStation 5 disc edition, and Samsung Bespoke refrigerator with ice maker. These are three different research tasks, with one attempt per task, rather than three repetitions of the same prompt. Catalogs and user knowledge were not modified.

## Results

| Requested model | Actual model / route | Completed cases | Median completed-case time | Median reported tokens | Grounded risk findings, total |
|---|---|---:|---:|---:|---:|
| Haiku 5.5 | `claude-haiku-5-5` through Claude Code; OpenRouter retry below | 0/3 | — | — | — |
| Gemma local agent | `gemma3n:e2b` through Ollama and Kriko's local agent | 3/3 | 24.7 s | 5,629 | 0 |
| GPT 6 Luna | `opencode-go/gpt-6-luna` through OpenCode; OpenRouter retry below | 0/3 | — | — | — |
| GLM 5.3, Mistral provided | `zai-glm-5-3` through Mistral Conversations | 3/3 | 63.0 s | 11,618 | 17 |

A completed case returned parseable output; it does not necessarily contain usable risk findings. **Grounded** means a finding's quote passed the source-text check. It is not an independent verification that the product has that fault, and this report does not present the test set's automatic correctness scores as model accuracy.

Gemma produced 17 unsupported risk candidates across the three cases. The source checks rejected all of them. Its locally generated replies changed source URLs or quote text, so no risk finding survived. Some specification fields remained; the finding count measures risks only. GLM returned 17 grounded risks and one rejected candidate. **GLM's dollar cost is unknown** because this installation's price catalog has no entry for this newly served model; missing cost data is not zero cost.

## Account and provider failures

- **Haiku / Claude Code:** all three attempts stopped with `error_max_budget_usd` at the $0.20 requested ceiling. The error also contained `unrecognized_model` for `claude-haiku-5-5`. These were not completed Haiku answers.
- **Luna / OpenCode Go:** all three attempts were rejected because the saved account requires an active OpenCode Go subscription.
- **Luna / GitHub Copilot:** a further three attempts were rejected because `gpt-6-luna` was unavailable to the installed CLI's account.
- **OpenRouter retries:** both `openrouter/anthropic/claude-haiku-5.5` and `openrouter/openai/gpt-6-luna` were offered in the installed CLI's model list. Three attempts per model were rejected for insufficient credits. No successful timing or quality result is claimed for either.

The account failures are part of this machine's observed availability. No account was upgraded and no credit purchase was made. These models can be remeasured once an authorised account can actually serve them.

## How to read the timings

The clock includes search, reading, model generation, and each adapter's repair or verification work. The local agent used the fixed case queries and a 4,096-token loaded context. Hosted agents use their provider's search tools and prompts. These are measurements of the **complete app workflows**, not of identical isolated model inference.

The requested controls were three source pages, 1,024 output tokens for local generation, temperature zero, a 240-second case timeout, and a $0.20 spend ceiling. Providers enforce different controls: Mistral's integrated search is bounded by instructions, and one request may overshoot its requested spend ceiling. A source count on that route includes search snippets, so it is not a count of full pages opened. Cloud API usage is reported by the provider; token accounting differs between routes.

The model configurations were launched in parallel while the release checks were running. The three Gemma cases ran sequentially on one GPU, including a cold first call. These small samples are suitable for showing what happened on the release host; they are not a controlled speed comparison or a general model ranking.

## Repeat a run

From a checkout with the Python environment set up, use the shipped runner. It runs the production benchmark and stores its results in JSONL. Configure your provider account first.

```powershell
.\.venv\Scripts\python.exe tools/release_bench.py --label "Haiku 5.5" --plane harness --harness claude-code --model claude-haiku-5-5 --output haiku.jsonl
.\.venv\Scripts\python.exe tools/release_bench.py --label "Gemma local agent" --plane local --model gemma3n:e2b --output gemma.jsonl
.\.venv\Scripts\python.exe tools/release_bench.py --label "GPT 6 Luna" --plane harness --harness opencode --model opencode-go/gpt-6-luna --output luna.jsonl
.\.venv\Scripts\python.exe tools/release_bench.py --label "GLM 5.3 (Mistral)" --plane api --harness mistral-api --model zai-glm-5-3 --output glm.jsonl
```

For an existing credential file, the Mistral run also accepts `--mistral-key-file <path>`. The runner loads it into the process environment without printing it or copying it into the result. It copies user preferences into a temporary app database; benchmark results are written only to the named output file. Online research still uses the chosen provider and search service.

## Recorded outputs

The output files contain the requested and selected model, per-case timings, token counts, returned answers, refused-item counts, and local stage telemetry. Source pages are represented by their URLs, lengths, and SHA-256 digests rather than reproduced in full. Credential values and user database contents are not included.

- [Haiku via Claude Code](2026-10-09-haiku.jsonl)
- [Gemma local agent](2026-10-09-gemma.jsonl)
- [Luna via OpenCode Go](2026-10-09-luna.jsonl)
- [GLM via Mistral](2026-10-09-glm.jsonl)
- [Haiku via OpenRouter retry](2026-10-09-haiku-openrouter.jsonl)
- [Luna via OpenRouter retry](2026-10-09-luna-openrouter.jsonl)
- [Luna via GitHub Copilot retry](2026-10-09-luna-copilot.jsonl)
