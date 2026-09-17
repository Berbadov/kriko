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

const fs = require("node:fs");
const path = require("node:path");

const { loadBackground, send } = require("./background_harness.js");

const MANIFEST = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "manifest.json"), "utf8"));

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
  context_units: { usage_km: "km" },
  packs: [{ pack_id: "org.kriko.cars", version: "0.4.0" }],
  unmapped_labels: ["Takasa Uygun"],
  method: "narrowed", coverage: "RISKS_FOUND", flags: [],
  verdict: "recognised", score: 1.0, considered: [],
  next_step: { action: "none", say: "" },
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

test("a claim reaches the panel under the engine's own field names", async () => {
  // The worker used to rename three things on the way through — `claims` to
  // `risks`, `body` to `rationale`, `advice` to `inspection_advice` — for
  // nothing. A shared component would have had to translate, and a bug report
  // saying "risk" needed a mental hop to reach a `claims` table.
  const { result } = await analyse();
  const [claim] = result.claims;

  assert.equal(claim.title, CLAIM.title);
  assert.equal(claim.body, CLAIM.body);
  assert.equal(claim.advice, CLAIM.advice);
  assert.equal(claim.severity, "high");
  assert.equal(claim.domain, "engine");
  assert.deepEqual(claim.why_shown, CLAIM.why);
});

test("a manufacturer-sourced claim reads as confirmed", async () => {
  const { result } = await analyse();
  assert.equal(result.claims[0].strength, "confirmed");
  assert.equal(result.claims[0].confidence, 0.82);
});

test("a forum-sourced claim reads as reported, and says how many said it", async () => {
  const claim = { ...CLAIM, sources: [
    { ...CLAIM.sources[0], tier: "forum_ugc" },
    { ...CLAIM.sources[0], tier: "seo_blog" },
  ]};
  const { result } = await analyse({
    analysis: { ...ANALYSIS, claims: [claim] } });

  assert.equal(result.claims[0].strength, "reported");
  assert.equal(result.claims[0].source_count, 2);
  // A numeric score next to "Reported" would read as trustworthy and undercut
  // the label; the card only shows one on confirmed claims.
  assert.equal(result.claims[0].confidence, undefined);
});

test("a disputed claim still reaches the panel, marked", async () => {
  const { result } = await analyse({
    analysis: { ...ANALYSIS, claims: [{ ...CLAIM, disputed: true }] } });
  assert.equal(result.claims[0].disputed, true);
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
  assert.deepEqual(result.claims, []);
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

test("the badge counts high-severity claims", async () => {
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

// ── the bridge back to the app ──────────────────────────────────────────

test("the request says which door it came in by", async () => {
  const { state } = await analyse();
  const post = state.requests.find((r) => r.method === "POST");
  // Without this every analysis looks in-app in the reader's history, and the
  // first question anyone asks about a surprising result — "where did this
  // come from?" — has no answer.
  assert.equal(post.body.origin, "extension");
});

test("the result carries a link that opens the same answer in the app", async () => {
  const { result } = await analyse({
    analysis: { ...ANALYSIS, lookup_id: "abc123" } });
  assert.equal(result.app_url, "http://127.0.0.1:8787/#/result/abc123");
});

test("an answer the app did not store offers no link to it", async () => {
  const { result } = await analyse();
  assert.equal(result.app_url, undefined);
});

test("an app that is not running says so, rather than naming a status code", async () => {
  const h = loadBackground({ offline: true, tabResponses: withTab() });
  await assert.rejects(() => h.sandbox.runAnalysisForTab(1, SCRAPE.url));
  const entry = h.state.session["kriko_result_" + SCRAPE.url];
  assert.equal(entry.code, "APP_NOT_RUNNING");
  // The panel keys its "start Kriko" hint off the code, but the text is what
  // a reader who never opens the panel's internals actually sees.
  assert.match(entry.error, /not running|Kriko/i);
});

// ── the two doors into the panel ────────────────────────────────────────
//
// A keyboard shortcut is worth having only if it does the same thing as the
// button. These pin the two ends of that: one function behind both listeners,
// and a manifest whose command name is the one the worker actually answers to
// — a mismatch there is silent, because Chrome registers a command nobody
// handles and the key simply does nothing.

test("the toolbar button and the keyboard shortcut send the same message", async () => {
  const h = loadBackground({ tabResponses: { TOGGLE_HOVER_LITE: { ok: true } } });

  h.clickListeners[0]({ id: 7 });
  await h.commandListeners[0]("toggle-panel");
  await new Promise((r) => setImmediate(r));

  assert.deepEqual(h.state.tabMessages.map((m) => m.message.type),
                   ["TOGGLE_HOVER_LITE", "TOGGLE_HOVER_LITE"]);
  // The command has no tab of its own and has to ask which one is in front.
  assert.deepEqual(h.state.tabMessages.map((m) => m.tabId), [7, 1]);
});

test("the manifest declares the command the worker listens for", () => {
  const declared = Object.keys(MANIFEST.commands || {});
  assert.deepEqual(declared, ["toggle-panel"]);
  const source = fs.readFileSync(
    path.join(__dirname, "..", "background.js"), "utf8");
  assert.ok(source.includes('command !== "toggle-panel"'),
            "the worker must answer to the command name the manifest declares");
});

test("an unknown command touches nothing", async () => {
  const h = loadBackground({ tabResponses: { TOGGLE_HOVER_LITE: { ok: true } } });
  await h.commandListeners[0]("some-other-thing");
  assert.deepEqual(h.state.tabMessages, []);
});

test("a page with no panel in it is not an error", async () => {
  // No `tabResponses`, so `sendMessage` rejects the way it does on a tab no
  // content script was injected into.
  const h = loadBackground();
  h.clickListeners[0]({ id: 7 });
  await h.commandListeners[0]("toggle-panel");
  await new Promise((r) => setImmediate(r));
  // Nothing thrown, nothing unhandled: reaching here is the assertion.
  assert.equal(h.state.tabMessages.length, 2);
});

// ── where the app is ────────────────────────────────────────────────────

test("the options page is told the default and what was actually stored", async () => {
  const h = loadBackground({ routes: { "/api/health": { version: "0.3.3" } } });
  const first = await send(h, { type: "GET_API_BASE" });
  assert.equal(first.base, "http://127.0.0.1:8787");
  assert.equal(first.default, "http://127.0.0.1:8787");
  // Empty, not the default: "I have not chosen" and "I chose the default"
  // have to stay distinguishable, or emptying the field reads as a no-op.
  assert.equal(first.stored, "");
});

test("a saved address is normalised once, by the code that consumes it", async () => {
  const h = loadBackground({ routes: { "/api/health": { version: "0.3.3" } } });
  const reply = await send(h,
    { type: "SET_API_BASE", payload: { url: " 192.168.1.9:8787/ " } });
  assert.equal(reply.ok, true);
  assert.equal(reply.base, "http://192.168.1.9:8787");
  assert.equal(h.state.local.krikoApiBaseUrl, "http://192.168.1.9:8787");
});

test("saving reports whether anything answered there, without refusing the save", async () => {
  const h = loadBackground({ offline: true });
  const reply = await send(h,
    { type: "SET_API_BASE", payload: { url: "http://127.0.0.1:9999" } });
  // Saved anyway. Configuring the extension before starting the app is a
  // reasonable order to do things in.
  assert.equal(h.state.local.krikoApiBaseUrl, "http://127.0.0.1:9999");
  assert.equal(reply.ok, true);
  assert.equal(reply.reachable, false);
  assert.match(reply.detail, /not running/i);
});

test("a reachable app answers with its version", async () => {
  const h = loadBackground({ routes: { "/api/health": { version: "0.3.3" } } });
  const reply = await send(h,
    { type: "SET_API_BASE", payload: { url: "http://127.0.0.1:8787" } });
  assert.equal(reply.reachable, true);
  assert.equal(reply.version, "0.3.3");
});

test("emptying the field forgets the address rather than storing nothing", async () => {
  const h = loadBackground({ routes: { "/api/health": { version: "0.3.3" } } });
  await send(h, { type: "SET_API_BASE", payload: { url: "http://elsewhere:1" } });
  const reply = await send(h, { type: "SET_API_BASE", payload: { url: "  " } });
  assert.equal("krikoApiBaseUrl" in h.state.local, false);
  assert.equal(reply.base, "http://127.0.0.1:8787");
  assert.equal(reply.stored, "");
});

test("something that is not an address is refused, and the old one kept", async () => {
  const h = loadBackground({ routes: { "/api/health": {} } });
  await send(h, { type: "SET_API_BASE", payload: { url: "http://127.0.0.1:8787" } });
  const reply = await send(h, { type: "SET_API_BASE", payload: { url: "///" } });
  assert.equal(reply.ok, false);
  assert.equal(h.state.local.krikoApiBaseUrl, "http://127.0.0.1:8787");
});

test("changing the address drops the adapter list the old app gave us", async () => {
  const h = loadBackground({
    routes: routes(), tabResponses: withTab() });
  await h.sandbox.runAnalysisForTab(1, SCRAPE.url);
  const before = h.state.requests.filter((r) => r.url.endsWith("/api/adapters")).length;
  await send(h, { type: "SET_API_BASE", payload: { url: "http://127.0.0.1:8788" } });
  await h.sandbox.runAnalysisForTab(1, SCRAPE.url);
  const after = h.state.requests.filter((r) => r.url.endsWith("/api/adapters")).length;
  assert.ok(after > before,
    "which sites are worth reading is a fact about one app, not a global one");
});

test("the panel can open the extension's own settings", async () => {
  const h = loadBackground();
  const reply = await send(h, { type: "OPEN_OPTIONS" });
  assert.equal(reply.ok, true);
  assert.equal(h.state.optionsOpened, 1);
});

test("the manifest ships that settings page", () => {
  assert.equal(MANIFEST.options_ui.page, "options/options.html");
  for (const file of ["options/options.html", "options/options.js",
                      "options/options.css"]) {
    assert.ok(fs.existsSync(path.join(__dirname, "..", file)), file);
  }
});

// ── what a reader does next ─────────────────────────────────────────────

test("a stored answer carries the two screens a reader acts from", async () => {
  const { result } = await analyse({
    analysis: { ...ANALYSIS, lookup_id: "abc123" } });
  // Path segments, not query strings: `/api/focus` refuses a query on
  // purpose, so this is the only spelling that survives the handoff.
  assert.deepEqual(result.app_routes, {
    result: "result/abc123",
    questions: "questions/abc123",
    compare: "compare/abc123",
  });
  // And the same three as tabs, for when no desktop shell is listening.
  assert.equal(result.app_urls.questions,
               "http://127.0.0.1:8787/#/questions?id=abc123");
  assert.equal(result.app_urls.compare,
               "http://127.0.0.1:8787/#/compare?left=abc123");
});

test("an answer the app did not store offers neither of them", async () => {
  const { result } = await analyse();
  assert.equal(result.app_routes, undefined);
  assert.equal(result.app_urls, undefined);
});

// ── "Open in Kriko" tells the truth about what it did ────────────────────
//
// The button's whole job is to put the reader in front of the *app*. It got
// there by posting a route and trusting a 2xx to mean a window came to the
// front — which it does not: a 2xx means the route was recorded, and whether
// anything raised a window depends on whether a desktop shell is reading the
// sidecar's stdout. With the server started from a terminal the old code
// reported success and declined to open a tab, so the button did nothing at
// all, visibly. These four tests are the four answers it can now give.

test("a raised window means no browser tab", async () => {
  const h = loadBackground({
    routes: { "/api/focus": { accepted: true, route: "check", delivery: "raised" } },
  });
  const got = await send(h, {
    type: "OPEN_IN_APP",
    payload: { route: "check", fallbackUrl: "http://127.0.0.1:8787/#/check" },
  });
  assert.equal(got.raised, true);
  assert.deepEqual(h.state.tabsCreated, []);
});

test("no shell attached opens the tab the reader asked for", async () => {
  // The case that produced the report. The route posts fine, nothing is
  // listening for the line, and a tab is the correct answer rather than a
  // fallback the reader has to interpret.
  const h = loadBackground({
    routes: { "/api/focus": { accepted: true, route: "check", delivery: "no_shell" } },
  });
  const got = await send(h, {
    type: "OPEN_IN_APP",
    payload: { route: "check", fallbackUrl: "http://127.0.0.1:8787/#/check" },
  });
  assert.equal(got.raised, false);
  assert.equal(got.delivery, "no_shell");
  assert.deepEqual(h.state.tabsCreated, ["http://127.0.0.1:8787/#/check"]);
});

test("nothing running still falls back to a tab", async () => {
  const h = loadBackground({ offline: true });
  const got = await send(h, {
    type: "OPEN_IN_APP",
    payload: { route: "check", fallbackUrl: "http://127.0.0.1:8787/#/check" },
  });
  assert.equal(got.ok, true);
  assert.equal(got.delivery, "unreachable");
  assert.deepEqual(h.state.tabsCreated, ["http://127.0.0.1:8787/#/check"]);
});

test("a route the app refuses is reported, not opened in a tab", async () => {
  // A 422 can only mean this extension built a route the app cannot
  // navigate to. Opening a tab at that same bad route hides a defect in our
  // code behind a fallback meant for a missing app.
  const h = loadBackground({
    routes: { "/api/focus": { detail: "not a route this app could navigate to" } },
    statuses: { "/api/focus": 422 },
  });
  const got = await send(h, {
    type: "OPEN_IN_APP",
    payload: { route: "nope!", fallbackUrl: "http://127.0.0.1:8787/#/nope!" },
  });
  assert.equal(got.ok, false);
  assert.match(got.error, /not a route/);
  assert.deepEqual(h.state.tabsCreated, []);
});

test("an older extension's `raised` key still means what it said", async () => {
  // The extension ships on its own clock, so the app keeps the alias — and
  // the worker reads it when a server predating `delivery` answers.
  const h = loadBackground({
    routes: { "/api/focus": { accepted: true, route: "check", raised: true } },
  });
  const got = await send(h, {
    type: "OPEN_IN_APP",
    payload: { route: "check", fallbackUrl: "http://127.0.0.1:8787/#/check" },
  });
  assert.equal(got.raised, true);
  assert.deepEqual(h.state.tabsCreated, []);
});


// ── what the worker carries through, and what it used to drop ───────────

test("the byline and the units reach the panel", async () => {
  // Both are sent by /api/analyze and both were dropped in `toViewModel`,
  // silently. The footer printed "unknown" on every result since the byline
  // was added, and every context fact rendered without its unit — neither
  // visible from any test, because a test of this shape written against
  // `toViewModel` would have asserted whatever it happened to copy.
  const { result } = await analyse();
  assert.deepEqual(result.packs, ANALYSIS.packs);
  assert.deepEqual(result.context_units, ANALYSIS.context_units);
});

test("how sure the engine is travels with the answer", async () => {
  // The panel had two states for four situations. A verdict the client cannot
  // see is a verdict the client renders as certainty.
  const { result } = await analyse();
  assert.equal(result.verdict, "recognised");
  assert.equal(result.score, 1.0);
  assert.deepEqual(result.next_step, { action: "none", say: "" });
});

test("a doubtful answer arrives as doubtful, with what was weighed", async () => {
  const probable = {
    ...ANALYSIS, claims: [], coverage: "PROBABLE_MATCH", method: "probable",
    verdict: "probably", score: 0.51,
    considered: [{ subject_id: "s1", pack_id: "p", label: "Golf VII 1.6 TDI",
                   score: 0.51, keys: [] }],
    next_step: { action: "confirm", say: "This looks like Golf VII 1.6 TDI…",
                 subject_id: "s1" },
  };
  const { result } = await analyse({ analysis: probable });
  assert.equal(result.verdict, "probably");
  assert.equal(result.considered.length, 1);
  assert.equal(result.next_step.action, "confirm");
});

test("a missing verdict is empty rather than invented", async () => {
  // An older engine sends none. The panel must be able to tell "this engine
  // did not say" from "this engine said unrecognised" — the second is an
  // answer and the first is silence.
  const { adapter, ...rest } = ANALYSIS;
  const older = { adapter, ...rest };
  delete older.verdict;
  delete older.next_step;
  const { result } = await analyse({ analysis: older });
  assert.equal(result.verdict, "");
  assert.equal(result.next_step, null);
});
