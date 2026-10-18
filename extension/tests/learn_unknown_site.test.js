// "Learn this page" on a site nothing reads. The reader's report: the button
// did not work and did not come up by itself on unknown pages. It lived only
// inside the Research card, so a page Kriko could not read offered "Add this
// site" (a trip to the app) and nothing else, and the panel waited for a toolbar
// press on pages the reader had no reason to press it on.
const test = require("node:test");
const assert = require("node:assert/strict");
const { loadPanel } = require("./hover_lite_harness.js");
const { loadBackground } = require("./background_harness.js");

const AGENTS = [
  { id: "local", label: "Local agent", kind: "local" },
  { id: "claude", label: "Claude Code", kind: "cli" },
];

function worker(extra = {}) {
  return (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local", budget_usd: 0 } };
    if (message.type === "AGENTS") return { ok: true, chosen: "local", agents: AGENTS };
    if (extra[message.type]) return extra[message.type](message);
    return { ok: true };
  };
}

const noAdapter = (extra = {}) => ({ ok: false, code: "NO_ADAPTER", hostKnown: false, ...extra });

function openUnread(analyzeResponse, workerResponse = worker()) {
  const p = loadPanel({ analyzeResponse, workerResponse });
  p.openPanel();
  p.click(".lite-cta");
  return p;
}

const verdict = (p) => p.shadow().querySelector(".lite-verdict");

test("a site nothing reads offers Learn this page on the card, with the agent to use", () => {
  const p = openUnread(noAdapter());
  assert.equal(verdict(p).dataset.verdict, "no-adapter");
  assert.equal(verdict(p).querySelector(".lite-learn-btn").textContent, "Learn this page");
  assert.deepEqual([...verdict(p).querySelectorAll(".lite-agent-select option")].map((o) => o.value),
    ["local", "claude"]);
  assert.ok(verdict(p).querySelector(".lite-site-add"), "the app's Sites screen is still one press away");
});

test("pressing it learns the page, then the worker takes the new reading in and the page is asked again", () => {
  const p = openUnread(noAdapter(), worker({
    LEARN_PAGE: () => ({ ok: true, lesson: { mode: "local", learned: true, host: "shop.example", name: "Acme Roadster",
      grabs: [{ as: "brand", value: "Acme", kind: "identity" }] } }),
  }));
  const before = p.sent.filter((m) => m.type === "ANALYZE").length;
  p.click(".lite-learn-btn");

  const types = p.sent.map((m) => m.type);
  assert.ok(types.includes("LEARN_PAGE"));
  assert.ok(types.indexOf("KRIKO_SYNC_SITES") > types.indexOf("LEARN_PAGE"));
  const asks = p.sent.filter((m) => m.type === "ANALYZE");
  assert.ok(asks.length > before, "the page is looked at again");
  assert.equal(asks[asks.length - 1].payload.fresh, true);
  assert.ok(types.lastIndexOf("ANALYZE") > types.indexOf("KRIKO_SYNC_SITES"),
    "asked after the sites were synced, never from the list the worker already held");
});

test("a press that taught nothing says why on the card and leaves it in place", () => {
  const p = openUnread(noAdapter(), worker({
    LEARN_PAGE: () => ({ ok: true, lesson: { mode: "local", learned: false, reason: "This page prints no labelled facts to learn from." } }),
  }));
  p.click(".lite-learn-btn");
  assert.equal(verdict(p).querySelector(".lite-learn-status").textContent,
    "This page prints no labelled facts to learn from.");
  assert.equal(verdict(p).querySelector(".lite-learn-btn").textContent, "Learn this page");
});

test("a page that is not a listing, on a site Kriko reads, offers nothing to learn", () => {
  const p = openUnread(noAdapter({ hostKnown: true }));
  assert.equal(verdict(p).dataset.verdict, "no-adapter");
  assert.equal(verdict(p).querySelector(".lite-learn-btn"), null);
});

test("an unknown product on a site nothing reads offers the site to be learned too", () => {
  const p = openUnread({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Acme Roadster", learnable: true });
  assert.equal(verdict(p).dataset.verdict, "unknown-product");
  assert.ok(verdict(p).querySelector(".lite-learn-btn"));
  const known = openUnread({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Acme Roadster" });
  assert.equal(verdict(known).querySelector(".lite-learn-btn"), null, "a site Kriko reads has nothing to learn");
});

test("the worker's nudge brings the panel up, and does not close one that is open", () => {
  const p = loadPanel({ analyzeResponse: noAdapter(), workerResponse: worker() });
  assert.equal(p.shadow(), null);
  p.deliverMessage({ type: "KRIKO_LEARN_NUDGE" });
  assert.ok(p.shadow(), "the panel is on screen");
  p.deliverMessage({ type: "KRIKO_LEARN_NUDGE" });
  assert.ok(p.shadow(), "a second nudge is not a toggle");
});

// ── the worker's side: which pages are worth a nudge ────────────────────

const ELSEWHERE = "https://elsewhere.invalid/p/1";
const page = (product, fields = {}) => ({
  url: ELSEWHERE, title: "Shop", description: "", fields, listing: {}, product,
});
const tab = (scrape) => ({
  GET_SCRAPE: { ok: true, payload: scrape },
  KRIKO_LEARN_NUDGE: { ok: true },
});
const routes = (analysis = { readable: false, reason: "unreadable" }) => ({
  "/api/adapters": [], "/api/analyze": analysis,
});
const nudges = (h) => h.state.tabMessages.filter((m) => m.message.type === "KRIKO_LEARN_NUDGE");

test("a product page on an unread site is nudged once, however many of its pages are opened", async () => {
  const h = loadBackground({
    routes: routes(), tabResponses: tab(page({ name: "Acme Roadster", typed: true }, { "ld:@type": "product" })),
  });
  await assert.rejects(() => h.sandbox.runAnalysisForTab(1, ELSEWHERE, { auto: true }), (e) => e.code === "UNKNOWN_PRODUCT" || e.code === "NO_ADAPTER");
  assert.equal(nudges(h).length, 1);
  assert.equal(nudges(h)[0].tabId, 1);
  const entry = Object.values(h.state.session).find((one) => one && one.code);
  assert.equal(entry.learnable, true, "the panel is told, so the card it opens can offer Learn");

  await assert.rejects(() => h.sandbox.runAnalysisForTab(1, ELSEWHERE + "2", { auto: true }));
  assert.equal(nudges(h).length, 1, "the same site is not asked about again this session");
});

test("an unknown product on an unread site is nudged the same way", async () => {
  const h = loadBackground({
    routes: routes({ readable: false, reason: "unknown_product", product: { name: "Acme Roadster" } }),
    tabResponses: tab(page({ name: "Acme Roadster", typed: true })),
  });
  await assert.rejects(() => h.sandbox.runAnalysisForTab(1, ELSEWHERE, { auto: true }), (e) => e.code === "UNKNOWN_PRODUCT");
  assert.equal(nudges(h).length, 1);
});

test("an ordinary page on an unread site is left alone", async () => {
  const h = loadBackground({ routes: routes(), tabResponses: tab(page({ name: "Home", typed: false })) });
  await assert.rejects(() => h.sandbox.runAnalysisForTab(1, ELSEWHERE, { auto: true }));
  assert.equal(nudges(h).length, 0);
});

test("pressing the toolbar is the reader asking, so nothing is nudged", async () => {
  const h = loadBackground({
    routes: routes(), tabResponses: tab(page({ name: "Acme Roadster", typed: true }, { "ld:@type": "product" })),
  });
  await assert.rejects(() => h.sandbox.runAnalysisForTab(1, ELSEWHERE, {}));
  assert.equal(nudges(h).length, 0);
});

test("a site Kriko already reads is never nudged to be learned", async () => {
  const h = loadBackground({
    routes: { "/api/adapters": [{ id: "x", site: "elsewhere.invalid", match: ["*elsewhere.invalid/ilan/*"], labels: [] }],
      "/api/analyze": { readable: false } },
    tabResponses: tab(page({ name: "Acme Roadster", typed: true })),
  });
  await assert.rejects(() => h.sandbox.runAnalysisForTab(1, ELSEWHERE, { auto: true }));
  assert.equal(nudges(h).length, 0);
});
