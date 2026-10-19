# Kriko beta-readiness sweep

Reviewed 2026-10-19, commit `f7fd98ff`, version `0.2.5`.

The findings and baseline results below describe the tree before implementation.
See [implementation status](#implementation-status) for the changes and their
verification limits. The version has not been bumped or published.

The central gap is **task ownership**: the product can produce an answer without establishing that it did the work the reader requested. Some paths explicitly encourage handing an unfinished search back to the reader. Other paths remove the context, tools, evidence, or controls an agent needs to finish. Changing the assistant's tone alone would leave those causes in place.

This inventory names **36 gaps**. They include confirmed defects, missing capabilities, and release evidence still required. They are not 36 observed failures by real models, and they do not all have to block the same release.

## Scope and evidence

Reviewed desktop Chat, product questions, Compare, queue/job infrastructure, catalog and site management, provider routing and transport, research prompts, source handling, conversation history, cost reporting, mobile, documentation, benchmarks, and release tooling. Reviewed the extension's integration paths and ran its existing tests.

- **Reproduced:** exercised the application functions with scripted model replies, fixed search/page results, or mocked HTTP responses. These establish application behavior, not how often a real model misbehaves.
- **Source:** directly visible in the current implementation.
- **Capability:** an absent or incomplete workflow; priority depends on the release promise.
- **Unverified:** a release claim requiring an actual provider, device, browser, or packaged build.

P0 means a proposed stable-release blocker for the affected shipped workflow. P1 means important work for a dependable core experience. P2 means a product improvement or an explicit scope decision. These are audit recommendations, not an existing release policy.

## The qualities to name

| Quality | What the reader should experience |
|---|---|
| Ownership | A request starts the work and produces the requested result. |
| Initiative | The assistant takes the next obvious authorized step. |
| Persistence | A weak result leads to another useful attempt within a clear budget. |
| Judgment | It asks only when missing information materially changes the answer or action. |
| Continuity | It remembers constraints, corrections, and unfinished work. |
| Evidence discipline | It distinguishes what it checked, inferred, assumed, and could not verify. |
| Decisiveness | It makes a supported recommendation when the evidence permits one. |
| Transparency | It shows meaningful progress and explains a real blocker precisely. |
| Recoverability | The reader can stop, retry, reconnect, and preserve useful work. |
| Consistency | The same task has the same essential behavior across entry points and providers. |

## Agent behavior and orchestration

| ID / priority | Name and finding | Evidence | Definition of done |
|---|---|---|---|
| K01 · P0 | **Completion without fulfillment.** A promise or unnecessary permission question can be accepted as the final answer. The shared chat rules do not establish a consistent act/clarify/block/finish contract. | Reproduced: a scripted “I can help with that. Would you like me to get started?” is returned with progress `1.0`. [Chat finalization](../src/app/chat.py#L1073), [job handler](../src/app/web/tasks.py#L4169). | Evaluate completion against the request. Supported tasks produce the requested work; partial and blocked outcomes retain a precise reason. Behavioral scenarios catch empty offers and needless permission loops without rejecting legitimate clarification or abstention. |
| K02 · P1 | **Search handoff instead of follow-through.** Some prompts tell the agent to suggest better search words or give the search that would verify an item. That can make the reader do work the app can perform. | Source: [empty-results instructions](../src/app/chat.py#L397), [buying rule 7](../src/app/chat.py#L364). | Within the allowed budget, run an actionable alternative before asking the reader to search. When stopping is justified, say what was tried and what remains unresolved. |
| K03 · P1 | **Tool capability decided too early.** Native-tool selection uses the original message route. An ordinary-chat turn that later asks Kriko to search does not recompute that selection. Codex/Vibe can consequently keep the tool-free completion path for the subsequent web answer. | Source: [tool selection](../src/app/web/tasks.py#L4028), [captured setting](../src/app/web/tasks.py#L4101), [tool-free protocol handling](../src/app/web/tasks.py#L4320). | Resolve capabilities for the current stage. Late search escalation receives the same supported tools and evidence access as a message initially routed to web. |
| K04 · P0 | **Tool requests escaping as answers.** Search requests are decoded on the ordinary-chat path but not after the web-answer call. | Reproduced: the web answer can be exactly `SEARCH: Acme official manual`. [Web finalization](../src/app/chat.py#L1051). | Consume or explicitly fail tool requests at every model boundary. A reader never receives protocol text as a completed answer. |
| K05 · P1 | **Conversation amnesia.** Prompts receive eight previous messages, each clipped to 400 characters, with no durable constraint summary in this path. | Reproduced: an initial budget and country vanish after eight later messages. [History bounds](../src/app/chat.py#L31), [history rendering](../src/app/chat.py#L138). | Preserve active requirements and corrections across long conversations. Summarize or retrieve older context and expose meaningful truncation. |
| K06 · P2 | **Chat cannot carry out app actions.** The Chat source registry provides reads, while catalog authoring, filing, and other mutations live behind separate workflows. An action request can be routed into a read/answer path. | Source/probe: “Can you create a catalog from this research?” routes to `catalogue`; [source registry](../src/app/chatdata.py#L1084), [chat storage boundary](../src/app/web/tasks.py#L4060). | Decide the supported action scope. Supported actions execute through a controlled tool or explicit UI handoff; unsupported ones name the working route and never imply that a mutation happened. |
| K07 · P1 | **Forced brevity on detailed follow-ups.** Product and comparison follow-ups use a fixed 70-word, three-sentence, plain-text instruction even when the question needs a substantial comparison or detailed checks. | Source: [follow-up rules](../src/app/followup.py#L23), compared with [adaptive Chat length](../src/app/research_policy.py#L8). | Match answer length and formatting to the request and decision. Detailed questions can receive structured evidence, lists, and tables. |
| K08 · P2 | **Requirements are not carried as a durable task state.** The web path returns `need: {}`; conditions are mostly instructions in prose rather than a reusable record of constraints and unresolved items. | Source: [web result shape](../src/app/chat.py#L1065), [catalog planning shape](../src/app/chat.py#L216). | Keep active constraints, assumptions, covered items, and open items across turns. A multi-item request accounts for every requested item. |
| K09 · P1 | **Language-dependent research routing.** Equivalent requests in different languages do not consistently take the same path. Model-requested search can rescue some cases, but this depends on the model and K03. | Reproduced: “Find a quiet air purifier” routes to web; “Trouve-moi un purificateur silencieux” and “Bana sessiz bir hava temizleyici bul” route to chat. [Routing rules](../src/app/chat.py#L606). | Equivalent supported-language tasks get equivalent research, clarification, and action behavior. Test ordinary wording in each supported language. |
| K10 · P1 | **Incomplete turn-level cost accounting.** Chat creates a researcher for each call, returns its text without accumulated usage, and does not return turn cost/token totals. The spend overview aggregates `research_runs`, not all chat work. | Source: [per-call researcher](../src/app/web/tasks.py#L4241), [Chat result](../src/app/web/tasks.py#L4205), [spend query](../src/app/costs.py#L36), [API per-instance budget](../src/app/providers/apiagent.py#L421). | Share a turn budget and aggregate usage across planning, answering, native tools, and metadata. Show unknown or partial usage explicitly; do not present a subset as the total bill. |

## Research and evidence

| ID / priority | Name and finding | Evidence | Definition of done |
|---|---|---|---|
| K11 · P0 | **Unverified Chat citations.** Prompt instructions request grounding, but the host accepts answer URLs and claims without checking that the page was read or supports the claim. Research ingestion has stronger quote checks than Chat. | Reproduced: after reading a page stating 42 units, a scripted answer claiming 900 units with a link to `never-read.example` is retained; that URL enters `sources`. [URL extraction](../src/app/chat.py#L530), [source assembly](../src/app/chat.py#L1058). | Distinguish fetched evidence, native-tool evidence, and unverified links. Unsupported claims/citations trigger repair or an explicit unverified outcome. Preserve the evidence boundaries across providers. |
| K12 · P1 | **Only the first supplied link is read.** The direct-link path finds a single URL, so a two-link comparison can reach the answer with only one page opened by Kriko. | Reproduced with two explicit links. [Direct URL handling](../src/app/chatdata.py#L911). | Read every relevant reader-supplied link within a stated limit and report each failed read. Require evidence for both sides of a comparison. |
| K13 · P1 | **No replacement for unreadable leading results.** The host reads the first three selected pages and does not replace failed reads with remaining leads. Its query retry tests empty result rows, not absent or irrelevant page evidence. | Reproduced: five leads, first three unreadable, fourth readable; the fourth is never opened. [Page selection](../src/app/chatdata.py#L963), [retry condition](../src/app/chat.py#L1007). | Continue through alternative leads and, when useful, refine the query until evidence is adequate or the work budget is exhausted. Keep successful-page limits separate from attempted-page limits. |
| K14 · P2, P1 for manual research | **Incomplete document support.** Chat's host reader rejects PDF and other non-text content. Product manuals commonly need a document reader. Native provider tools may have different support. | Source: [content-type filter](../src/app/chatweb.py#L112). | Define supported document formats. For promised formats, extract page/section-addressable evidence; otherwise show an explicit format limitation and a usable alternative. |
| K15 · P1 | **Evidence clipped by position.** Page excerpts are clipped to 2,800 characters rather than retrieving the passage relevant to the question. A successful fetch can omit the actual specification or qualification. | Source: [excerpt fitting](../src/app/chatdata.py#L809). | Select question-relevant passages with surrounding conditions and provenance. A fact near the end of a long page remains retrievable. |
| K16 · P0 | **Decision context disappears in desktop views.** The shared desktop `Check` representation omits research coverage, diagnostic outcome, variant assumptions, usage context, and claim applicability. Product/Compare therefore cannot consistently show why a result is conditional or incomplete. | Source: [Check/Risk types and mapping](../kriko-ui/src/compare/checks.ts#L14), [product rendering](../kriko-ui/src/screens/Product.tsx#L155). | Carry and display decision-critical assumptions, applicability, disputes, and coverage. A thin or failed check with zero claims is visibly different from a well-researched check with no sourced problems. |
| K17 · P1 | **Product evidence is harder to inspect than comparison evidence.** The product screen shows up to three source links per risk without the saved quotes; Compare has expandable quotations. | Source: [product sources](../kriko-ui/src/screens/Product.tsx#L171), [Compare quotations](../kriko-ui/src/screens/Compare.tsx#L238). | Open the supporting quote and all relevant sources from either entry point, with consistent handling of supporting and disputing evidence. |
| K18 · P1 | **Saved Quick Look specifications disappear.** `loadCheck` builds specifications only from a matched catalog subject's attributes; it ignores saved `response.specs`. | Reproduced by loading a mocked saved Quick Look with a sourced Weight specification: output `specs` is empty. [Check loading](../kriko-ui/src/compare/checks.ts#L89). | Show sourced Quick Look specifications even before catalog filing. Preserve their source and quote through Product and Compare. |
| K19 · P2 | **Comparison matches wording instead of meaning.** Risks align by exact title; specifications align by exact label and compare literal value strings. Equivalent units or differently worded versions of the same issue can look different. | Source: [risk rows](../kriko-ui/src/compare/checks.ts#L128), [spec rows](../kriko-ui/src/compare/checks.ts#L141). | Use stable concept identities and supported unit normalization while preserving original wording. Do not merge different conditions merely because titles match. |
| K20 · P1 | **Freshness and specification provenance are missing from the decision view.** The loaded Check has no research timestamp or freshness state, and Compare renders spec values without their `source`. | Source: [Check fields](../kriko-ui/src/compare/checks.ts#L31), [spec cells](../kriko-ui/src/screens/Compare.tsx#L169). | Show when time-sensitive facts were checked and allow source inspection. Offer refresh for stale evidence; distinguish saved history from current information. |

## Desktop workflows and data

| ID / priority | Name and finding | Evidence | Definition of done |
|---|---|---|---|
| K21 · P0 | **Engine failure turns into a working-looking demo.** Health or roster failure switches the app into demo mode. The explicit demo explanation is inside More; the main task screens can show fixture results. | Source: [fallback](../kriko-ui/src/engine/Engine.tsx#L80), [drawer disclosure](../kriko-ui/src/ui/Drawer.tsx#L107), [product demo answer](../kriko-ui/src/screens/Product.tsx#L107). | Require an explicit demo choice, or keep a persistent unmistakable demo banner on every screen. Engine failures preserve real data and lead to recovery controls. |
| K22 · P1 | **Dead attachment affordance.** “Add a file” has no handler, file input, or corresponding attachment payload. | Source: [Composer button](../kriko-ui/src/ui/Composer.tsx#L105), [message schema](../src/app/web/routers/chat.py#L47). | Implement the promised upload/read workflow with clear supported formats, or remove/disable the control with an explanation. |
| K23 · P0 | **Inconsistent cancellation controls.** Product passes an empty Stop callback. Compare always passes `running={false}` and an empty callback, so it offers no working in-composer cancellation. | Source: [product Composer](../kriko-ui/src/screens/Product.tsx#L215), [Compare Composer](../kriko-ui/src/screens/Compare.tsx#L191). | Stop targets the actual job from every question surface, visibly acknowledges cancellation, and preserves useful partial work. |
| K24 · P1 | **Product questions hide streaming and progress.** The product screen follows jobs with a no-op read callback and shows a fixed “Searches the web” line until completion. It can ignore partial answers that other surfaces display. | Source: [job following](../kriko-ui/src/screens/Product.tsx#L116), [working state](../kriko-ui/src/screens/Product.tsx#L195). | Display real stage/activity and growing answers. Saved and newly started questions behave consistently. |
| K25 · P1 | **Silent UI failures.** Product Open errors are swallowed, Compare persistence errors are swallowed, and generic API errors collapse different connection failures into the same message. | Source: [Open catch](../kriko-ui/src/ui/ProductCard.tsx#L31), [draft save catch](../kriko-ui/src/compare.tsx#L132), [API errors](../kriko-ui/src/engine/api.ts#L61). | Every failed user action has visible, specific feedback and an appropriate retry. Distinguish “not saved” from “saved” and connection loss from validation/provider errors. |
| K26 · P1 | **Catalog management lost reachable operations.** The new panel can enable/rollback installed catalogs and install/discard existing drafts, but has no visible release catalog discovery/import, manual update, authoring, or Quick Look filing controls. Corresponding backend operations exist. | Source: [catalog panel](../kriko-ui/src/ui/panels/Catalogs.tsx#L8), [catalog client](../kriko-ui/src/engine/catalogs.ts#L171), [artifact install](../src/app/web/routers/packs.py#L17), [update/harvest endpoints](../src/app/web/routers/jobs.py#L103). | A fresh desktop user can obtain a catalog and reach every retained core catalog workflow. Explicitly scope out any retired operations and update the documentation. |
| K27 · P1 | **Onboarding explains features without proving readiness.** The tour describes agent selection and adding the extension, but does not complete connection verification, extension staging/installation, or a successful first sourced check. The startup roster is intentionally a lightweight presence check. | Source: [tour](../kriko-ui/src/tour/Tour.tsx#L19), [availability contract](../src/app/web/routers/prefs.py#L62), [agent panel](../kriko-ui/src/ui/panels/Agents.tsx#L9). | A fresh user reaches a real sourced answer through a guided path. Distinguish installed, configured, authenticated, tool-capable, and verified states without adding paid calls merely to detect presence. |
| K28 · P1 | **History search only searches a slice.** The desktop loads 200 checks and filters those rows locally. The Compare picker loads 30. Older matching work can be inaccessible through these controls. | Source: [history request](../kriko-ui/src/engine/history.ts#L73), [client filtering](../kriko-ui/src/ui/panels/History.tsx#L16), [Compare picker](../kriko-ui/src/screens/Compare.tsx#L301). | Search and page across the entire saved history. Preserve the selected filter and provide retry after loading errors. |
| K29 · P1 | **No complete backup/restore workflow.** Chat Markdown export exists, but there is no user-facing restoration workflow for the app's history, settings, catalog revisions, and research state. Keeping local files across uninstall is not a recovery flow. | Capability review: [chat-only export](../kriko-ui/src/engine/chatexport.ts#L30), [settings panel](../kriko-ui/src/ui/panels/Settings.tsx#L37), [data documentation](../README.md#your-data). | Export and restore a consistent snapshot, with an explicit policy for secrets. Verify a restore after an interrupted write or version upgrade. |
| K30 · P1 | **Chat retries are not idempotent.** The underlying runner supports `client_request_id`, but the Chat message schema and submit call do not carry one. A retry after an uncertain response can create another message/job. | Reproduced by calling the real handler twice with the same proposed request ID and a fake runner: two saved reader messages and two job IDs. [Chat request/submit](../src/app/web/routers/chat.py#L47), [runner deduplication](../src/app/web/jobs.py#L602). Compare question submission has the same integration gap in source. | The same logical send has one saved message and one logical job. Reconnect/retry discovers the existing work; an intentional repeat remains possible. |

## Validation, release, documentation, and mobile

| ID / priority | Name and finding | Evidence | Definition of done |
|---|---|---|---|
| K31 · P1 | **Benchmarks miss the coworker problem.** The fixed-web benchmark exercises Quick Look evidence extraction and settings, not conversational task ownership, multi-turn constraints, task completion, or unnecessary confirmation. API agent IDs are outside this runner's recognized roster; agents using their own web tools cannot be scored by its fixed-web path. | Source: [benchmark runner](../src/app/agentbench/runner.py#L37), [graded checks](../src/app/agentbench/checks.py#L372). | Add outcome-based scenarios for every advertised provider and entry point, including weak results, clarification, multi-item tasks, interruptions, and long conversations. Report unavailable coverage separately from passes. |
| K32 · P0 | **A green local gate is incomplete release evidence.** `tools/gate.sh` does not run the React build/lint, site tests, or mobile checks. Rust checks can be skipped for missing tooling/cache while the final summary still says “all gates passed.” The desktop workflow is manual. | Source: [local gate](../tools/gate.sh#L143), [skip handling](../tools/gate.sh#L242), [success summary](../tools/gate.sh#L284), [workflow triggers](../.github/workflows/desktop.yml#L23). This audit also found an actual red Python baseline; see K36. | Define required release checks for each shipped artifact. Include the frontend and behavioral checks, make skips visible in the release verdict, and retain results tied to the released commit. |
| K33 · P0 for release sign-off | **Packaged user journeys remain unverified by this audit.** Existing smoke scripts check process survival, installer behavior, and engine startup, but they do not establish the complete visible research journey. | Unverified: [app smoke scope](../packaging/smoke_app.py#L1), [desktop packaging workflow](../.github/workflows/desktop.yml#L140). No Windows package, live provider credentials, or real device/browser journey was exercised here. | Observe fresh install → setup → listing → sourced answer → follow-up → Compare → cancellation/reconnect → upgrade with retained data on the actual shipping package. Record provider/CLI versions and outcome. This is missing evidence, not proof these journeys fail. |
| K34 · P1 | **Documentation describes a different interface and installer.** README still has “What's new in 0.1.2” under version 0.2.5, describes Overview/Home/Check/System navigation, and refers to MSI update/install steps while the current Windows recipe builds NSIS setup EXEs. | Source: [README](../README.md), [current shell](../kriko-ui/src/App.tsx#L90), [NSIS packaging](../.github/workflows/desktop.yml#L129). | Follow installation, first use, extension setup, catalog installation, and update instructions verbatim against the shipping artifact. Each label and file type must exist. |
| K35 · P0 if mobile is included | **Mobile is a prototype with fixture research and a simulated reader.** Mobile's own README explicitly says the reader, research, and catalogs are not real; screenshot fields start from a predefined reading rather than OCR output. | Source: [mobile limitations](../kriko-mobile/README.md#what-is-real-and-what-is-not), [fixture research](../kriko-mobile/src/engine/research.ts#L1), [screenshot fields](../kriko-mobile/src/app/check.tsx#L40). | Either ship mobile explicitly as a labeled prototype outside the stable research promise, or implement and verify actual image reading, research, catalogs, and source access on a device. Desktop release need not wait for an explicitly separate prototype. |
| K36 · P0 for affected startup paths | **Database initialization depends on an existing parent directory.** `JobRunner` opens `Ledger` during `create_app`; `Ledger.connect` calls SQLite directly without creating the parent. The normal `state.connect` helper creates it, but has not necessarily run yet. | Reproduced in the clean-environment suite: one failure and three setup errors at `agentledger.py:201`, all “unable to open database file.” Source: [runner construction](../src/app/web/jobs.py#L434), [ledger connection](../src/app/agentledger.py#L200), [normal initialization](../src/app/web/state.py#L868). | Startup succeeds for a valid writable app-state path whose parent does not exist. Isolate every test's state path; a clean machine and a developer machine with existing state get the same result. Do not infer failure of every default packaged startup from this narrower case. |

## Reproduced examples

Offline probes used `chat.run_turn`, `chatdata.Context`, and the existing test `Script`/`Hooks` helpers. No live model, search provider, or paid account was called.

| Scenario | Actual result |
|---|---|
| Agent asks permission instead of explaining induction charging | Returned that text as the answer with progress `1.0`. |
| First three search pages fail; fourth would be readable | One search, three reads, zero successful pages; fourth lead never opened. |
| Web-answer model replies `SEARCH: Acme official manual` | Returned the request literally as the final answer. |
| Reader asks to compare two explicit URLs | Host reader opened only the first URL. |
| Budget/country is followed by eight later messages | The budget was absent from the next model prompt. |
| Equivalent English/French/Turkish discovery requests | Routes were `web`, `chat`, `chat`. |
| Fetched text says 42 units; model claims 900 with an unread proof link | Claim and link survived; unread URL was added to the source list. |
| Saved Quick Look has a sourced Weight specification | Real `loadCheck` returned `specs: []` against mocked HTTP data. |
| Call the Chat handler twice with the same proposed client request ID | Two saved reader messages and distinct fake job IDs. |
| Call `create_app` with a writable state path under a missing directory | SQLite raised “unable to open database file” before serving requests. |

The citation probe demonstrates that the host does not reject fabricated claims. It does not claim a real provider fabricated that answer. Likewise, absence of native-tool activity in these probes does not establish that every CLI would stop there: some tool-enabled agents can fill gaps themselves.

## Validation results

Python 3.13.5, runtime lock plus development/pipeline dependencies; Node 24.19.0.

| Check | Result |
|---|---|
| Python suite, `pytest -n 4` | **3,139 passed, 28 skipped, 1 failed, 3 errors**, 121.72 seconds. Failure: `test_web_bundle.py::test_root_identifies_the_native_app_and_api`. Errors: the three `test_pack_install.py` upload cases. All four reach the missing database-parent path in K36. |
| Extension suite, `npm test` | **318 passed**, no failures/skips. |
| Site suite, `npm run test:site` | **1 passed**. |
| Desktop UI, `npm run build` | Passed TypeScript/build; emitted a bundle-size advisory. |
| Desktop UI, `npm run lint` | Exited successfully with 36 React warnings. |
| Python lint, `ruff check src packs` | Passed. |
| Python type checks | Passed: 39 engine, 182 app, 53 pack source files; mypy notes that some untyped bodies are unchecked. |
| Version consistency | Passed for the six reported locations, all `0.2.5`. |
| Behavioral/source probes | Reproduced findings listed above. |
| Native shell compilation, Windows installer/upgrade, live agent behavior, mobile lint/typecheck/device use | Not performed. No claim of a fully passing release gate. |

The initial Python run lacked loopback socket permission and was interrupted after socket-related setup errors; the reported complete run used the network-capable execution mode so local-server tests could run. That initial run is not counted as a product failure.

## First implementation sequence

1. Fix K36 and establish a reproducible clean-state baseline.
2. Establish the shared agent contract and completion outcomes (K01–K04): do the requested work, recover within budget, ask only for decisive missing information, and expose real blockers.
3. Repair evidence integrity and context (K05, K11–K13, K16, K18). Preserve exact variants, all supplied links, active constraints, and source support.
4. Make production controls dependable (K21–K27, K30): visible engine failure, working Stop, accurate progress, visible action failures, and reachable catalog/setup workflows.
5. Enforce release evidence and correct the promise (K31–K35). Explicitly separate desktop support, prototype mobile, and any future capabilities.

A useful stable-release scenario is: “Find compatible options under my budget, verify sellers and exact variants, compare them with sources, remember my correction, and finish the recommendation.” It should work in ordinary language, survive one unreadable source and a reconnect, show real progress, and stop when asked. Genuine evidence gaps should produce a precise bounded outcome after reasonable attempts.

## Implementation status

Implemented 2026-10-19. “Implemented” records shipped-source behavior and automated
checks where available; it does not substitute for a packaged Windows observation
or establish a real model's success rate. The bounded implementations and scope
choices are stated explicitly below.

| ID | Result and boundary |
|---|---|
| K01 | Shared ownership/completion contract across Chat, follow-ups and agent adapters. Entirely empty offers get one repair attempt, then an explicit incomplete outcome. The guard is deliberately narrow, not a universal semantic completion grader. |
| K02 | Prompts request another actionable search rather than transferring the search to the reader; failed evidence receives a bounded retry. |
| K03 | Native-tool capability is recalculated for the web-answer stage after late search escalation. |
| K04 | Search requests after web/catalog answering are consumed or fail explicitly; protocol text is not accepted as completion. |
| K05 | Larger bounded recent context, older reader requirements, and durable compact memory preserve constraints and corrections. Omitted history is identified. Model context windows still bound what can be supplied. |
| K06 | Explicit Chat handoffs reach catalog authoring/filing and backup workflows. Mutations use those controlled screens; Chat does not claim to have executed an app mutation merely by discussing it. |
| K07 | Removed the fixed 70-word/three-sentence limit. Follow-up detail and structure follow the request. |
| K08 | Persistent thread memory records goals, constraints, corrections and unresolved items; web results retain the current request and prior requirements. This is compact conversational state, not a formal per-item semantic task planner. |
| K09 | Expanded discovery routing with English, French and Turkish regression examples. This establishes those examples, not coverage of every language or phrasing. |
| K10 | Shared per-turn usage/budget accounting includes planning, answering and metadata. Unknown provider usage and measured subtotals are distinguished; local cumulative token counts are not counted twice. |
| K11 | Fetched-source provenance, citation repair, model-based claim review and exact supporting-quote validation. Contradictory answers receive repair; unavailable/exhausted review and unsupported native references remain visibly unverified. Review is fallible and limited to supplied excerpts. |
| K12 | Reads multiple supplied public links, up to five per research request. Failed reads remain in the research activity. |
| K13 | Replaces unreadable leading results with remaining leads under the existing deadline, then permits a bounded query retry. |
| K14 | Public text-bearing PDFs are extracted with page labels, byte/page limits and the existing public-address restrictions. Scanned PDFs/OCR and arbitrary binary attachments are outside this implementation. |
| K15 | Question-relevant excerpts select late passages with adjacent context instead of taking only the document prefix. |
| K16 | Product/Compare retain and show assumptions, coverage, diagnostics, usage context and applicability; ambiguous subjects do not silently borrow a candidate's specs. |
| K17 | Both decision surfaces expose all saved source quotations and supporting/disputing evidence. |
| K18 | Saved Quick Look specifications retain values, sources and quotations before catalog filing. |
| K19 | Risk alignment uses concept/problem identities when supplied and normalized titles otherwise. Known numeric dimensions receive unit normalization; differences preserve conditions and wording. General semantic synonym matching is not claimed. |
| K20 | Saved dates, freshness guidance and specification sources are visible; Product offers an explicit fresh-evidence question. |
| K21 | Engine failure presents recovery controls. Demo requires an explicit choice and has a persistent visible banner. |
| K22 | Functional local text attachments: TXT, Markdown, CSV, JSON and logs up to 12 KB, with an explicit provider-sharing explanation and visible size/read errors. |
| K23 | Product/Compare Stop cancels the actual job, including a stop requested while submission is pending, and retains useful partial text. |
| K24 | Product questions show real job activity and streamed partial answers, including reconnection to saved in-progress work. |
| K25 | Visible open/load/save/submission errors, recovery controls, clearer transport errors and a guard against asking against an unsaved Compare board. |
| K26 | Reachable release discovery/import, update, Quick Look filing, draft authoring/review/install and existing enable/rollback/discard controls. |
| K27 | Guided setup includes explicit agent connection verification, catalogs, extension staging/browser instructions and a sourced-check step. A connection response is not presented as proof of research capability; the actual packaged journey still needs observation. |
| K28 | Server-side search across all saved checks, paging, retry and the same full-history picker in Compare. |
| K29 | SQLite-consistent ZIP snapshot export, validated staged restore before startup, previous-data copies and exact data-only draft restoration. Provider key files are excluded. Python tests cover committed WAL data, draft replacement and rejected traversal. The native bridge accommodates base64 expansion of a 32 MB archive; its added large-transfer Rust regression awaits Cargo/Windows validation with K33. |
| K30 | Persistent logical send IDs and backend reservations deduplicate Chat/Compare retries after uncertain responses. Reusing an ID with different input fails with a conflict. |
| K31 | Added an opt-in real-provider conversational runner for CLI/API/local agents with ownership, two-link, old-budget and latest-correction scenarios, alongside regression tests for recovery, interruption and evidence failures. Broader semantic and entry-point evaluation still requires the acceptance observations; no live-provider pass is claimed. |
| K32 | Desktop build/lint/behavior and site checks are part of the gate. Missing Rust tooling/cache/Windows target returns an incomplete nonzero result. Publication additionally requires observed journeys tied to the exact source fingerprint. Mobile checks are explicit for the separate prototype. |
| K33 | **Awaiting external validation.** Added the required packaged journeys, evidence format and publication check. Windows install/upgrade, browser/device operation and real provider/model outcomes were not available in this environment; no passing evidence was fabricated. |
| K34 | Rewrote installation/usage documentation for current navigation, setup, catalogs, backups, NSIS setup EXEs and portable ZIPs. Following it on the shipping Windows package remains part of K33. |
| K35 | Chose the explicitly separate prototype scope: persistent mobile prototype disclosure, prototype app name and README limitations. Mobile lint/typecheck pass; simulated research is not advertised as stable research. |
| K36 | Ledger initialization creates a missing writable parent; affected tests isolate their state paths. Cold-start regression passes. |

Core regression evidence lives in [task ownership tests](../src/app/tests/test_task_ownership.py),
[desktop behavior tests](../kriko-ui/tests/checks.test.mjs) and
[release acceptance tests](../src/app/tests/test_release_acceptance.py).
The [shared contract](../src/app/workcontract.py),
[conversation runner](../src/app/conversationbench.py) and
[release acceptance procedure](RELEASE_ACCEPTANCE.md) make the behavior and the
remaining release work reviewable.

### Checks after implementation

Python 3.13.5 and Node 24.19.0, with loopback access enabled for local-server tests.

| Check | Result |
|---|---|
| Python gate: versions, Ruff, mypy, full suite | 3,173 passed, 28 skipped; all static checks passed, including exact and empty-draft restoration. Shell source/packaging checks were rerun after the bridge edit; actual Rust execution remains incomplete. |
| Extension | 318 passed. |
| Desktop UI | Build and lint passed; four actual behavior scenarios passed. React hook warnings and a bundle-size advisory remain. |
| Website | Existing suite passed. |
| Shipped Python wheel | Import and CLI smoke checks passed. |
| Mobile prototype | Typecheck and lint passed; no device observation. |
| Live-provider conversation suite | Plan generated; real requests not run because provider accounts/models are not configured here. |
| Native shell / Windows shipping package | Incomplete: Cargo is unavailable here; packaged journeys remain unobserved. |
| Release evidence validation | Correctly rejects absent observation evidence. Publication is blocked until the acceptance record is supplied for the final source. |

These results establish an implementation baseline, not stable-release sign-off.
