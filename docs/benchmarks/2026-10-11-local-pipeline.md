# Local pipeline comparison — 2026-10-11

Target: the GPUI desktop and browser extension, sharing the Python research engine.
The Svelte/Tauri frontend is retired.

## Mechanism

1. Extract product identity from the request and listing. Keep unknown variants explicit.
2. Plan searches in the selected search language through local OpenSERP.
3. Read up to six usable pages, preferring different registrable domains and replacing unreadable results.
4. Extract each page separately within the local context budget. The model selects evidence IDs; Python copies the original source characters.
5. Reject wrong-model evidence, invented numbers, invalid references, and unsupported assertions. A structured model check is an additional filter, not a factual guarantee.
6. Corroborate matching failures using independent publishers. Preserve representative checked wording and every citation.
7. Render display text in the response language and check the rendered assertion against the unchanged evidence. Report incomplete stages explicitly.

Pages read, pages relevant, completed evidence passes, cited pages, and publishers per finding are separate counts. Reading six pages does not imply six sources support each finding.

## Installed-model comparison

Identical fictional evidence, native Ollama, temperature 0, thinking disabled, 4096-token context. Output limits vary by stage. One case contains two documented problems and matching battery reports; another contains positive evidence and a neighbouring model's failure. This is a small controlled comparison, not a general benchmark or proof of reliability.

Final shipping pipeline digest: `67fd77e059831464fdfb061380b76ddfa774c9e13a71a9d9383d808313140ed6`.

| Installed model | Expected problems recovered | Battery publishers | Abstention case | Evidence-case time |
|---|---:|---:|---|---:|
| Qwen 3.5 4B | 2/2 | 2 | Correct | 23.0 s |
| Qwen 3.5 0.8B | 1/2 | 1 | Correct | 20.7 s |
| Gemma 3n E2B | 0/2 after rendering filters | 0 | No findings; partial | 34.5 s |

Gemma extracted candidates but failed language/number preservation checks; the pipeline withheld affected output and reported partial coverage. Earlier versions allowed a positive review to appear as a risk. Those historical artifacts document why the guards changed; they do not validate the final pipeline.

Qwen 4B is the smallest **tested** configuration meeting these cases. Its installed Q4 model is approximately 3.3 GB. The 0.8B model missed a documented problem despite receiving the same sources. Increasing the source counter would not repair that extraction failure.

The Turkish run recovered both problems, kept the battery's two-publisher support, generated Turkish queries and display text, and retained the English source quotes. Technical specification values remain copied from sources. Results: [English/model comparison](2026-10-11-shipping-model-comparison.jsonl), [Turkish](2026-10-11-shipping-turkish.jsonl).

## Reproduce

```powershell
.venv\Scripts\python.exe tools/evaluate_local_pipeline.py --models qwen3.5:4b qwen3.5:0.8b gemma3n:e2b --contexts 4096 --output comparison.jsonl
.venv\Scripts\python.exe tools/evaluate_local_pipeline.py --models qwen3.5:4b --contexts 4096 --cases evidence --language tr --search-language tr --plan-queries --output turkish.jsonl
```

The comparison fixes web evidence to isolate model behaviour. Live OpenSERP was separately observed returning Bing results through the production multi-engine adapter; DuckDuckGo did not return results in the initial probe. Search and fetched-page availability can vary.

Ollama receives the selected context limit directly. Other OpenAI-compatible servers must also be configured with a matching context window on the server. Verification and language checks use the same local model and can make correlated mistakes. Exact copied quotes establish what a fetched page says, not whether its author is correct or independent of another publisher.

Windows installer and live API observations are recorded in [the native release record](2026-10-11-native-release.md). GPUI screen appearance remains unverified because the computer-use helper pipe was unavailable. No pytest or Vitest suites were run.
