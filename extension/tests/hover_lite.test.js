// The panel's half of the contract with the service worker.
//
// The footer is backlog B15, re-pointed. It has always named whatever
// answered, so that a stale answer was visible to anyone looking at the panel
// instead of silently rendering as fresh. With the server gone, the thing a
// reader needs to identify is *whose knowledge this is*: several packs may be
// installed, none of them is authoritative, and "disable the pack that is
// wrong" is only possible if the panel says which one spoke.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { loadPanel } = require("./hover_lite_harness.js");

const ENTRY = {
  ok: true,
  listing: { damage_info: null, equipment: {} },
  result: {
    claims: [],
    coverage: "RISKS_FOUND",
    identity: { make: "volkswagen", model: "golf", fuel: "Dizel" },
    context: { build_year: 2014, usage_km: 190000 },
    // The units the answering pack declared. The panel formats from these
    // rather than from any table of its own — a year must not become "2,014"
    // and a mileage must not stay "190000".
    context_units: { usage_km: "km" },
    packs: [{ pack_id: "org.kriko.cars", version: "1.4.0" }],
  },
};

test("footer is hidden before any analysis result", () => {
  const p = loadPanel();
  p.openPanel();
  assert.equal(p.footer().hidden, true);
});

test("the footer names the pack whose knowledge answered", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(ENTRY);

  const footer = p.footer();
  assert.equal(footer.hidden, false);
  assert.equal(footer.textContent, "org.kriko.cars · 1.4.0");
});

test("two packs answering are both named", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, packs: [
    { pack_id: "org.kriko.cars", version: "1.4.0" },
    { pack_id: "com.example.tuning", version: "0.1.0" },
  ]}});
  assert.match(p.footer().textContent, /org\.kriko\.cars.*com\.example\.tuning/);
});

test("an answer no pack claims renders as unknown rather than blank", () => {
  // The B15 incident shape: something answered and would not say what. The
  // word "unknown" is itself the tell; an empty footer is not.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ok: true, result: { claims: [] } });
  assert.equal(p.footer().hidden, false);
  assert.equal(p.footer().textContent, "unknown");
});

test("footer hides again when the analysis fails", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(ENTRY);
  assert.equal(p.footer().hidden, false);

  p.deliverEntry({ ok: false, error: "Network error" });
  assert.equal(p.footer().hidden, true);
});

// ── the listing header ──────────────────────────────────────────────────

test("the header shows what the engine understood, not what the page said", () => {
  // Before Phase 6c this came from the client's own reading of the page. It
  // now comes from the resolved identity, which means the header doubles as
  // the answer to "did it understand this car?" — the question a reader
  // actually has when the claims look wrong.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(ENTRY);

  const text = p.listing().textContent;
  // extension-11 (B145 audit): a fact prints only when the pack declared a
  // unit for it. `build_year` has none here — the reader already sees the
  // year in the identity line, and printing it again as a bare "2014" in the
  // facts row was the same fact twice, the second time indistinguishable
  // from a raw count.
  assert.doesNotMatch(text, /2014/);
  assert.match(text, /190,000 km/);
  assert.match(text, /Dizel/);
  assert.match(text, /volkswagen golf/i);
});

test("a page the engine could not resolve still renders a header", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ok: true, listing: {},
                   result: { claims: [], coverage: "NOT_MATCHED",
                             identity: {}, context: {} } });
  assert.ok(p.listing());
});

// ── messaging ───────────────────────────────────────────────────────────

test("the panel asks the worker for an analysis by its current message name", () => {
  // `ANALYZE_AD` was the old name and the old payload shape. A rename that
  // misses one side fails silently — the panel sits on "analyzing" forever.
  const p = loadPanel();
  p.openPanel();
  assert.ok(p.sent.some((m) => m.type === "ANALYZE"),
            `sent: ${JSON.stringify(p.sent.map((m) => m.type))}`);
  assert.ok(!p.sent.some((m) => m.type === "ANALYZE_AD"));
});

test("which pages are analysable is the worker's answer, not a hostname check", () => {
  // The panel used to test for sahibinden.com itself, which meant installing
  // a pack for a second listing site changed nothing until someone edited
  // this file. The installed adapters decide; the panel just asks.
  const p = loadPanel({ url: "https://arabam.example/ilan/9" });
  p.openPanel();
  assert.ok(p.sent.some((m) => m.type === "ANALYZE"));
});

test("a page no pack can read is idle, not an error", () => {
  // "No pack covers this site" is not a failure the reader can act on, and
  // rendering it as one puts a red panel on every ordinary web page.
  const p = loadPanel({ analyzeResponse: { ok: false, code: "NO_ADAPTER",
                                           error: "No installed pack can read this page." } });
  p.openPanel();
  assert.equal(p.pipeline(), "idle");
  assert.equal(p.errorText(), null);
});

test("a real failure is still shown as one", () => {
  const p = loadPanel({ analyzeResponse: { ok: false, error: "Kriko is not reachable (502)." } });
  p.openPanel();
  assert.equal(p.pipeline(), "error");
  assert.match(p.errorText(), /not reachable/);
});

test("a failure is said once, in the error box, not again in the status line", () => {
  const p = loadPanel({ analyzeResponse: { ok: false, error: "Kriko is not reachable (502)." } });
  p.openPanel();
  assert.match(p.errorText(), /not reachable/);
  assert.equal(p.statusText(), "", "the status line is empty while the error box speaks");
});

// ── queue mode ──────────────────────────────────────────────────────────

test("Add to queue puts this listing's product in the app's research queue", () => {
  // The queue is filled from the listings themselves: the reader presses the
  // key on each product they are weighing, and Compare lines them up once an
  // agent has researched them.
  const p = loadPanel({ workerResponse: (m) => m.type === "QUEUE_ADD"
    ? { ok: true, added: true, count: 2, max: 8 } : { ok: true } });
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, lookup_id: "abc123" } });
  p.click(".lite-queue");

  const ask = p.sent.find((m) => m.type === "QUEUE_ADD");
  assert.ok(ask, "the panel asked the worker to queue the product");
  assert.ok(ask.payload.url, "keyed by the listing's address");
  assert.equal(ask.payload.lookup_id, "abc123", "the stored answer travels with it");
  assert.ok(ask.payload.name, "under a name the agent can research");
  const row = p.shadow().querySelector(".lite-queue-row");
  assert.match(row.textContent, /In the queue/);
  assert.match(row.textContent, /2 of 8/);
  assert.ok(p.shadow().querySelector(".lite-queue").disabled, "a second press is not offered");
});

test("a full queue says so instead of pretending the product was queued", () => {
  const p = loadPanel({ workerResponse: (m) => m.type === "QUEUE_ADD"
    ? { ok: false, status: 409, error: "Kriko refused that (the queue holds 8 products)." }
    : { ok: true } });
  p.openPanel();
  p.deliverEntry(ENTRY);
  p.click(".lite-queue");

  const row = p.shadow().querySelector(".lite-queue-row");
  assert.equal(row.dataset.phase, "error");
  assert.match(row.textContent, /queue is full/);
  assert.equal(p.shadow().querySelector(".lite-queue").disabled, false, "it can be tried again");
});

// ── the way back to the app ─────────────────────────────────────────────

test("the footer raises the desktop app rather than opening a browser tab", () => {
  // The panel is deliberately small — it shows the claims and stops. The full
  // report, the sources and the comparison live in the app.
  //
  // It used to get there with an <a href> at the engine's own port, which
  // opens the report as *another browser tab* next to the desktop app the
  // reader already has running. "Open in Kriko" has to mean the window, so
  // the control is a button and the route travels as a message.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: {
    ...ENTRY.result,
    app_route: "result/abc123",
    app_url: "http://127.0.0.1:8787/#/result/abc123",
  } });

  assert.equal(p.footer().querySelector("a"), null, "no browser-tab link");
  p.click(".lite-open-app");

  const ask = p.sent.find((m) => m.type === "OPEN_IN_APP");
  assert.ok(ask, "the panel asked the worker to raise the app");
  assert.equal(ask.payload.route, "result/abc123");
  // The tab survives as the *fallback* the worker uses when no shell answers,
  // so it is still carried — just no longer the default path.
  assert.equal(ask.payload.fallbackUrl, "http://127.0.0.1:8787/#/result/abc123");
  // The pack attribution the footer already carried must survive the addition.
  assert.match(p.footer().textContent, /org\.kriko\.cars/);
});

test("an answer the app never stored offers no way in", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(ENTRY);
  assert.equal(p.footer().querySelector(".lite-open-app"), null);
});

test("the panel hands the reader on to the two screens they act from", () => {
  // Reading the claims is half of it. The other half — the questions to take
  // to the seller, and holding this listing against the others — lived only
  // in the app, so a reader finishing the panel had to find the same listing
  // again by hand. The answer is already saved under an id, and the routes
  // arrive with it.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: {
    ...ENTRY.result,
    app_route: "result/abc123",
    app_url: "http://127.0.0.1:8787/#/result/abc123",
    app_routes: {
      result: "result/abc123",
      questions: "questions/abc123",
      compare: "compare/abc123",
    },
    app_urls: {
      result: "http://127.0.0.1:8787/#/result/abc123",
      questions: "http://127.0.0.1:8787/#/questions?id=abc123",
      compare: "http://127.0.0.1:8787/#/compare?left=abc123",
    },
  } });

  const labels = [...p.footer().querySelectorAll(".lite-open-app")]
    .map((b) => b.textContent);
  assert.deepEqual(labels, ["Open in Kriko", "Ask the seller", "Compare"]);

  p.footer().querySelectorAll(".lite-open-app")[1].dispatchEvent(
    new p.dom.window.MouseEvent("click", { bubbles: true }));
  const ask = p.sent.filter((m) => m.type === "OPEN_IN_APP").pop();
  assert.equal(ask.payload.route, "questions/abc123");
  assert.equal(ask.payload.fallbackUrl,
               "http://127.0.0.1:8787/#/questions?id=abc123");
});

test("an app that gave no routes offers no buttons for them", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: {
    ...ENTRY.result, app_route: "result/abc123" } });
  const labels = [...p.footer().querySelectorAll(".lite-open-app")]
    .map((b) => b.textContent);
  assert.deepEqual(labels, ["Open in Kriko"]);
});

test("an app that is not running offers the settings that would fix it", () => {
  // The one failure whose cause is on this side of the wire: the app is
  // listening somewhere the extension is not looking. Every other error is
  // the app's to explain, and offering its own settings there would be a
  // guess dressed as help.
  const p = loadPanel({ analyzeResponse: {
    ok: false, code: "APP_NOT_RUNNING",
    error: "Kriko is not running. Open the Kriko app, then try again." } });
  p.openPanel();
  assert.equal(p.pipeline(), "error");
  p.click(".lite-error .lite-open-app");
  assert.ok(p.sent.some((m) => m.type === "OPEN_OPTIONS"));
});

test("an ordinary failure offers nothing but the failure", () => {
  const p = loadPanel({ analyzeResponse: {
    ok: false, error: "Kriko is not reachable (502)." } });
  p.openPanel();
  assert.equal(p.shadow().querySelector(".lite-error .lite-open-app"), null);
});

// ── marking knowledge from the panel ────────────────────────────────────

const CLAIM = {
  claim_id: "c1",
  // A verdict is stored per (pack, claim): claim ids are only unique inside
  // the pack that minted them, so the pack travels with the mark.
  pack_id: "org.kriko.cars",
  subject_id: "s1",
  title: "Timing chain tensioner wear",
  severity: "high",
  strength: "reported",
  domain: "engine",
};

test("a domain group's heading is a text transform, not a lookup keyed on car parts", () => {
  // extension-22 (B145 audit, named must-fix): the panel used to hold a
  // fixed engine/transmission/emissions/... map and fell back to a
  // half-capitalized string for anything outside it. A pack the engine has
  // never seen (a drill's "chuck/bearing" domain, say) must render its
  // heading exactly as well as the cars pack's own domains do.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [
    { ...CLAIM, domain: "chuck/bearing" },
  ] } });

  const text = p.claims().textContent;
  assert.match(text, /Chuck\/Bearing/);
});

test("a verdict on a claim reaches the app with the claim's own id", () => {
  // The panel is where a reader is actually looking at the car, so it is the
  // only place a verdict is cheap to collect. It travels by claim_id: a
  // verdict against a *rendered position* would attach to whatever ranked
  // third the next time the pack changed.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CLAIM] } });

  p.click('.lite-rc-markbtn[data-verdict="useful"]');

  const mark = p.sent.find((m) => m.type === "MARK_CLAIM");
  assert.ok(mark, "the verdict left the panel");
  assert.equal(mark.payload.claim_id, "c1");
  assert.equal(mark.payload.verdict, "useful");
  assert.equal(mark.payload.subject_id, "s1");
  assert.equal(mark.payload.pack_id, "org.kriko.cars");
});

test("the verdict paints immediately, before the app has answered", () => {
  // A round trip to the engine is fast but not free, and a button that looks
  // dead until it returns gets clicked twice.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CLAIM] } });

  const button = p.click('.lite-rc-markbtn[data-verdict="wrong"]');
  assert.equal(button.getAttribute("aria-pressed"), "true");
  // And only that one.
  const useful = p.shadow().querySelector('.lite-rc-markbtn[data-verdict="useful"]');
  assert.equal(useful.getAttribute("aria-pressed"), "false");
});

test("pressing the verdict already held takes it back", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CLAIM] } });

  p.click('.lite-rc-markbtn[data-verdict="useful"]');
  const button = p.click('.lite-rc-markbtn[data-verdict="useful"]');

  assert.equal(button.getAttribute("aria-pressed"), "false");
  const asks = p.sent.filter((m) => m.type === "MARK_CLAIM");
  // A falsy verdict is the retraction — the worker turns it into a DELETE.
  assert.ok(!asks[asks.length - 1].payload.verdict);
});

test("a verdict the app refuses does not stay painted", () => {
  // The optimism has to be reversible, or a mark that never reached the
  // engine reads to the reader as one that did.
  const p = loadPanel({ workerResponse: { ok: false, error: "no such claim" } });
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CLAIM] } });

  const button = p.click('.lite-rc-markbtn[data-verdict="useful"]');
  assert.equal(button.getAttribute("aria-pressed"), "false");
});

test("a claim with no id offers no verdict at all", () => {
  // Older stored answers predate claim_id. A verdict with nothing to attach
  // to is worse than no verdict, so the control is absent rather than inert.
  const p = loadPanel();
  p.openPanel();
  const { claim_id, ...anonymous } = CLAIM;
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [anonymous] } });

  assert.equal(p.shadow().querySelector(".lite-rc-markbtn"), null);
});

// ── researching a gap from the panel ────────────────────────────────────

const GAP_ENTRY = {
  ...ENTRY,
  result: {
    ...ENTRY.result,
    claims: [],
    coverage: "NO_RISKS",
    subjects: [{ subject_id: "s9", pack_id: "org.kriko.cars",
                 label: "VW Golf 1.6 TDI", kind: "product", claims: 0 }],
  },
};

test("a subject the packs know but hold nothing on opens a consent form, not a run", () => {
  // The difference that matters: "nothing matched" is a pack adapter problem
  // the reader cannot act on, while a subject that resolved with zero claims
  // is a *named* gap. The press names it in a consent form — research spends
  // the reader's subscription, so it never starts on the first click.
  const p = loadPanel({ workerResponse: {
    ok: true, plane: { backend: "agent", budget_usd: 0 },
    job: { job_id: "j1", kind: "research", state: "running" },
  } });
  p.openPanel();
  p.deliverEntry(GAP_ENTRY);

  const gap = p.shadow().querySelector(".lite-gap");
  assert.ok(gap, "the gap was rendered");
  assert.match(gap.textContent, /VW Golf 1\.6 TDI/);

  p.click(".lite-gap-btn");
  assert.equal(
    p.sent.filter((m) => m.type === "RESEARCH_PRODUCT").length, 0,
    "no run starts on the first press",
  );
  const form = p.shadow().querySelector(".lite-research");
  assert.ok(form, "the consent form opened");
  assert.match(form.textContent, /VW Golf 1\.6 TDI/);

  p.click(".lite-research-start");
  const ask = p.sent.find((m) => m.type === "RESEARCH_PRODUCT");
  assert.ok(ask, "research was requested on the second, explicit press");
  assert.equal(ask.payload.subject_id, "s9");
  assert.ok(!("allow_draft" in (ask.payload || {})),
            "a known subject never drafts by accident");
});

const ASKED = { questions: [{ id: "engine_code", ask: "Which engine code is it?",
  options: ["BUG", "CASA"], default: "BUG", because: "BUG was common." }] };

function askingPanel(state) {
  const p = loadPanel({ workerResponse: {
    ok: true, plane: { backend: "agent", budget_usd: 0 },
    job: { job_id: "j1", kind: "pack_author", state, done: state !== "running",
           attention: ASKED },
    delivered: true, job_id: "j2", kind: "pack_author",
  } });
  p.openPanel();
  p.deliverEntry(GAP_ENTRY);
  p.click(".lite-gap-btn");
  p.click(".lite-research-start");
  return p;
}

test("a live run's question is a row of answers, and a press reaches the run (B147)", () => {
  const p = askingPanel("running");
  const asked = p.shadow().querySelector(".lite-asked");
  assert.ok(asked, "the question is on the panel, not only in the app's log");
  assert.match(asked.textContent, /Which engine code is it\?/);
  assert.doesNotMatch(p.shadow().textContent, /stopped_at|"questions"/);

  const casa = [...asked.querySelectorAll(".lite-chip")].find((b) => /CASA/.test(b.textContent));
  casa.click();
  const said = p.sent.find((m) => m.type === "JOB_SAY");
  assert.ok(said, "the answer was said to the running job");
  assert.equal(said.payload.job_id, "j1");
  assert.match(said.payload.text, /CASA/);
  assert.match(p.shadow().querySelector(".lite-asked").textContent, /It heard you\./);
});

test("a finished run's question runs it again with the answer applied (B147)", () => {
  const p = askingPanel("interrupted");
  const casa = [...p.shadow().querySelectorAll(".lite-chip")].find((b) => /CASA/.test(b.textContent));
  casa.click();
  assert.equal(p.sent.filter((m) => m.type === "JOB_SAY").length, 0);
  const retry = p.sent.find((m) => m.type === "JOB_RETRY");
  assert.ok(retry, "the run was started again");
  assert.deepEqual(retry.payload, { job_id: "j1", answers: { engine_code: "CASA" } });
});

test("a subject that already has claims is not offered as a gap", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...GAP_ENTRY, result: { ...GAP_ENTRY.result,
    claims: [CLAIM],
    subjects: [{ ...GAP_ENTRY.result.subjects[0], claims: 4 }] } });

  assert.equal(p.shadow().querySelector(".lite-gap"), null);
});

test("a subject reached only through its parts is not offered as a gap either", () => {
  // extension-4 (B145 audit): `subject.claims` only ever counts claims
  // reached *directly*, so a car whose 8 risks all reach it through a shared
  // part still has `claims: 0` on the subject itself. The gap card used to
  // read "couldn't find the knowledge" directly under those 8 risks — this
  // asserts the panel trusts what's already on screen over that count.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...GAP_ENTRY, result: { ...GAP_ENTRY.result,
    claims: [CLAIM],
    subjects: [{ ...GAP_ENTRY.result.subjects[0], claims: 0 }] } });

  assert.equal(p.shadow().querySelector(".lite-gap"), null);
});

/* Re-checking what a cited page says now.
 *
 * The button is a supplement to a card that is already useful, so every test
 * here is also asserting what does *not* happen: no panel-wide error, no card
 * that empties itself, nothing that reads as a retraction.
 */
const CITED = { ...CLAIM, sources: [{ url: "https://example.test/thread", title: "Owners' thread" }] };
const CHECK = { pack_id: "org.kriko.cars", claim_id: "c1", verdict: "quoted",
                detail: "", sources: [], checked_at: "2026-09-09T10:00:00" };

test("pressing the check asks the app about this claim, by id", () => {
  const p = loadPanel({ workerResponse: { ok: true, check: CHECK } });
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CITED] } });

  p.click(".lite-rc-factbtn");

  const asks = p.sent.filter((m) => m.type === "CHECK_FACTS");
  assert.equal(asks.length, 1);
  // The quote is never sent: the app reads it out of the pack, so a page
  // scripting this message cannot ask "does that URL contain this string".
  assert.deepEqual(asks[0].payload, { pack_id: "org.kriko.cars", claim_id: "c1" });
});

test("the verdict lands on the card with the date it was checked", () => {
  const p = loadPanel({ workerResponse: { ok: true, check: CHECK } });
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CITED] } });

  p.click(".lite-rc-factbtn");

  const label = p.shadow().querySelector(".lite-rc-factverdict");
  assert.equal(label.hidden, false);
  assert.equal(label.dataset.verdict, "quoted");
  assert.match(label.textContent, /Source still says this · 2026-09-09/);
});

test("a claim with nothing to re-read offers no button", () => {
  // CLAIM carries no sources. Offering a check that can only ever answer
  // "unreachable" would be a control that exists to disappoint.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CLAIM] } });

  assert.equal(p.shadow().querySelector(".lite-rc-factbtn"), null);
});

test("a check the app refuses leaves the card as it was", () => {
  const p = loadPanel({ workerResponse: { ok: false, error: "no engine" } });
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CITED] } });

  const button = p.click(".lite-rc-factbtn");

  assert.equal(p.shadow().querySelector(".lite-rc-factverdict").hidden, true);
  // And pressable again — a button stuck on "Reading the source…" is worse
  // than no answer, because it looks like the answer is still coming.
  assert.equal(button.disabled, false);
  assert.equal(p.errorText(), null);
});

test("a verdict already held survives the list being rebuilt", () => {
  const p = loadPanel({ workerResponse: { ok: true, check: CHECK } });
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CITED] } });
  p.click(".lite-rc-factbtn");

  // A fresh analysis of the same page redraws every card from scratch.
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, claims: [CITED] } });

  const label = p.shadow().querySelector(".lite-rc-factverdict");
  assert.equal(label.hidden, false);
  assert.equal(label.dataset.verdict, "quoted");
});

// ── how sure the engine is, and what the reader does about it ───────────
//
// The panel had two states for four situations: claims, or a blank. A reader
// who met the blank had a good pack installed for that exact product and no
// way to find out which of four things had gone wrong. Every assertion below
// is about the panel *not writing its own copy* — the sentence and the action
// word are the engine's, because a client that composes its own from a status
// code stops agreeing the first time a method is added.

const PROBABLE = {
  ...ENTRY,
  result: {
    ...ENTRY.result,
    coverage: "PROBABLE_MATCH",
    verdict: "probably",
    score: 0.58,
    considered: [{
      subject_id: "s1", pack_id: "org.kriko.cars",
      label: "Golf VII EA211 105 hp", score: 0.58,
      keys: [
        { key: "make", how: "exact", score: 1 },
        { key: "engine_code", how: "absent", score: 0 },
      ],
    }],
    next_step: {
      action: "confirm", subject_id: "s1",
      say: "This looks like Golf VII EA211 105 hp, but the page and the pack "
         + "do not agree on everything. Is that the same one?",
    },
  },
};

const verdict = (p) => p.shadow().querySelector(".lite-verdict");

test("a recognised page with claims gets no banner", () => {
  // A banner on every successful answer is a banner nobody reads by the third.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: {
    ...ENTRY.result, verdict: "recognised", score: 1,
    claims: [CLAIM], next_step: { action: "none", say: "" } } });
  assert.equal(verdict(p), null);
});

test("a doubtful answer is served, and labelled as a question", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(PROBABLE);

  const box = verdict(p);
  assert.equal(box.dataset.verdict, "probably");
  assert.match(box.textContent, /Probably this one/);
  assert.equal(box.querySelector(".lite-verdict-score").textContent, "58%");
});

test("the sentence is the engine's, word for word", () => {
  // Not paraphrased, not recomposed from the verdict — the same string.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(PROBABLE);
  assert.equal(
    verdict(p).querySelector(".lite-verdict-say").textContent,
    PROBABLE.result.next_step.say,
  );
});

test("what was weighed is shown per key, with each key's own reading", () => {
  // The two readings that matter point at different bugs: `conflict` is
  // usually the page, `absent` is usually the adapter.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(PROBABLE);

  const keys = [...verdict(p).querySelectorAll(".lite-weighed-key")]
    .map((el) => el.dataset.how);
  assert.deepEqual(keys, ["exact", "absent"]);
  assert.match(verdict(p).textContent, /Golf VII EA211 105 hp/);
});

test("a page nothing covers offers the app rather than a search", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: {
    ...ENTRY.result, verdict: "unrecognised", score: 0, considered: [],
    next_step: { action: "install",
      say: "No installed pack covers this kind of product at all." } } });

  assert.equal(verdict(p).querySelector(".lite-verdict-btn").textContent,
               "Open Kriko");
});

test("research with nothing to research on opens a named form, not a run", () => {
  // `research` arrives with a subject_id when there is something to run
  // against and without one when there is not. The second cannot start a run,
  // so it opens the research form with a name field — and a button labelled
  // "Research it" that opens a form is a button the reader stops trusting,
  // which is why the button says what the form is for.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: {
    ...ENTRY.result, verdict: "unrecognised", score: 0.2,
    considered: [{ subject_id: "s9", label: "Something else", score: 0.2, keys: [] }],
    next_step: { action: "research", url: "https://example/x",
      say: "The nearest thing installed is Something else." } } });

  assert.equal(verdict(p).querySelector(".lite-verdict-btn").textContent,
               "Research this product");
  p.click(".lite-verdict-btn");
  assert.ok(p.shadow().querySelector(".lite-research"),
            "the research form opened");
  assert.equal(
    p.sent.filter((m) => m.type === "RESEARCH_PRODUCT").length, 0,
    "no run starts before the reader presses Research in the form",
  );
});

test("an engine that says nothing about the verdict draws no banner", () => {
  // An older engine sends no verdict at all. Silence is not a fifth state to
  // render — it is the absence of an answer, and inventing one for it would
  // put words in the engine's mouth.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(ENTRY);
  assert.equal(verdict(p), null);
});

// ── typing the name ─────────────────────────────────────────────────────

const HITS = {
  ok: true,
  items: [
    { subject_id: "a", pack_id: "org.kriko.cars", label: "Golf VII", claims: 134,
      identity: { engine_code: "EA211", power_min_hp: "105" } },
    { subject_id: "b", pack_id: "org.kriko.cars", label: "Golf VII", claims: 134,
      identity: { engine_code: "EA211", power_min_hp: "125" } },
  ],
};

test("the header opens a field to type a product name into", () => {
  const p = loadPanel();
  p.openPanel();
  assert.equal(p.shadow().querySelector(".lite-search-field"), null);
  p.click(".lite-btn-search");
  assert.ok(p.shadow().querySelector(".lite-search-field"));
});

test("two characters is the floor, and nothing is asked below it", () => {
  const p = loadPanel({ searchResponse: HITS });
  p.openPanel();
  p.click(".lite-btn-search");
  p.type(".lite-search-field", "g");
  p.flushTimers();
  assert.equal(p.sent.filter((m) => m.type === "SEARCH").length, 0);
});

test("a search asks the worker, because the panel cannot reach the app", () => {
  const p = loadPanel({ searchResponse: HITS });
  p.openPanel();
  p.click(".lite-btn-search");
  p.type(".lite-search-field", "golf");
  p.flushTimers();

  const asked = p.sent.filter((m) => m.type === "SEARCH");
  assert.equal(asked.length, 1);
  assert.equal(asked[0].payload.q, "golf");
});

test("every result carries its identity, which is the whole point", () => {
  // Two rows reading "Golf VII" are not a choice. The values underneath are
  // what make them one, and that is what the reader asked search for.
  const p = loadPanel({ searchResponse: HITS });
  p.openPanel();
  p.click(".lite-btn-search");
  p.type(".lite-search-field", "golf");
  p.flushTimers();

  const hits = [...p.shadow().querySelectorAll(".lite-search-hit")];
  assert.equal(hits.length, 2);
  assert.match(hits[0].textContent, /105/);
  assert.match(hits[1].textContent, /125/);
  assert.match(hits[0].textContent, /134 known/);
});

test("a search that finds nothing says so rather than showing an empty list", () => {
  const p = loadPanel({ searchResponse: { ok: true, items: [] } });
  p.openPanel();
  p.click(".lite-btn-search");
  p.type(".lite-search-field", "nothing like this");
  p.flushTimers();
  assert.match(p.shadow().querySelector(".lite-search-note").textContent,
               /Nothing in the installed packs matches/);
});

test("pressing a result raises the app on that subject", () => {
  const p = loadPanel({ searchResponse: HITS });
  p.openPanel();
  p.deliverEntry(ENTRY);
  p.click(".lite-btn-search");
  p.type(".lite-search-field", "golf");
  p.flushTimers();
  p.click(".lite-search-hit");

  const opened = p.sent.filter((m) => m.type === "OPEN_IN_APP").pop();
  assert.equal(opened.payload.route, "subject/a");
});

test("pressing Analyze on a site nothing reads says so, and offers the fix", () => {
  // Silence is right for the automatic run at page load — nobody asked it
  // anything. It is wrong after a press: the reader hit a button called
  // "Analyze current page" and watched nothing happen, which is the dead end
  // §1.4 is about.
  const p = loadPanel({ analyzeResponse: { ok: false, code: "NO_ADAPTER" } });
  p.openPanel();
  p.click(".lite-btn-density");

  const box = p.shadow().querySelector(".lite-verdict");
  assert.equal(box.dataset.verdict, "no-adapter");
  assert.match(box.textContent.replace(/\s+/g, " "),
               /Nothing installed knows how to read this site yet/);
  p.click(".lite-verdict-btn");
  assert.equal(p.sent.filter((m) => m.type === "OPEN_IN_APP").pop().payload.route,
               "sites");
});

test("a product nothing installed knows gets its name and one research button (B149)", () => {
  // The reader's "new products aren't recognised": the page was read, the
  // product was named, and no pack holds it. The dead end used to be "Not
  // read here / Add this site", which was untrue and offered the wrong fix.
  const p = loadPanel({
    analyzeResponse: { ok: false, code: "UNKNOWN_PRODUCT", productName: "Bosch HSG 7584 B 1" },
    workerResponse: (message) => {
      if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "harness", budget_usd: 0 } };
      if (message.type === "ANALYZE") {
        return { ok: false, code: "UNKNOWN_PRODUCT", productName: "Bosch HSG 7584 B 1" };
      }
      return { ok: true };
    },
  });
  p.openPanel();
  p.click(".lite-btn-density");

  const box = p.shadow().querySelector(".lite-verdict");
  assert.equal(box.dataset.verdict, "unknown-product");
  assert.match(box.textContent.replace(/\s+/g, " "), /doesn't know Bosch HSG 7584 B 1 yet/);
  assert.doesNotMatch(box.textContent, /Add this site/);
  assert.equal(p.errorText(), null, "not a red banner");

  p.click(".lite-unknown-research");
  assert.equal(p.shadow().querySelector(".lite-research-name").value, "Bosch HSG 7584 B 1",
    "the name the page gave is already typed in");
  assert.ok(p.shadow().querySelector(".lite-research-start"));
});

test("a stored unknown-product answer reopens on the same card (B149)", () => {
  const p = loadPanel({ analyzeResponse: { ok: false, code: "UNKNOWN_PRODUCT", productName: "Acme Phone 5" } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Acme Phone 5" });
  const box = p.shadow().querySelector(".lite-verdict");
  assert.equal(box.dataset.verdict, "unknown-product");
  assert.match(box.textContent, /Acme Phone 5/);
  p.deliverEntry(ENTRY);
  assert.equal(p.shadow().querySelector(".lite-verdict[data-verdict='unknown-product']"), null);
});

test("a known site's page that just isn't a listing gets a quieter card, no 'Add this site'", () => {
  // extension-5/extension-6/extension-8: a category page on a site Kriko
  // already reads is not "nothing installed knows how to read this site" —
  // that copy, and the offer to go write an adapter, belongs only to a host
  // no pack has at all. `hostKnown` is background.js's own determination
  // (any installed adapter's domain matches this hostname), so the panel
  // never re-derives it from a site name.
  const p = loadPanel({ analyzeResponse: { ok: false, code: "NO_ADAPTER", hostKnown: true } });
  p.openPanel();
  p.click(".lite-btn-density");

  const box = p.shadow().querySelector(".lite-verdict");
  assert.equal(box.dataset.verdict, "no-adapter");
  assert.match(box.textContent.replace(/\s+/g, " "), /isn't one/);
  assert.equal(box.querySelector(".lite-verdict-btn"), null);
});

test("the empty state doesn't promise a run time it doesn't always keep", () => {
  // extension-13 (B145 audit): the copy claimed "under 2s" while the
  // automatic run actually landed around 3.2s (a 1.5s fixed delay in
  // content.js on top of the real work). Fixed the delay in content.js;
  // this half drops the broken promise from the panel's own words instead
  // of chasing a number that will drift again. Checked at the source level
  // because reaching the idle empty state through the harness means racing
  // the same auto-trigger this fix is about.
  const source = fs.readFileSync(
    path.join(__dirname, "..", "hover_lite", "hover_lite.js"), "utf8");
  assert.doesNotMatch(source, /under 2/);
  assert.match(source, /Quick Search/);
});

test("pressing Refresh asks background.js to bypass its own cache", () => {
  // extension-3 (B145 audit): the panel used to send a plain ANALYZE
  // whichever control fired it, so background.js's 6-hour result cache
  // answered a deliberate Refresh press exactly like the silent run at page
  // load — there was no way to tell it "no, actually ask this time".
  const p = loadPanel({ analyzeResponse: { ok: true, result: ENTRY.result } });
  p.openPanel();
  p.click(".lite-btn-density");

  const asked = p.sent.filter((m) => m.type === "ANALYZE").pop();
  assert.equal(asked.payload.fresh, true);
});

test("it is not a red banner, because the reader did nothing wrong", () => {
  const p = loadPanel({ analyzeResponse: { ok: false, code: "NO_ADAPTER" } });
  p.openPanel();
  p.click(".lite-btn-density");
  assert.equal(p.pipeline(), "idle");
  assert.equal(p.errorText(), null);
});

test("an answer clears it — something read the page after all", () => {
  const p = loadPanel({ analyzeResponse: { ok: false, code: "NO_ADAPTER" } });
  p.openPanel();
  p.click(".lite-btn-density");
  assert.ok(p.shadow().querySelector(".lite-verdict"));
  p.deliverEntry(ENTRY);
  assert.equal(p.shadow().querySelector(".lite-verdict"), null);
});

test("an unknown product gets one button: quick cards now, then the deeper run (B148)", () => {
  const RISK = { title: "Gearbox judder", body: "It judders.", advice: "Drive it cold.",
    severity: "high", strength: "reported", source_count: 1, domain: "example.org", quick: true,
    sources: [{ url: "https://example.org/a", domain: "example.org", quote: "it judders" }] };
  let researchPresses = 0;
  const p = loadPanel({ workerResponse: (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "harness", budget_usd: 0 } };
    if (message.type === "RESEARCH_PRODUCT") {
      researchPresses += 1;
      return { ok: true, job: researchPresses === 1
        ? { job_id: "q1", kind: "quick_look", deepen_job_id: "d1" }
        : { job_id: "d1", kind: "pack_author" } };
    }
    if (message.type === "JOB_STATUS" && message.payload.job_id === "q1") {
      return { ok: true, job: { state: "succeeded", done: true, result: {
        assumed: "the 1.6 diesel", risks: [RISK], dropped: 1, deepen_job_id: "d1",
        specs: [{ name: "Year", value: "2019", url: "https://example.org/a", domain: "example.org" }] } } };
    }
    if (message.type === "JOB_STATUS") {
      return { ok: true, job: { state: "running", done: false, progress: 0.2, message: "reading" } };
    }
    return { ok: true };
  } });
  p.openPanel();
  p.deliverEntry({ ...GAP_ENTRY, result: { ...GAP_ENTRY.result, subjects: [] } });
  p.click(".lite-research-product");
  const buttons = [...p.shadow().querySelectorAll(".lite-research button")].map((b) => b.textContent.trim());
  assert.ok(buttons.includes("Start Quick Search"), buttons.join(" | "));
  assert.equal(p.shadow().querySelector(".lite-research-draft"), null, "one button, not two");
  p.type(".lite-research-name", "Mystery Car 1.6");
  p.click(".lite-research-start");

  const asked = p.sent.find((m) => m.type === "RESEARCH_PRODUCT");
  assert.equal(asked.payload.allow_draft, true);
  assert.equal(asked.payload.url, p.dom.window.location.href);
  const slot = p.shadow().querySelector(".lite-research");
  assert.match(slot.textContent, /Gearbox judder/);
  assert.match(slot.textContent, /Taken as: the 1\.6 diesel/);
  assert.match(slot.querySelector(".lite-quick-src").textContent, /it judders/);
  assert.equal(slot.querySelector(".lite-quick-src a").getAttribute("href"), "https://example.org/a");
  // #116: the specs it read show the way a researched product's figures do,
  // and the lines it could not source are said, not hidden.
  const spec = slot.querySelector(".lite-quick-spec");
  assert.equal(spec.getAttribute("href"), "https://example.org/a");
  assert.match(spec.textContent, /Year/);
  assert.match(spec.textContent, /2019/);
  assert.match(slot.querySelector(".lite-quick-dropped").textContent, /1 line/);
  // #114: no pack is started beside the quick look. The panel stops at the
  // answer and offers the build as an explicit press.
  assert.ok(!p.sent.some((m) => m.type === "JOB_STATUS" && m.payload.job_id === "d1"),
    "the deeper run must not be followed on its own");
  assert.match(slot.querySelector(".lite-research-status").textContent, /1 thing to know/);
  // #115: the pages it read are folded into a sources drawer.
  assert.match(slot.querySelector(".lite-quick-sources-toggle").textContent, /Show sources \(1\)/);
  p.click(".lite-quick-sources-toggle");
  assert.equal(slot.querySelector(".lite-quick-sources").hidden, false);
  assert.equal(slot.querySelector(".lite-quick-source").getAttribute("href"), "https://example.org/a");
  assert.match(slot.querySelector(".lite-quick-source").textContent, /example\.org/);
  // The pack is drafted and installed only by the Build press.
  const presses = p.sent.filter((m) => m.type === "RESEARCH_PRODUCT").length;
  p.click(".lite-quick-build");
  const build = p.sent.filter((m) => m.type === "RESEARCH_PRODUCT")[presses];
  assert.equal(build.payload.deepen, true, "the Build press asks for the deep run");
  assert.equal(build.payload.quick, false, "the Build press starts no second quick look");
  assert.ok(p.sent.some((m) => m.type === "JOB_STATUS" && m.payload.job_id === "d1"));
});

test("a deep run that installed its pack refreshes the listing (B148)", () => {
  const p = loadPanel({ workerResponse: (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "harness", budget_usd: 0 } };
    if (message.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "d1", kind: "pack_author" } };
    if (message.type === "JOB_STATUS") {
      return { ok: true, job: { state: "succeeded", done: true,
        result: { installed: true, pack_id: "mystery.car" } } };
    }
    return { ok: true };
  } });
  p.openPanel();
  p.deliverEntry({ ...GAP_ENTRY, result: { ...GAP_ENTRY.result, subjects: [] } });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Mystery Car 1.6");
  const before = p.sent.filter((m) => m.type === "ANALYZE").length;
  p.click(".lite-research-start");
  assert.equal(p.sent.filter((m) => m.type === "ANALYZE").length, before + 1,
    "the listing was analysed again once the pack was in");
  assert.equal(p.shadow().querySelector(".lite-research"), null,
    "the research panel closed: the listing itself knows the product now");
});

test("a quick look can be asked a follow-up, answered in the panel (#112)", () => {
  const RISK = { title: "Gearbox judder", body: "It judders.", advice: "Drive it cold.",
    severity: "high", strength: "reported", source_count: 1, domain: "example.org", quick: true,
    sources: [{ url: "https://example.org/a", domain: "example.org", quote: "it judders" }] };
  const p = loadPanel({ workerResponse: (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "harness", budget_usd: 0 } };
    if (message.type === "RESEARCH_PRODUCT") {
      return { ok: true, job: { job_id: "q1", kind: "quick_look" } };
    }
    if (message.type === "JOB_STATUS" && message.payload.job_id === "q1") {
      return { ok: true, job: { job_id: "q1", state: "succeeded", done: true, result: {
        assumed: "the 1.6 diesel", risks: [RISK], dropped: 0 } } };
    }
    if (message.type === "JOB_STATUS" && message.payload.job_id === "a1") {
      return { ok: true, job: { job_id: "a1", state: "succeeded", done: true, result: {
        q: "Is it reliable?", answer: "The findings say it judders; drive it cold." } } };
    }
    if (message.type === "QUICK_ASK") {
      assert.equal(message.payload.job_id, "q1");
      assert.equal(message.payload.q, "Is it reliable?");
      return { ok: true, job: { job_id: "a1", kind: "quick_ask" } };
    }
    if (message.type === "QUICK_ASKS") {
      return { ok: true, asks: [{ job_id: "a1", q: "Is it reliable?",
        answer: "The findings say it judders; drive it cold.", state: "succeeded", done: true }] };
    }
    return { ok: true };
  } });
  p.openPanel();
  p.deliverEntry({ ...GAP_ENTRY, result: { ...GAP_ENTRY.result, subjects: [] } });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Mystery Car 1.6");
  p.click(".lite-research-start");
  const slot = p.shadow().querySelector(".lite-research");
  // The question box appears with the quick look.
  assert.ok(slot.querySelector(".lite-follow-input"), "the follow-up box is offered");
  p.type(".lite-follow-input", "Is it reliable?");
  p.click(".lite-follow-ask");
  assert.ok(p.sent.some((m) => m.type === "QUICK_ASK"), "the ask reached the background");
  assert.ok(p.sent.some((m) => m.type === "JOB_STATUS" && m.payload.job_id === "a1"),
    "the panel followed the ask to its answer");
  assert.match(p.shadow().querySelector(".lite-follow-q").textContent, /Is it reliable\?/);
  assert.match(p.shadow().querySelector(".lite-follow-answer").textContent, /judders/);
});

test("the follow-up exchange survives reload (#112)", () => {
  const RISK = { title: "Gearbox judder", body: "It judders.", advice: "", severity: "high",
    strength: "reported", source_count: 1, domain: "example.org", quick: true,
    sources: [{ url: "https://example.org/a", domain: "example.org", quote: "it judders" }] };
  const p = loadPanel({ workerResponse: (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "harness", budget_usd: 0 } };
    if (message.type === "RESEARCH_PRODUCT") {
      return { ok: true, job: { job_id: "q1", kind: "quick_look" } };
    }
    if (message.type === "JOB_STATUS" && message.payload.job_id === "q1") {
      return { ok: true, job: { job_id: "q1", state: "succeeded", done: true, result: {
        assumed: "the 1.6 diesel", risks: [RISK], dropped: 0 } } };
    }
    if (message.type === "QUICK_ASKS") {
      return { ok: true, asks: [{ job_id: "a1", q: "Is it reliable?",
        answer: "It judders; drive it cold.", state: "succeeded", done: true }] };
    }
    return { ok: true };
  } });
  p.openPanel();
  p.deliverEntry({ ...GAP_ENTRY, result: { ...GAP_ENTRY.result, subjects: [] } });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Mystery Car 1.6");
  p.click(".lite-research-start");
  const saved = p.storage.session._bag.get(`kriko_followups_${p.dom.window.location.href}`);
  assert.ok(saved?.quick?.risks?.length, "the quick look was cached for the reload");
  // A reload: a fresh panel on the same listing, nothing in page state.
  const again = loadPanel({ sessionBag: p.storage.session._bag, workerResponse: (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "harness", budget_usd: 0 } };
    if (message.type === "QUICK_ASKS") {
      return { ok: true, asks: [{ job_id: "a1", q: "Is it reliable?",
        answer: "It judders; drive it cold.", state: "succeeded", done: true }] };
    }
    return { ok: true };
  } });
  again.openPanel();
  again.deliverEntry({ ...GAP_ENTRY, result: { ...GAP_ENTRY.result, subjects: [] } });
  again.click(".lite-research-product");
  const slot = again.shadow().querySelector(".lite-research");
  assert.match(slot.textContent, /Gearbox judder/, "the quick cards came back");
  assert.match(slot.textContent, /Is it reliable\?/, "the exchange came back");
  assert.match(slot.textContent, /It judders; drive it cold\./, "the answer came back");
});

test("an answer keeps Quick Search available beside the header lookup refresh", () => {
  const p = loadPanel({ analyzeResponse: { ok: true, result: ENTRY.result } });
  p.openPanel();
  p.deliverEntry(ENTRY);
  const wrap = p.shadow().querySelector(".lite-cta-wrap");
  assert.equal(wrap.style.display, "");
  assert.equal(wrap.querySelector(".lite-cta-label").textContent, "Quick Search");
  assert.ok(p.shadow().querySelector(".lite-btn-density"), "the header icon still asks again");
});

test("Quick Search reads the page into a web research form and sends source limits", () => {
  const p = loadPanel({ workerResponse: (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local", budget_usd: 0 } };
    if (message.type === "PREPARE_QUICK_SEARCH") return { ok: true, name: "Northstar AX-1040R2" };
    if (message.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "quick-40", kind: "quick_look" } };
    return { ok: true };
  }});
  p.openPanel();
  const lookupsBefore = p.sent.filter((message) => message.type === "ANALYZE").length;
  p.click(".lite-cta");
  assert.equal(p.shadow().querySelector(".lite-research-name").value, "Northstar AX-1040R2");
  assert.equal(p.sent.filter((message) => message.type === "ANALYZE").length, lookupsBefore);
  p.type(".lite-research-sources", "40");
  const context = p.type(".lite-research-page-chars", "40000");
  context.dispatchEvent(new p.dom.window.Event("change", { bubbles: true }));
  p.click(".lite-research-start");
  const request = p.sent.find((message) => message.type === "RESEARCH_PRODUCT");
  assert.equal(request.payload.q, "Northstar AX-1040R2");
  assert.equal(request.payload.max_documents, 40);
  assert.equal(request.payload.context_chars, 40000);
  assert.equal(request.payload.deepen, false);
});

test("Quick Search shows and restores sourced specifications without risk cards", () => {
  const p = loadPanel({ workerResponse: (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local", budget_usd: 0 } };
    if (message.type === "PREPARE_QUICK_SEARCH") return { ok: true, name: "Northstar AX-1040R2" };
    if (message.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "specs-only", kind: "quick_look" } };
    if (message.type === "JOB_STATUS") return { ok: true, job: { job_id: "specs-only", state: "succeeded", done: true,
      result: { risks: [], specs: [{ name: "Weight", value: "2 kg", url: "https://example.org/spec" }] } } };
    return { ok: true };
  }});
  p.openPanel();
  p.click(".lite-cta");
  p.click(".lite-research-start");
  assert.match(p.shadow().querySelector(".lite-quick-spec").textContent, /Weight2 kg/);
  assert.match(p.shadow().querySelector(".lite-research-status").textContent, /1 sourced specification/);
  const again = loadPanel({ sessionBag: p.storage.session._bag });
  again.openPanel();
  again.click(".lite-cta");
  assert.match(again.shadow().querySelector(".lite-quick-spec").textContent, /Weight2 kg/);
});
