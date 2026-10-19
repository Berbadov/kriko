// The worker's side of the reader as a buyer: the price memory beside the
// analysis, the look before paying, the buttons, and the timer that tells.
const test = require("node:test");
const assert = require("node:assert");

const { loadBackground, send } = require("./background_harness.js");

const URL_ = "https://www.listing.example/ilan/x";
const SCRAPE = {
  url: URL_, title: "Kettle X200", description: "Fast boil.",
  fields: { "ld:price": "49.90", "ld:priceCurrency": "EUR" },
  product: { name: "Kettle X200", typed: true },
  listing: { damage_info: null, equipment: {} },
};
const ADAPTERS = [{ id: "listing", site: "listing.example", pack_id: "p", match: ["*listing.example/ilan/*"], labels: [] }];
const ANALYSIS = { adapter: "listing", identity: {}, context: {}, claims: [], coverage: "NO_CLAIMS",
  method: "exact", flags: [], unmapped_labels: [], packs: [], verdict: "recognised", score: 1 };
const BUYER = { price: { verdict: "first", price: 49.9, currency: "EUR", summary: "First time." },
  watch: null, audit: null, fit: null, profile: false, name: "Kettle X200" };

test("a product page is remembered beside the analysis, and the answer is stored under its own key", async () => {
  const h = loadBackground({
    routes: { "/api/adapters": ADAPTERS, "/api/analyze": ANALYSIS, "/api/buyer/page": BUYER },
    tabResponses: { GET_SCRAPE: { ok: true, payload: SCRAPE } } });
  await h.sandbox.runAnalysisForTab(1, URL_);
  await new Promise((resolve) => setImmediate(resolve));
  const call = h.state.requests.find((r) => r.url.endsWith("/api/buyer/page"));
  assert.deepEqual(call.body.fields, SCRAPE.fields);
  assert.equal(call.body.product_name, "Kettle X200");
  assert.equal(call.body.url, URL_);
  const stored = h.state.session["kriko_buyer_" + URL_];
  assert.equal(stored.ok, true);
  assert.equal(stored.buyer.price.verdict, "first");
});

test("an app that cannot answer the price memory costs the reader nothing else", async () => {
  const h = loadBackground({
    routes: { "/api/adapters": ADAPTERS, "/api/analyze": ANALYSIS },
    tabResponses: { GET_SCRAPE: { ok: true, payload: SCRAPE } } });
  const result = await h.sandbox.runAnalysisForTab(1, URL_);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(result.adapter, "listing");
  assert.equal(h.state.session["kriko_buyer_" + URL_].ok, false);
});

const CART = { ok: true, items: [{ name: "Kettle X200", price: "49,90", currency: "€" }], text: "Free returns" };

function pageLoaded(h, url) {
  return new Promise((resolve) => {
    h.messageListeners[0]({ type: "PAGE_LOADED", payload: { url } }, { tab: { id: 1 } }, resolve);
  });
}

test("a cart page gets a look before paying, and a worrying verdict reaches the page", async () => {
  const verdict = { verdict: "check", findings: [{ severity: "check", message: "Cheaper elsewhere" }], headline: "Cheaper elsewhere" };
  const h = loadBackground({
    routes: { "/api/adapters": ADAPTERS, "/api/prices/checkout": verdict },
    tabResponses: { GET_CART: CART, GET_SCRAPE: { ok: false, error: "no" }, SHOW_GUARD: { ok: true } } });
  await pageLoaded(h, "https://shop.example/checkout");
  await new Promise((resolve) => setImmediate(resolve));
  const call = h.state.requests.find((r) => r.url.endsWith("/api/prices/checkout"));
  assert.equal(call.body.url, "https://shop.example/checkout");
  assert.deepEqual(call.body.items, CART.items);
  assert.equal(call.body.text, "Free returns");
  const shown = h.state.tabMessages.find((m) => m.message.type === "SHOW_GUARD");
  assert.equal(shown.message.result.verdict, "check");
});

test("a verdict of go is kept quietly and the page is not interrupted", async () => {
  const h = loadBackground({
    routes: { "/api/adapters": ADAPTERS, "/api/prices/checkout": { verdict: "go", findings: [] } },
    tabResponses: { GET_CART: CART, GET_SCRAPE: { ok: false } } });
  await pageLoaded(h, "https://shop.example/cart");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.state.tabMessages.some((m) => m.message.type === "SHOW_GUARD"), false);
  assert.equal(h.state.session["kriko_guard_https://shop.example/cart"].result.verdict, "go");
});

test("the look before paying can be switched off, and a product page never triggers it", async () => {
  const off = loadBackground({
    localState: { buyerGuard: false },
    routes: { "/api/adapters": ADAPTERS, "/api/prices/checkout": { verdict: "stop", findings: [] } },
    tabResponses: { GET_CART: CART, GET_SCRAPE: { ok: false } } });
  await pageLoaded(off, "https://shop.example/checkout");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(off.state.requests.some((r) => r.url.endsWith("/api/prices/checkout")), false);

  const product = loadBackground({
    routes: { "/api/adapters": ADAPTERS, "/api/prices/checkout": { verdict: "stop", findings: [] } },
    tabResponses: { GET_SCRAPE: { ok: false } } });
  await pageLoaded(product, "https://shop.example/p/cartridge-12");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(product.state.requests.some((r) => r.url.endsWith("/api/prices/checkout")), false);
});

test("the panel's buttons are forwarded to the app's own routes, trimmed", async () => {
  const h = loadBackground({ routes: {
    "/api/prices/watches": { watch_id: "w1", target: 40 },
    "/api/buyer/purchases": { purchase_id: "p1", due: [] },
    "/api/buyer/purchases/p1/answer": { purchase_id: "p1", verdict: "regret" },
    "/api/buyer/purchases/p1/snooze": { snoozed: "p1" },
    "/api/buyer/pick": { picked: { name: "A" }, ranked: [] },
    "/api/buyer/advice": { job_id: "j1" },
    "/api/buyer/fit": { profile: true, items: [] },
  } });
  const watch = await send(h, { type: "BUYER_WATCH", payload: { url: URL_, name: "Kettle", target: "40", price: 49.9, currency: "EUR" } });
  assert.equal(watch.ok, true);
  assert.deepEqual(h.state.requests.at(-1).body, { url: URL_, name: "Kettle", target: "40", drop_pct: null, price: 49.9, currency: "EUR" });
  await send(h, { type: "BUYER_BOUGHT", payload: { name: "Kettle", url: URL_, price: 49.9, currency: "EUR" } });
  assert.deepEqual(h.state.requests.at(-1).body, { name: "Kettle", url: URL_, price: 49.9, currency: "EUR" });
  const answer = await send(h, { type: "BUYER_ANSWER", payload: { purchase_id: "p1", verdict: "regret", reason: "lid cracked" } });
  assert.equal(answer.verdict, "regret");
  assert.deepEqual(h.state.requests.at(-1).body, { verdict: "regret", reason: "lid cracked" });
  assert.equal((await send(h, { type: "BUYER_SNOOZE", payload: { purchase_id: "p1" } })).snoozed, "p1");
  assert.equal((await send(h, { type: "BUYER_PICK", payload: {} })).picked.name, "A");
  assert.deepEqual(h.state.requests.at(-1).body, { queue: true });
  const advice = await send(h, { type: "BUYER_ADVICE", payload: { mode: "debate" } });
  assert.equal(advice.job_id, "j1");
  assert.deepEqual(h.state.requests.at(-1).body, { queue: true, mode: "debate", question: "" });
  const fit = await send(h, { type: "BUYER_FIT", payload: { items: Array.from({ length: 80 }, () => ({ name: "x" })) } });
  assert.equal(fit.profile, true);
  assert.equal(h.state.requests.at(-1).body.items.length, 60);
});

test("an app that refuses a button is reported as a refusal, not as no app", async () => {
  const h = loadBackground({ routes: { "/api/buyer/pick": { detail: "no saved checks" } },
    statuses: { "/api/buyer/pick": 422 } });
  const reply = await send(h, { type: "BUYER_PICK", payload: {} });
  assert.equal(reply.ok, false);
  assert.equal(reply.status, 422);
});

test("the timer asks the app to re-read what is due, then tells once about what crossed", async () => {
  const alerts = { items: [{ alert_id: "a1", name: "Kettle", price: 39, currency: "EUR", was_price: 50, url: URL_ }] };
  const h = loadBackground({ routes: {
    "/api/prices/sweep": { job_id: "", due: 0 },
    "/api/prices/alerts": alerts,
    "/api/buyer/purchases": { due: [{ purchase_id: "p9", name: "Blender" }] },
  } });
  const made = [];
  h.sandbox.chrome.notifications = { create(id, options) { made.push({ id, options }); }, onClicked: { addListener() {} } };
  await h.sandbox.checkBuyerAlerts();
  assert.ok(h.state.requests.some((r) => r.url.endsWith("/api/prices/sweep") && r.method === "POST"));
  assert.equal(h.state.badge[undefined], "↓");
  assert.deepEqual(made.map((one) => one.id), ["kriko-alert:a1", "kriko-due:p9"]);
  assert.match(made[0].options.message, /Kettle: 39 EUR \(was 50\)/);
  await h.sandbox.checkBuyerAlerts();
  assert.equal(made.length, 2, "the same alert is not announced twice");
});

test("without the notifications permission a drop still marks the toolbar button", async () => {
  const h = loadBackground({ routes: {
    "/api/prices/sweep": { job_id: "", due: 0 },
    "/api/prices/alerts": { items: [{ alert_id: "a1", name: "K", price: 1, currency: "", url: URL_ }] },
    "/api/buyer/purchases": { due: [] },
  } });
  await h.sandbox.checkBuyerAlerts();
  assert.equal(h.state.badge[undefined], "↓");
});

test("the extension asks for notifications only as an optional permission", () => {
  const manifest = require("../manifest.json");
  assert.ok(!manifest.permissions.includes("notifications"),
    "a required permission would have the browser switch the extension off at the next update");
  assert.deepEqual(manifest.optional_permissions, ["notifications"]);
});

const DUE = { due: [{ purchase_id: "p1", name: "Blender" }, { purchase_id: "p2", name: "Lamp" }] };

function dueWorker(extra = {}) {
  return loadBackground({
    routes: { "/api/adapters": ADAPTERS, "/api/analyze": ANALYSIS, "/api/buyer/page": BUYER,
      "/api/buyer/purchases": DUE, ...extra },
    tabResponses: { GET_SCRAPE: { ok: true, payload: SCRAPE }, KRIKO_DUE_NUDGE: { ok: true } } });
}
const nudges = (h) => h.state.tabMessages.filter((m) => m.message.type === "KRIKO_DUE_NUDGE");
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("a page Kriko reads is where a due purchase is asked about, one at a time and not twice in a day", async () => {
  const h = dueWorker();
  await h.sandbox.runAnalysisForTab(1, URL_, { auto: true });
  await settle();
  assert.equal(nudges(h).length, 1);
  assert.equal(nudges(h)[0].message.purchase.purchase_id, "p1");
  assert.equal(nudges(h)[0].message.count, 2);
  await h.sandbox.runAnalysisForTab(1, URL_, { auto: true, fresh: true });
  await settle();
  assert.equal(nudges(h).length, 2, "the second purchase is asked about next, never the first again");
  assert.equal(nudges(h)[1].message.purchase.purchase_id, "p2");
  await h.sandbox.runAnalysisForTab(1, URL_, { auto: true, fresh: true });
  await settle();
  assert.equal(nudges(h).length, 2, "both were asked about today");
});

test("pressing the button on a page is the reader's own ask, and is not interrupted by a question", async () => {
  const h = dueWorker();
  await h.sandbox.runAnalysisForTab(1, URL_, { auto: false });
  await settle();
  assert.equal(nudges(h).length, 0);
});

test("with no purchase due, no question is asked", async () => {
  const h = dueWorker({ "/api/buyer/purchases": { due: [] } });
  await h.sandbox.runAnalysisForTab(1, URL_, { auto: true });
  await settle();
  assert.equal(nudges(h).length, 0);
});
