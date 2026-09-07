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

const { loadPanel } = require("./hover_lite_harness.js");

const ENTRY = {
  ok: true,
  listing: { damage_info: null, equipment: {} },
  result: {
    risks: [],
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
  p.deliverEntry({ ok: true, result: { risks: [] } });
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
  // actually has when the risks look wrong.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(ENTRY);

  const text = p.listing().textContent;
  assert.match(text, /2014/);
  assert.match(text, /190,000 km/);
  assert.match(text, /Dizel/);
  assert.match(text, /volkswagen golf/i);
});

test("a page the engine could not resolve still renders a header", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ok: true, listing: {},
                   result: { risks: [], coverage: "NOT_MATCHED",
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

// ── the way back to the app ─────────────────────────────────────────────

test("the footer raises the desktop app rather than opening a browser tab", () => {
  // The panel is deliberately small — it shows the risks and stops. The full
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
  // Reading the risks is half of it. The other half — the questions to take
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

const RISK = {
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

test("a verdict on a claim reaches the app with the claim's own id", () => {
  // The panel is where a reader is actually looking at the car, so it is the
  // only place a verdict is cheap to collect. It travels by claim_id: a
  // verdict against a *rendered position* would attach to whatever ranked
  // third the next time the pack changed.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, risks: [RISK] } });

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
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, risks: [RISK] } });

  const button = p.click('.lite-rc-markbtn[data-verdict="wrong"]');
  assert.equal(button.getAttribute("aria-pressed"), "true");
  // And only that one.
  const useful = p.shadow().querySelector('.lite-rc-markbtn[data-verdict="useful"]');
  assert.equal(useful.getAttribute("aria-pressed"), "false");
});

test("pressing the verdict already held takes it back", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, risks: [RISK] } });

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
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, risks: [RISK] } });

  const button = p.click('.lite-rc-markbtn[data-verdict="useful"]');
  assert.equal(button.getAttribute("aria-pressed"), "false");
});

test("a claim with no id offers no verdict at all", () => {
  // Older stored answers predate claim_id. A verdict with nothing to attach
  // to is worse than no verdict, so the control is absent rather than inert.
  const p = loadPanel();
  p.openPanel();
  const { claim_id, ...anonymous } = RISK;
  p.deliverEntry({ ...ENTRY, result: { ...ENTRY.result, risks: [anonymous] } });

  assert.equal(p.shadow().querySelector(".lite-rc-markbtn"), null);
});

// ── researching a gap from the panel ────────────────────────────────────

const GAP_ENTRY = {
  ...ENTRY,
  result: {
    ...ENTRY.result,
    risks: [],
    coverage: "NO_RISKS",
    subjects: [{ subject_id: "s9", pack_id: "org.kriko.cars",
                 label: "VW Golf 1.6 TDI", kind: "product", claims: 0 }],
  },
};

test("a subject the packs know but hold nothing on becomes a research button", () => {
  // The difference that matters: "nothing matched" is a pack adapter problem
  // the reader cannot act on, while a subject that resolved with zero claims
  // is a *named* gap. Naming it is what makes it researchable in one click.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(GAP_ENTRY);

  const gap = p.shadow().querySelector(".lite-gap");
  assert.ok(gap, "the gap was rendered");
  assert.match(gap.textContent, /VW Golf 1\.6 TDI/);

  p.click(".lite-gap-btn");
  const ask = p.sent.find((m) => m.type === "RESEARCH_SUBJECT");
  assert.ok(ask, "research was requested");
  assert.equal(ask.payload.subject_id, "s9");
  assert.equal(ask.payload.pack_id, "org.kriko.cars");
});

test("a subject that already has claims is not offered as a gap", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...GAP_ENTRY, result: { ...GAP_ENTRY.result,
    risks: [RISK],
    subjects: [{ ...GAP_ENTRY.result.subjects[0], claims: 4 }] } });

  assert.equal(p.shadow().querySelector(".lite-gap"), null);
});
