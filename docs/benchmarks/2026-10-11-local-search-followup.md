# Local search follow-up — 2026-10-11

Request: "did a search with qwen3.5:4b no results are shown" and "agents are going to the product pages instead of issue forums and sites".

## Reproduced

The installed OpenSERP process remained running. Its health document reported `degraded`: Bing and DuckDuckGo were ready, while Ecosia's circuit was open. The installed local-plane API nevertheless reported no search service. Discovery only accepted a fully healthy service, and discarded HTTP 503 health documents.

Live OpenSERP French results also included advertisement entries with `type=ad` and DuckDuckGo click-tracking URLs. The adapter discarded the type and passed the advertisements to the reader. The planner used exact regional SKU searches and an official-specification query; unrelated readable pages consumed the page budget before relevance filtering.

A preliminary corrected live run exposed an additional false claim: Qwen treated navigation text as evidence of missing configuration. This was rejected as a valid release observation and led to further evidence gates.

## Fix

- Accept partial OpenSERP health when a configured search engine is ready. Preserve its 503 health document without accepting error documents as model inventories.
- Filter advertisements and search-engine ad redirects.
- Plan issue discussions, owner reports, and repair experiences. Pin a quoted exact-model forum search, remove extra regional SKU terms, and avoid bare model/specification searches in normal planning.
- Prefer discussion URLs and issue titles. Replace unreadable, irrelevant, and copied pages continuously rather than waiting for an entire batch. Bound extraction to the selected page ceiling and expose actual read/selected/rejected/timed-out counts.
- Allow a literal distinctive model code plus another supplied name token to establish page relevance. Claim-level applicability checks remain required.
- Reject extracted family names that omit the reader's explicit model code. Check planned query language and use localized issue queries when the planner disobeys it.
- Exclude navigation boilerplate. Classify the quoted source independently of the proposed claim before checking the claim. Missing listing metadata, repair offers, service prices, and support menus are not failure evidence.
- Replace identifiable repair-service advertisements before extraction: a generic symptom menu is not an incident report, even if a small model misclassifies its individual bullet points. A subsequent Gemma run exposed this case after the Qwen run had rejected the same type of content.
- Log rejection reasons and show honest empty-result coverage in GPUI and the extension.
- Supervise only the OpenSERP child the app owns; tolerate partial health and transient failures, recover after an owned child exits, and leave unrelated listeners untouched.
- Allow an updated 1.3.0 MSI to replace the earlier 1.3.0 build.

## Live observation

Qwen 3.5 4B, 4096 context, French response and French search, product `Lenovo IdeaPad Slim 3 15AMN8` with supplied SKU `82XQ00SFTX`.

The corrected run searched four issue queries, read seven pages from five publisher buckets, and selected six relevant pages. The first two extracted pages were exact-model Darty SAV forums. One unrelated page was replaced. Six evidence passes completed; seven candidates were rejected, with no pipeline errors and no retained findings. Repair-service advertising was classified as unclear rather than a documented failure.

The inspected Darty forum page was a product-group hub with a buyer question about the numeric keypad, product details, and generic service promotions. No failure thread or owner malfunction report appeared in the fetched text. Its evidence window retained the available discussion text. These observations establish retrieval and rejection behavior; they do not establish that the laptop is problem-free.

Static Python checks, JavaScript syntax, Rust compilation, and source review were completed. No test suites were added or run by this task. Model-based classification remains fallible. The earlier controlled model comparison describes the first MSI's pipeline snapshot, not a complete evaluation of these subsequent gates. Visual screen confirmation remains pending.

## Updated installer

The complete packaging recipe completed, followed by an isolated-source freeze and MSI relink to exclude unrelated concurrent workspace edits. Frozen-engine startup checks passed. The MSI installed successfully (exit 0), and the installed GPUI and sidecar digests matched the reviewed build. The installed local-plane API reported the reader's selected `gemma4:e2b`, French response/search, context 4096, and `ready=true`.

The final artifact checksum is published in `SHA256SUMS.txt` alongside the release MSI.

WiX reported ICE61 for the intentional same-version upgrade, plus existing ICE63/ICE91 warnings. The existing release tag remains unchanged; the installer source is recorded by the linked follow-up PR.
