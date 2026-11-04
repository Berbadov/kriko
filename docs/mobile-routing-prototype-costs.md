# Kriko caching and model-routing prototype

31 October 2026 · APK 0.13.1 · Android package app.kriko.mobile

## Cost estimate

USD, excluding applicable tax. These are planning estimates, not measured
production averages. Model charges use official list prices checked on 31 October.

| Request | Estimated direct API charge | Planning cost including retry/serving allowance |
|---|---:|---:|
| Simple 3B answer, 600 input / 200 output tokens | $0.000080 | $0.001096 |
| Simple 8B answer, 600 input / 200 output tokens | $0.000120 | $0.001144 |
| Screenshot research | $0.011480 | $0.014776 |
| Deep comparison | $0.027810 | $0.034372 |

Planning cost = API charge × 1.20 + $0.001 per request. Both overhead figures
are assumptions. A local answer-cache hit has zero new model/retrieval charge;
the planning calculations still reserve the per-request overhead.

For a shopping-heavy mix of 20% eligible simple questions, 60% screenshot
research and 20% deep comparisons, the modeled average is **$0.0159664 per
query: about 1.60 cents**, versus the earlier $0.0168184 estimate. This assumes
simple traffic is 25% 3B / 75% 8B at 600/200 tokens, with no cache hits.
If 10% of those simple requests hit the cache, the average is $0.01596376.
The narrow cache therefore adds little savings to this shopping-heavy mix.

The earlier simple-request estimate included two retrievals. Mercury could
already answer a simple question without tools. Giving Mercury the same short
prompt and no tools produces an overall $0.0160024 average, so the model swap
alone accounts for only a small part of the reduction. Research still dominates.

Keep **$0.02 per research credit** for package budgeting until representative
mobile usage is measured. Example allowances:

| Plan | Research credits | Full-use contribution at $0.02/credit |
|---|---:|---:|
| $6.99/month | 100 | $3.69 |
| $12.99/month | 250 | $5.64 |

Contribution assumes a 15% Play deduction and $0.25/$0.40 other monthly variable
costs. It excludes fixed overhead, taxes, refunds and acquisition. Deep tasks
should use weighted credits; price monitoring needs a separate allowance.
These are package proposals, not implemented subscriptions.

## What is implemented

- Ministral 8B for eligible translations, Turkish rewrites and basic explanations.
- Ministral 3B for eligible English rewrites and allowlisted basic definitions.
- Mercury research for shopping, prices, merchant credibility, screen context,
  conversational follow-ups, non-default research preferences and other requests.
- Mercury fallback if the quick request fails, is incomplete, or expresses
  recognized uncertainty/research needs. This does not detect every wrong answer.
- Local memory cache: at most 32 successful static answers, ten-minute TTL,
  scoped to exact question, credential, model, language and answer style.
- History/access clearing invalidates the cache, including pending cache writes.
  Screenshots, fresh prices and merchant results are excluded.
- No 14B route. GLM Flash was compared but is not enabled in this APK.

The configured environment key was used for live synthetic benchmarking, not
embedded in the APK. Enable the route by supplying the optional Mistral key in
BYOK, alongside Mercury and DeepSeek. Existing two-key trials/grants still work
through Mercury. This prototype has no hosted billing or cost-metering backend.

## Try the prototype

1. Install kriko-agent-0.13.1.apk over the previous same-signed build to retain
   app data. Signature checks passed; phone interaction testing is still needed.
2. Configure BYOK with all three keys. Keep research preferences at their defaults
   and thoroughness at 50 or lower. Use a fresh chat without a screen attachment.
3. Ask `Define photosynthesis` to try 3B.
4. Start another fresh chat and ask `What is gravity?` to try 8B.
5. Ask `Translate to Turkish: Good evening.` in a fresh chat to try 8B translation.
6. Repeat the identical question in another fresh chat within ten minutes.
   The answer steps should say it came from this device's recent answer cache.
   Repeating inside the same conversation retains history and uses research.
7. Try a product/merchant question or attach a screenshot: it should use research.
8. Clear history, then repeat the static question in a fresh chat: it should
   call the model again. Diagnostics remain optional, off by default.

Typecheck, Expo lint, offline routing/cache regressions, Android release build,
APK signature and 16 KB alignment checks passed.

## Evidence and next measurements

The retained synthetic benchmark contains 20 short prompts per model. Manual
semantic grading gave 3B 12/20, 8B 12/20, GLM Flash 18/20. Both Ministral models
made numerical and Turkish definition errors; GLM hit the output cap on two
tasks. These prompts are not a representative mobile workload or a broad model
ranking. The route is deliberately limited rather than replacing the researcher.
Recorded testing charges across both runs total $0.00306 at list rates.

Before raising allowances, measure 200–500 real mobile turns: route, accepted
answer rate, all model/vision token usage, retrieval charges, retries, fallback,
cache hits, latency and cost per attempted/accepted answer. Reconcile provider
invoices; report mean and p95 rather than treating these estimates as telemetry.

Official model rates per million input/output tokens:
[3B $0.10/$0.10](https://docs.mistral.ai/models/ministral-3-3b-25-12),
[8B $0.15/$0.15](https://docs.mistral.ai/models/ministral-3-8b-25-12),
[GLM Flash $0.15/$0.50](https://docs.mistral.ai/models/zai-glm-5-3-flash).
