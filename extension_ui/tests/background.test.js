// The service worker's contract with the local app.
//
// Phase 6c rewired this. It used to POST `{listing_url, ad_metadata}` to
// `/analyze` on ports 8000/8765 — an endpoint and a payload that no longer
// exist. It now POSTs the raw scrape to `/api/analyze` on 8787 and lets the
// installed pack decide what any of it means.
//
// These tests exist because that mismatch shipped silently: the server side
// was rebuilt and verified end to end while the extension went on calling a
// dead endpoint, and nothing failed until someone opened a listing.
const test = require("node:test");
const assert = require("node:assert");

const { loadBackground } = require("./background_harness.js");

const ADAPTERS = [{
  id: "sahibinden", site: "sahibinden.com", pack_id: "org.kriko.cars",
  match: ["*sahibinden.com/ilan/*"],
  labels: ["marka", "seri", "yıl", "yakıt", "vites", "kilometre"],
}];

const CLAIM = {
  title: "Timing chain tensioner wear",
  body: "Rattle on cold start above 120,000 km.",
  advice: "Listen for a two-second rattle from cold.",
  severity: "high", domain: "engine", subject: "EA888 Gen2",
  relevance: 0.82, disputed: false, pack_id: "org.kriko.cars",
  why: ["high severity", "from pack: org.kriko.cars"],
  sources: [{ url: "https://vw.example/tsb", domain: "vw.example",
              quote: "q", stance: "supports", tier: "manufacturer" }],
};

const ANALYSIS = {
  adapter: "sahibinden",
  identity: { make: "volkswagen", model: "golf" },
  context: { usage_km: 190000 },
  unmapped_labels: ["Takasa Uygun"],
  method: "narrowed", coverage: "RISKS_FOUND", flags: [],
  claims: [CLAIM],
};

const SCRAPE = {
  url: "https://www.sahibinden.com/ilan/x",
  title: "2014 Volkswagen Golf",
  description: "Bakımlı.",
  fields: { Marka: "Volkswagen", Yıl: "2014" },
  listing: { damage_info: { changed: [] }, equipment: {} },
};

const routes = (analysis = ANALYSIS) => ({
  "/api/adapters": ADAPTERS,
  "/api/analyze": analysis,
});

const withTab = (scrape = SCRAPE) => ({ GET_SCRAPE: { ok: true, payload: scrape } });

async function analyse(opts = {}) {
  const h = loadBackground({
    routes: routes(opts.analysis), tabResponses: withTab(opts.scrape),
  });
  const result = await h.sandbox.runAnalysisForTab(1, SCRAPE.url);
  return { ...h, result };
}

// ── the wire contract ───────────────────────────────────────────────────

test("the analysis is POSTed to /api/analyze on the local app's port", async () => {
  const { state } = await analyse();
  const post = state.requests.find((r) => r.method === "POST");
  assert.equal(post.url, "http://127.0.0.1:8787/api/analyze");
});

test("the request body is the raw scrape, with nothing interpreted", async () => {
  const { state } = await analyse();
  const post = state.requests.find((r) => r.method === "POST");

  assert.deepEqual(post.body.fields, SCRAPE.fields);
  assert.equal(post.body.url, SCRAPE.url);
  assert.equal(post.body.title, SCRAPE.title);
  // The old payload's shape. Its presence would mean the client had gone back
  // to deciding what the page means.
  assert.ok(!("ad_metadata" in post.body));
  assert.ok(!("listing_url" in post.body));
  // Damage and equipment are for the panel, not the engine.
  assert.ok(!("listing" in post.body));
});

test("the labels the content script scans for come from the installed pack", async () => {
  const { state } = await analyse();
  const ask = state.tabMessages.find((m) => m.message.type === "GET_SCRAPE");
  assert.deepEqual(ask.message.labels, ADAPTERS[0].labels);
});

test("a site no installed pack can read is never scraped at all", async () => {
  const h = loadBackground({ routes: routes(), tabResponses: withTab() });
  await assert.rejects(
    () => h.sandbox.runAnalysisForTab(1, "https://elsewhere.invalid/x"));
  assert.equal(h.state.tabMessages.length, 0);
  assert.ok(!h.state.requests.some((r) => r.method === "POST"));
});

// ── claims become the panel's view model ────────────────────────────────

test("a claim becomes a risk card the panel can render", async () => {
  const { result } = await analyse();
  const [risk] = result.risks;

  assert.equal(risk.title, CLAIM.title);
  assert.equal(risk.rationale, CLAIM.body);
  assert.equal(risk.inspection_advice, CLAIM.advice);
  assert.equal(risk.severity, "high");
  assert.equal(risk.domain, "engine");
  assert.deepEqual(risk.why_shown, CLAIM.why);
});

test("a manufacturer-sourced claim reads as confirmed", async () => {
  const { result } = await analyse();
  assert.equal(result.risks[0].strength, "confirmed");
  assert.equal(result.risks[0].confidence, 0.82);
});

test("a forum-sourced claim reads as reported, and says how many said it", async () => {
  const claim = { ...CLAIM, sources: [
    { ...CLAIM.sources[0], tier: "forum_ugc" },
    { ...CLAIM.sources[0], tier: "seo_blog" },
  ]};
  const { result } = await analyse({
    analysis: { ...ANALYSIS, claims: [claim] } });

  assert.equal(result.risks[0].strength, "reported");
  assert.equal(result.risks[0].source_count, 2);
  // A numeric score next to "Reported" would read as trustworthy and undercut
  // the label; the card only shows one on confirmed claims.
  assert.equal(result.risks[0].confidence, undefined);
});

test("a disputed claim still reaches the panel, marked", async () => {
  const { result } = await analyse({
    analysis: { ...ANALYSIS, claims: [{ ...CLAIM, disputed: true }] } });
  assert.equal(result.risks[0].disputed, true);
});

test("coverage and the resolved identity survive into the view model", async () => {
  const { result } = await analyse();
  assert.equal(result.coverage, "RISKS_FOUND");
  assert.equal(result.identity.make, "volkswagen");
  assert.equal(result.context.usage_km, 190000);
});

test("a page nothing matched is an answer, not an error", async () => {
  const { result } = await analyse({ analysis: {
    ...ANALYSIS, coverage: "NOT_MATCHED", claims: [] } });
  assert.deepEqual(result.risks, []);
  assert.equal(result.coverage, "NOT_MATCHED");
});

// ── what the panel reads it from ────────────────────────────────────────

test("the result is written to session storage under the listing url", async () => {
  const { state, result } = await analyse();
  const entry = state.session["kriko_result_" + SCRAPE.url];
  assert.equal(entry.ok, true);
  assert.deepEqual(entry.result, result);
  // The panel renders the damage and equipment panels from this.
  assert.deepEqual(entry.listing, SCRAPE.listing);
});

test("the badge counts high-severity risks", async () => {
  const { state } = await analyse();
  assert.equal(state.badge[1], "1");
});

test("a failed analysis leaves an error entry the panel can show", async () => {
  const h = loadBackground({ routes: {}, tabResponses: withTab() });
  await assert.rejects(() => h.sandbox.runAnalysisForTab(1, SCRAPE.url));
  const entry = h.state.session["kriko_result_" + SCRAPE.url];
  assert.equal(entry.ok, false);
  assert.ok(entry.error);
});
