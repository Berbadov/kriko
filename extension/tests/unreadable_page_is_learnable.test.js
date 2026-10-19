// "Unable to read this page", with no way out. The reader's report: on a site
// Kriko already had an adapter for, the panel said it was unable to read the
// page, offered no Learn this page, and so the site could never be taught the
// page again. Two causes met. One refused selector from an adapter threw out of
// the whole scrape, so a readable page read as nothing. And the failure itself
// was a bare sentence on a card with no button.
const test = require("node:test");
const assert = require("node:assert/strict");

const { loadContentScript } = require("./harness.js");
const { loadBackground } = require("./background_harness.js");
const { loadPanel } = require("./hover_lite_harness.js");

const PAGE = `<html><head><title>Asus ROG Raikiri II | Shop</title></head><body>
  <h1>Asus ROG Raikiri II Controller</h1>
  <dl><dt>Brand</dt><dd>Asus</dd></dl>
</body></html>`;

test("an adapter's refused selector no longer takes the whole scrape down", () => {
  const s = loadContentScript(PAGE, "https://shop.example/p/1");
  // `[` is not a selector. An agent-written adapter can carry one like it.
  const scrape = s.buildScrape([], { states: [{ key: "x" }], block_selector: "[[", item_selector: "li" }, false);
  assert.equal(scrape.title, "Asus ROG Raikiri II Controller");
  assert.equal(scrape.fields.Brand, "Asus");
  assert.ok(scrape.problems.some((one) => one.startsWith("damage panel")), JSON.stringify(scrape.problems));
});

test("a page that reads cleanly reports no problems", () => {
  const s = loadContentScript(PAGE, "https://shop.example/p/1");
  assert.deepEqual([...s.buildScrape([], {}, false).problems], []);
});

const ADAPTERS = [{
  id: "shop", site: "shop.example", pack_id: "org.kriko.cars",
  match: ["*shop.example/p/*"], labels: ["brand"],
}];

test("a page the worker cannot read on a known site is a way to learn it, not a red alarm", async () => {
  const h = loadBackground({
    routes: { "/api/adapters": ADAPTERS },
    tabResponses: { GET_SCRAPE: { ok: false, error: "boom" } },
  });
  await assert.rejects(
    () => h.sandbox.runAnalysisForTab(1, "https://shop.example/p/1"),
    (error) => error.code === "SCRAPE_FAILED" && error.learnable === true && /boom/.test(error.message));
  assert.equal(h.state.badge[1], "?", "the page is the problem, not the extension");
});

test("the panel shows Learn this page under the error, and learns when it is pressed", () => {
  const p = loadPanel({
    analyzeResponse: { ok: false, code: "SCRAPE_FAILED", learnable: true, error: "Kriko could not read this page." },
    workerResponse: (message) => {
      if (message.type === "AGENTS") return { ok: true, chosen: "local", agents: [{ id: "local", label: "Local agent", kind: "local" }] };
      if (message.type === "LEARN_PAGE") return { ok: true, lesson: { mode: "local", learned: true, host: "shop.example", grabs: [] } };
      return { ok: true };
    },
  });
  p.openPanel();
  p.click(".lite-cta");
  const root = p.shadow();
  assert.match(root.querySelector(".lite-error").textContent, /could not read this page/);
  assert.equal(root.querySelector(".lite-error-learn .lite-learn-btn").textContent, "Learn this page");

  p.click(".lite-learn-btn");
  const types = p.sent.map((m) => m.type);
  assert.ok(types.includes("LEARN_PAGE"));
  assert.ok(types.indexOf("KRIKO_SYNC_SITES") > types.indexOf("LEARN_PAGE"));
  assert.ok(types.lastIndexOf("ANALYZE") > types.indexOf("KRIKO_SYNC_SITES"), "the page is asked about again once it is learned");
});

test("an error that is not about the page offers nothing to learn", () => {
  const p = loadPanel({ analyzeResponse: { ok: false, code: "APP_NOT_RUNNING", error: "Kriko is not running." } });
  p.openPanel();
  p.click(".lite-cta");
  assert.equal(p.shadow().querySelector(".lite-learn-btn"), null);
});
