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

test("RESEARCH_PRODUCT posts only the explicit product choice through the extension door", async () => {
  const h = loadBackground({ routes: {
    "/api/extension/research-plane": { job_id: "product-job", kind: "research" },
  } });
  const reply = await send(h, { type: "RESEARCH_PRODUCT", payload: {
    q: "Example device", allow_draft: true, cap: 0.2,
  } });
  assert.equal(reply.job.job_id, "product-job");
  assert.equal(h.state.requests.length, 1);
  const request = h.state.requests[0];
  assert.equal(request.url, "http://127.0.0.1:8787/api/extension/research-plane");
  assert.equal(request.method, "POST");
  assert.equal(request.headers["content-type"], "application/json");
  assert.equal(request.headers["X-Kriko-Extension"], MANIFEST.version);
  assert.deepEqual({ ...request.body, client_request_id: undefined },
    { q: "Example device", allow_draft: true, cap: 0.2, client_request_id: undefined });
  assert.equal(typeof request.body.client_request_id, "string");
  assert.ok(request.body.client_request_id.length <= 200);
});

test("selected subject research does not permit a draft by accident", async () => {
  const h = loadBackground({ routes: { "/api/extension/research-plane": { job_id: "j" } } });
  await send(h, { type: "RESEARCH_PRODUCT", payload: { subject_id: "s1", q: "ignored", cap: 0.2 } });
  assert.deepEqual({ ...h.state.requests[0].body, client_request_id: undefined },
    { subject_id: "s1", cap: 0.2, client_request_id: undefined });
});

test("cancellation posts to the existing job endpoint", async () => {
  const h = loadBackground({ routes: { "/api/jobs/j1/cancel": { job_id: "j1", state: "cancelled" } } });
  const reply = await send(h, { type: "CANCEL_JOB", payload: { job_id: "j1" } });
  assert.equal(reply.job.state, "cancelled");
  assert.equal(h.state.requests[0].method, "POST");
  assert.deepEqual(h.state.requests[0].body, {});
});

test("a run's question is answered through say, or retried with the answer (B147)", async () => {
  const h = loadBackground({ routes: {
    "/api/jobs/j1/say": { job_id: "j1", delivered: true },
    "/api/jobs/j1/retry": { job_id: "j2", kind: "pack_author" },
  } });
  const said = await send(h, { type: "JOB_SAY", payload: { job_id: "j1", text: "CASA" } });
  assert.equal(said.delivered, true);
  assert.deepEqual(h.state.requests[0].body, { text: "CASA" });
  const again = await send(h, { type: "JOB_RETRY",
    payload: { job_id: "j1", answers: { engine_code: "CASA" } } });
  assert.equal(again.job_id, "j2");
  assert.deepEqual(h.state.requests[1].body, { answers: { engine_code: "CASA" } });
});

const MANIFEST = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "manifest.json"), "utf8"));

// A manifest that injects statically on one invented host. The shipped one
// names no site, so the "already covered by the package" branch is reached
// through this rather than through a real site in `manifest.json`.
const STATIC_HOST = "listing.example";
const STATIC_MANIFEST = {
  ...MANIFEST,
  content_scripts: [{
    matches: [`https://*.${STATIC_HOST}/*`],
    js: ["content.js", "hover_lite/icons.js", "hover_lite/claim_card.js",
         "hover_lite/hover_lite.js"],
    run_at: "document_idle",
  }],
};

const ADAPTERS = [{
  id: "listing", site: STATIC_HOST, pack_id: "org.kriko.cars",
  match: [`*${STATIC_HOST}/ilan/*`],
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
  adapter: "listing",
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
  url: "https://www.listing.example/ilan/x",
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
  // The first POST to the *analysis*: the price memory is its own call beside it.
  const post = state.requests.find((r) => r.method === "POST" && r.url.endsWith("/api/analyze"));
  assert.equal(post.url, "http://127.0.0.1:8787/api/analyze");
});

test("the request body is the raw scrape, with nothing interpreted", async () => {
  const { state } = await analyse();
  const post = state.requests.find((r) => r.method === "POST" && r.url.endsWith("/api/analyze"));

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

// ── a site no pack reads (B149) ─────────────────────────────────────────
//
// It used to be never scraped at all, which is the reader's "in new sites
// products can't be grabbed". Now every page is read for the product it
// publishes; only a page that names none stays silent.

const ELSEWHERE = "https://elsewhere.invalid/x";
const shopPage = (product) => ({
  url: ELSEWHERE, title: "Shop", description: "",
  fields: { "ld:@type": "product", "ld:brand": "Makita" }, listing: {}, product,
});

test("a page load on a site nobody reads, naming no product, asks the app nothing", async () => {
  const h = loadBackground({
    routes: routes(), tabResponses: withTab(shopPage({ name: "Shop", typed: false })),
  });
  await assert.rejects(
    () => h.sandbox.runAnalysisForTab(1, ELSEWHERE, { auto: true }),
    (error) => error.code === "NO_ADAPTER");
  assert.ok(!h.state.requests.some((r) => r.method === "POST"));
  assert.equal(h.state.badge[1], "", "an ordinary page gets no badge");
});

test("a product page on a site nobody reads is asked about by its name", async () => {
  const h = loadBackground({
    routes: routes(),
    tabResponses: withTab(shopPage({ name: "Makita DHP484Z Combi Drill", typed: true })),
  });
  await h.sandbox.runAnalysisForTab(1, ELSEWHERE, { auto: true });
  const post = h.state.requests.find((r) => r.method === "POST");
  assert.equal(post.body.product_name, "Makita DHP484Z Combi Drill");
  assert.equal(post.body.fields["ld:brand"], "Makita");
  const ask = h.state.tabMessages.find((m) => m.message.type === "GET_SCRAPE");
  assert.deepEqual(ask.message.labels, [], "no site adapter, no site labels");
  // ...and the page's own label/value shapes ride along, which is the whole
  // of what a model is given to work out this site's reading structure from
  // (`app/siteinfer.py`). Nothing else on that request carries them.
  assert.equal(ask.message.explore, true,
    "a page nothing claims must be scraped for its own labels");
});

test("a page an adapter claims keeps the scrape it always had", async () => {
  const { state } = await analyse();
  const ask = state.tabMessages.find((m) => m.message.type === "GET_SCRAPE");
  // The declared labels are already the pack's words. Exploring as well would
  // put every other short string on the page on the wire for nothing, and it
  // would change the payload of every page that already worked.
  assert.equal(ask.message.explore, false);
  assert.deepEqual(ask.message.labels, ADAPTERS[0].labels);
});

test("a product nothing installed knows comes back with its own name to research", async () => {
  const h = loadBackground({
    routes: routes({ readable: false, reason: "unknown_product",
                     product: { name: "Bosch HSG 7584 B 1" } }),
    tabResponses: withTab(shopPage({ name: "Bosch HSG 7584 B 1", typed: true })),
  });
  await assert.rejects(
    () => h.sandbox.runAnalysisForTab(1, ELSEWHERE),
    (error) => error.code === "UNKNOWN_PRODUCT" && error.productName === "Bosch HSG 7584 B 1");
  const stored = h.state.session[`krikoAnalysis:${ELSEWHERE}`]
    || Object.values(h.state.session).find((v) => v && v.code === "UNKNOWN_PRODUCT");
  assert.equal(stored.code, "UNKNOWN_PRODUCT");
  assert.equal(stored.productName, "Bosch HSG 7584 B 1");
  assert.equal(h.state.badge[1], "?", "a question, not a red alarm");
});

test("the reader's click on an untyped page still asks, by the page's name", async () => {
  const h = loadBackground({
    routes: routes(), tabResponses: withTab(shopPage({ name: "Kelebek Duvar Sticker", typed: false })),
  });
  await h.sandbox.runAnalysisForTab(1, ELSEWHERE);
  const post = h.state.requests.find((r) => r.method === "POST");
  assert.equal(post.body.product_name, "Kelebek Duvar Sticker");
});

// ── the toolbar click on a site Kriko has never run on ─────────────────

test("the first click on an unknown site asks once for every site, then opens the panel there", async () => {
  let injected = 0;
  const h = loadBackground({
    routes: routes(),
    tabResponses: { TOGGLE_HOVER_LITE: () => { if (!injected) throw new Error("no receiver"); return { ok: true }; } },
  });
  const real = h.sandbox.chrome.scripting.executeScript;
  h.sandbox.chrome.scripting.executeScript = async (opts) => {
    if (opts && opts.files) injected += 1;
    return real(opts);
  };
  await h.clickListeners[0]({ id: 7, url: "https://www.mediamarkt.example/p/1" });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(h.state.permissionRequests, [["https://*/*"]]);
  assert.equal(injected, 1, "the click is the grant for this tab: the panel goes in now");
  assert.equal(h.state.tabMessages.filter((m) => m.message.type === "TOGGLE_HOVER_LITE").length, 2);
});

test("a click on the site the package already runs on never prompts", async () => {
  const h = loadBackground({ tabResponses: { TOGGLE_HOVER_LITE: { ok: true } },
                            manifest: STATIC_MANIFEST });
  await h.clickListeners[0]({ id: 7, url: `https://www.${STATIC_HOST}/ilan/1` });
  assert.deepEqual(h.state.permissionRequests, []);
});

test("once every site is granted, one registration covers them, skipping hosts already covered", async () => {
  const h = loadBackground({ routes: routes(), grantedOrigins: ["https://*/*"],
                            manifest: STATIC_MANIFEST });
  await h.sandbox.syncSites({ fresh: true });
  const any = h.state.registered.find((s) => s.id === "kriko-anysite");
  assert.ok(any, "no every-site registration");
  assert.deepEqual(any.matches, ["https://*/*"]);
  assert.ok(any.excludeMatches.includes(`https://*.${STATIC_HOST}/*`),
    "the manifest's own site must not run the panel twice");
  await h.sandbox.syncSites({ fresh: true });
  assert.equal(h.state.registered.filter((s) => s.id === "kriko-anysite").length, 1);
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
  // The panel renders the damage and equipment panels from this, and
  // (extension-8/extension-11, B145 audit) the page's own title, which the
  // scrape already carried separately from `listing` and which the stored
  // entry used to drop on the floor.
  assert.deepEqual(entry.listing, { ...SCRAPE.listing, title: SCRAPE.title });
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
  const post = state.requests.find((r) => r.method === "POST" && r.url.endsWith("/api/analyze"));
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

test("the small toolbar icon reflects a live app without replacing a page's risk badge", async () => {
  const h = loadBackground({ routes: { "/api/health": { ok: true, version: "1.0.0" } } });
  h.state.badge[1] = "2";
  assert.equal(h.state.alarms["kriko-connection"].periodInMinutes, 1);
  h.startupListeners[0]();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.state.toolbarIcon[16], "assets/icons/icon-16.png");
  assert.match(h.state.toolbarTitle, /connected.*open the panel/i);
  assert.equal(h.state.badge[1], "2");
  assert.ok(h.state.requests.some((request) =>
    request.url === "http://127.0.0.1:8787/api/health"));
});

test("the toolbar icon becomes muted when the app stops answering", async () => {
  const h = loadBackground({ offline: true });
  h.alarmListeners[0]({ name: "kriko-connection" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.state.toolbarIcon[16], "assets/icons/icon-offline-16.png");
  assert.match(h.state.toolbarTitle, /app is not running/i);
});

// An alarm is registered once and then lives in Chrome, not in the worker. So
// the second worker start below is the ordinary case this test exists for:
// MV3 stops a worker after about thirty seconds idle, and every start runs the
// top-level block again. `alarms.create` replaces an alarm of the same name
// and a replacement restarts its clock, so a worker that recreated its alarms
// on every start would push the 30-minute site sync back every few seconds and
// it would never come due. The distinction is invisible in one worker's
// lifetime, which is exactly why it needs a second one.
test("a restarted worker leaves a live alarm's clock alone", async () => {
  const first = loadBackground({});
  assert.deepEqual(first.state.alarmCreates.slice().sort(),
    ["kriko-connection", "kriko-prices", "kriko-site-sync"]);

  const second = loadBackground({ alarms: first.state.alarms });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(second.state.alarmCreates, [],
    "the restarted worker recreated an alarm that was already running");
  assert.equal(second.state.alarms["kriko-site-sync"].periodInMinutes, 30);

  // An alarm Chrome no longer holds is the one case that has to be recreated,
  // or a worker restarted after a browser update would go on syncing never.
  const third = loadBackground({ alarms: {
    "kriko-connection": { periodInMinutes: 1 }, "kriko-prices": { periodInMinutes: 30 } } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(third.state.alarmCreates, ["kriko-site-sync"]);
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

test("a phrase with no host in it is refused instead of becoming http://<phrase>", async () => {
  // extension-20: the old normaliser prefixed http:// onto any string, so
  // "not a url" was saved as "http://not a url" and blamed on the app being
  // down instead of being told it was never a valid address.
  const h = loadBackground({ routes: { "/api/health": {} } });
  await send(h, { type: "SET_API_BASE", payload: { url: "http://127.0.0.1:8787" } });
  const reply = await send(h, { type: "SET_API_BASE", payload: { url: "not a url" } });
  assert.equal(reply.ok, false);
  assert.match(reply.error, /not a url/i);
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
    analysis: { ...ANALYSIS, lookup_id: "abc123", compare_ready: true } });
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

test("Compare is not offered before there are two saved checks (extension-16)", async () => {
  // Compare's own empty state says "needs two saved checks", so a first-ever
  // analysis handing back a compare route just opens the app to that dead
  // end. The app tells us when there is something to compare against.
  const { result } = await analyse({
    analysis: { ...ANALYSIS, lookup_id: "abc123", compare_ready: false } });
  assert.equal("compare" in result.app_routes, false);
  assert.equal("compare" in (result.app_urls || {}), false);
  assert.equal(result.app_routes.questions, "questions/abc123");
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

test("no shell attached says the window is not connected and opens no tab", async () => {
  // The engine answers, but nothing is reading its stdout to raise a window.
  // The fallback tab used to open here; it pointed at the retired Svelte
  // hash routes, so the reader got a page that no longer exists. The answer
  // is now a named error the panel can say, and no tab.
  const h = loadBackground({
    routes: { "/api/focus": { accepted: true, route: "check", delivery: "no_shell" } },
  });
  const got = await send(h, {
    type: "OPEN_IN_APP",
    payload: { route: "check", fallbackUrl: "http://127.0.0.1:8787/#/check" },
  });
  assert.equal(got.ok, false);
  assert.equal(got.code, "DESKTOP_NOT_CONNECTED");
  assert.equal(got.delivery, "no_shell");
  assert.deepEqual(h.state.tabsCreated, []);
});

test("nothing running is reported, not opened in a dead tab", async () => {
  // extension-2 (B145 audit): a *transport* failure means there is no engine
  // on the other end at all, so the old fallback opened a browser tab onto
  // ERR_CONNECTION_REFUSED — a tab with nothing on it and nothing the reader
  // can do about it. "no_shell" (above) is different: the engine answered,
  // it just has no window to raise, and a tab is the right answer there.
  const h = loadBackground({ offline: true });
  const got = await send(h, {
    type: "OPEN_IN_APP",
    payload: { route: "check", fallbackUrl: "http://127.0.0.1:8787/#/check" },
  });
  assert.equal(got.ok, false);
  assert.equal(got.code, "APP_NOT_RUNNING");
  assert.deepEqual(h.state.tabsCreated, []);
});

test("an app that is open but never answers is named as hung, not as closed", async () => {
  // fetch has no timeout of its own: a wedged app held the panel's spinner
  // forever. The worker's clock ends it, and the reader is told the app is
  // open-but-stuck — "open the Kriko app" would be advice they already took.
  const h = loadBackground({ hung: true });
  const got = await send(h, {
    type: "OPEN_IN_APP",
    payload: { route: "check", fallbackUrl: "http://127.0.0.1:8787/#/check" },
  });
  assert.equal(got.ok, false);
  assert.equal(got.code, "APP_NOT_RESPONDING");
  assert.match(got.error, /did not answer/);
  assert.deepEqual(h.state.tabsCreated, []);
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

test("a second Refresh reuses the cache, but a fresh one re-asks the engine", async () => {
  // extension-3 (B145 audit): every request served the 6-hour local cache
  // once the scrape and installed packs matched, with no way to say "no,
  // ask again" — even the reader pressing Refresh got the stale answer, and
  // even a stopped engine never showed up in it.
  const h = loadBackground({ routes: routes(), tabResponses: withTab() });
  await h.sandbox.runAnalysisForTab(1, SCRAPE.url);
  // Only the analysis is counted: the price memory is asked for beside it.
  const analyses = () => h.state.requests
    .filter((r) => r.method === "POST" && r.url.endsWith("/api/analyze")).length;
  const postsAfterFirst = analyses();

  await h.sandbox.runAnalysisForTab(1, SCRAPE.url);
  assert.equal(
    analyses(), postsAfterFirst,
    "an ordinary re-run served the cache and asked nothing new"
  );

  await h.sandbox.runAnalysisForTab(1, SCRAPE.url, { fresh: true });
  assert.equal(
    analyses(), postsAfterFirst + 1,
    "fresh:true skipped the cache and asked the engine again"
  );
});

// The answer cache is the one part of a run that survives the browser
// session: the result itself lives in session storage, which Chrome clears,
// and the cache lives in storage.local, which it does not. That makes the
// cache's key a record of the reader's browsing whenever the key is the
// address, and the reader's browsing is the thing this product exists to keep
// to themselves.
test("the durable cache is keyed by a digest, not by the page's address", async () => {
  const h = loadBackground({ routes: routes(), tabResponses: withTab() });
  await h.sandbox.runAnalysisForTab(1, SCRAPE.url);

  const cached = Object.keys(h.state.local)
    .filter((key) => key.startsWith("kriko_cached_result_"));
  assert.equal(cached.length, 1,
    `expected one cache entry, found ${JSON.stringify(Object.keys(h.state.local))}`);
  assert.ok(!cached[0].includes(SCRAPE.url),
    "the cache key still spells out the page the reader visited");
  assert.ok(!cached[0].includes(new URL(SCRAPE.url).hostname),
    "the cache key still names the site");

  // And the digest still finds the entry: the second run is served from it,
  // which is the property the address key had.
  const analyses = () => h.state.requests.filter(
    (request) => request.method === "POST" && request.url.endsWith("/api/analyze")).length;
  const posts = analyses();
  await h.sandbox.runAnalysisForTab(1, SCRAPE.url);
  assert.equal(analyses(), posts, "the digest key missed an entry the address key used to find");
});

test("a pack update changes the cache signature even when the scrape has not", async () => {  // The signature used to hash only the scrape, so a pack shipping a new
  // claim for the same listing could not reach it: the cache would keep
  // serving the pre-update answer for up to 6 hours. `_scrapeSignature` now
  // takes the adapters list too, so a version bump on the same scrape must
  // change what comes out.
  const h = loadBackground({ routes: routes(), tabResponses: withTab() });
  const before = h.sandbox._scrapeSignature(SCRAPE, ADAPTERS);
  const after = h.sandbox._scrapeSignature(
    SCRAPE, ADAPTERS.map((a) => ({ ...a, version: "0.2.0" })));
  assert.notEqual(before, after);
});

test("changing sold-product identity invalidates the analysis cache", () => {
  const h = loadBackground({ routes: routes(), tabResponses: withTab() });
  const before = h.sandbox._scrapeSignature({ ...SCRAPE, product: { name: "Host" } }, ADAPTERS);
  const after = h.sandbox._scrapeSignature({ ...SCRAPE, product: { name: "Filter for Host" } }, ADAPTERS);
  assert.notEqual(before, after);
  const legacy = h.sandbox._stableHash({ title: SCRAPE.title || "", fields: SCRAPE.fields || {},
    packs: ADAPTERS.map((a) => `${a.pack_id}@${a.version || ""}`).sort() });
  assert.notEqual(after, legacy);
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

// ── B150: the listing's facts travel with "Research this product" ───────

test("research from a listing sends the page's own facts and description (B150)", async () => {
  const h = loadBackground({
    routes: { ...routes(), "/api/extension/research-plane": { job_id: "q1", kind: "quick_look" } },
    tabResponses: withTab(),
  });
  await h.sandbox.runAnalysisForTab(1, SCRAPE.url);
  h.state.requests.length = 0;
  await send(h, { type: "RESEARCH_PRODUCT", payload: {
    q: "2014 Volkswagen Golf", allow_draft: true, url: SCRAPE.url,
  } });
  const body = h.state.requests[0].body;
  assert.deepEqual(body.facts, SCRAPE.fields);
  assert.equal(body.description, SCRAPE.description);
  assert.equal(body.url, SCRAPE.url);
});

test("research on a page never read sends its name alone (B150)", async () => {
  const h = loadBackground({ routes: { "/api/extension/research-plane": { job_id: "q1" } } });
  await send(h, { type: "RESEARCH_PRODUCT", payload: {
    q: "Example device", allow_draft: true, url: "https://shop.example/p/1",
  } });
  assert.deepEqual({ ...h.state.requests[0].body, client_request_id: undefined },
    { q: "Example device", allow_draft: true, url: "https://shop.example/p/1",
      client_request_id: undefined });
});

test("uncertain research retries retain one durable id and confirmed receipt clears it", async () => {
  let acceptedJob = null;
  let loseResponses = 3;
  const h = loadBackground({ routes: {
    "/api/extension/research-plane": (body) => {
      if (!acceptedJob) acceptedJob = { job_id: "accepted-once", request_id: body.client_request_id };
      assert.equal(body.client_request_id, acceptedJob.request_id);
      if (loseResponses > 0) {
        loseResponses -= 1;
        throw new TypeError("connection reset after server accepted request");
      }
      return acceptedJob;
    },
  } });
  const payload = { q: "Example device", allow_draft: true };
  const first = await send(h, { type: "RESEARCH_PRODUCT", payload });
  assert.equal(first.ok, false);
  assert.equal(h.state.requests.length, 3);
  const firstId = h.state.requests[0].body.client_request_id;
  assert.ok(firstId);
  assert.ok(h.state.requests.every((row) => row.body.client_request_id === firstId));
  const pending = h.state.local.krikoResearchIntentsV1;
  assert.equal(pending.length, 1);
  assert.equal(pending[0].body.client_request_id, firstId);

  // Restart the worker while preserving Chrome's durable local storage.
  const restarted = loadBackground({ localState: h.state.local, routes: {
    "/api/extension/research-plane": (body) => {
      assert.equal(body.client_request_id, acceptedJob.request_id);
      return acceptedJob;
    },
  } });
  const recovered = await send(restarted, { type: "RESEARCH_PRODUCT", payload });
  assert.equal(recovered.job.job_id, "accepted-once");
  assert.equal(restarted.state.requests[0].body.client_request_id, firstId);
  assert.deepEqual(restarted.state.local.krikoResearchIntentsV1, []);

  await send(restarted, { type: "RESEARCH_PRODUCT", payload });
  assert.notEqual(restarted.state.requests[1].body.client_request_id, firstId,
    "a deliberate new click after a receipt starts a fresh intent");
});

test("changed research input gets a different client request id", async () => {
  const h = loadBackground({ routes: {
    "/api/extension/research-plane": (body) => ({ job_id: body.client_request_id }),
  } });
  await send(h, { type: "RESEARCH_PRODUCT", payload: { q: "First product" } });
  await send(h, { type: "RESEARCH_PRODUCT", payload: { q: "Second product" } });
  assert.notEqual(h.state.requests[0].body.client_request_id,
    h.state.requests[1].body.client_request_id);
});

test("quick follow-up writes carry stable request ids", async () => {
  const h = loadBackground({ routes: {
    "/api/extension/quick-look/j1/ask": (body) => ({ job_id: body.client_request_id }),
    "/api/extension/quick-looks/j1/pack": (body) => ({ job_id: body.client_request_id }),
  } });
  await send(h, { type: "QUICK_ASK", payload: { job_id: "j1", q: "Why?" } });
  await send(h, { type: "QUICK_TO_PACK", payload: { job_id: "j1" } });
  assert.equal(typeof h.state.requests[0].body.client_request_id, "string");
  assert.equal(h.state.requests[0].body.q, "Why?");
  assert.equal(typeof h.state.requests[1].body.client_request_id, "string");
});

// ── B152.4: an answer that follows the knowledge ─────────────────────────

test("a refreshed answer replaces the listing's entry, which is what repaints the panel", async () => {
  const url = "https://market.invalid/listing/42";
  const claim = {
    claim_id: "c2", pack_id: "p", title: "Added by the agent", severity: "high",
    domain: "mech", sources: [],
  };
  const h = loadBackground({
    routes: {
      "/api/lookup/abc/refresh": {
        lookup_id: "abc", refreshed: true,
        response: { lookup_id: "abc", claims: [claim], subjects: [], packs: [] },
      },
    },
  });
  h.state.session["kriko_result_" + url] = {
    ok: true, result: { lookup_id: "abc", claims: [] }, listing: { title: "x" },
  };
  const got = await send(h, { type: "REFRESH_ANSWER", payload: { url, lookupId: "abc" } });
  assert.equal(got.ok, true);
  const entry = h.state.session["kriko_result_" + url];
  assert.deepEqual(entry.result.claims.map((c) => c.title), ["Added by the agent"]);
  assert.equal(entry.result.lookup_id, "abc");
  // The listing extras from the scrape survive; only the answer changed.
  assert.equal(entry.listing.title, "x");
  const posted = h.state.requests.find((r) => r.url.endsWith("/api/lookup/abc/refresh"));
  assert.equal(posted.method, "POST");
});

test("an answer the app kept as it was leaves the entry alone", async () => {
  const url = "https://market.invalid/listing/42";
  const h = loadBackground({
    routes: { "/api/lookup/abc/refresh": { lookup_id: "abc", refreshed: false } },
  });
  const before = { ok: true, result: { lookup_id: "abc", claims: [] } };
  h.state.session["kriko_result_" + url] = before;
  const got = await send(h, { type: "REFRESH_ANSWER", payload: { url, lookupId: "abc" } });
  assert.equal(got.ok, true);
  assert.equal(got.result, null);
  assert.equal(h.state.session["kriko_result_" + url], before);
});

// ── learn this page, and the agents the panel can pick ────────────────────

test("LEARN_PAGE sends the tab's own snapshot and the picked agent to the app", async () => {
  const h = loadBackground({
    routes: { "/api/sites/learn": { host: "shop.example", mode: "local", learned: true, grabs: [] } },
    tabResponses: {
      GET_SCRAPE: { ok: true, payload: {
        url: "https://shop.example/p/1", title: "Acme Roadster | Shop",
        description: "d", fields: { Marka: "Acme" }, product: { name: "Acme Roadster", typed: true },
      } },
    },
  });
  const reply = await send(h, { type: "LEARN_PAGE", payload: { agent: "claude" } });
  assert.equal(reply.ok, true);
  assert.equal(reply.lesson.learned, true);
  const ask = h.state.tabMessages.find((m) => m.message.type === "GET_SCRAPE");
  assert.equal(ask.message.explore, true, "the page's own labels are what an agent learns from");
  const request = h.state.requests[0];
  assert.equal(request.url, "http://127.0.0.1:8787/api/sites/learn");
  assert.equal(request.body.agent, "claude");
  assert.deepEqual(request.body.fields, { Marka: "Acme" });
  assert.equal(request.body.product.name, "Acme Roadster");
});

test("LEARN_PAGE says so when the page cannot be read, and asks the app nothing", async () => {
  const h = loadBackground({ tabResponses: { GET_SCRAPE: { ok: false } } });
  const reply = await send(h, { type: "LEARN_PAGE", payload: {} });
  assert.equal(reply.ok, false);
  assert.match(reply.error, /could not read this page/);
  assert.equal(h.state.requests.length, 0);
});

test("AGENTS offers only what the app can run now", async () => {
  const h = loadBackground({ routes: { "/api/agent-market": {
    chosen: "local",
    agents: [
      { id: "local", label: "Local agent", kind: "local", state: "ready", action: "use", local: true },
      { id: "claude", label: "Claude Code", kind: "cli", state: "ready", action: "use" },
      { id: "codex", label: "Codex", kind: "cli", state: "not_installed", action: "install" },
      { id: "cursor", label: "Cursor", kind: "cli", state: "ready", action: "connect" },
    ],
  } } });
  const reply = await send(h, { type: "AGENTS" });
  assert.equal(reply.chosen, "local");
  assert.deepEqual(reply.agents.map((one) => one.id), ["local", "claude"]);
});

test("RESEARCH_PRODUCT carries the agent picked in the panel, and nothing else about it", async () => {
  const h = loadBackground({ routes: { "/api/extension/research-plane": { job_id: "j" } } });
  await send(h, { type: "RESEARCH_PRODUCT", payload: { q: "Acme", allow_draft: true, harness: "claude" } });
  assert.equal(h.state.requests[0].body.harness, "claude");
});
