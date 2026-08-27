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
