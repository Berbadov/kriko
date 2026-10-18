const test = require("node:test");
const assert = require("node:assert/strict");
const { loadContentScript } = require("./harness.js");
const { loadPanel } = require("./hover_lite_harness.js");
const { loadBackground, send } = require("./background_harness.js");

test("a promotional listing title cannot suppress facts across details sections", () => {
  const page = loadContentScript(`<h1>ÖZAK-BOYASIZ 2017 MODEL OPEL ASTRA 1.4 ENJOY 105.000'KM KIRMIZI</h1>
    <ul class="classifiedInfoList"><li><strong>Marka</strong> Opel</li>
      <li><strong>Seri</strong> Astra</li><li><strong>Model</strong> 1.4 Enjoy</li></ul>
    <table class="classifiedInfo"><tr><th>Yıl</th><td>2017</td></tr></table>
    <dl><dt>Motor Gücü</dt><dd>100 hp</dd></dl>
    <div class="spec-row"><span>New engine code</span><span>B14XE</span></div>`);
  const scrape = page.buildScrape(["Marka", "Seri", "Model", "Yıl"], {});
  assert.equal(scrape.fields.Marka, "Opel");
  assert.equal(scrape.fields.Seri, "Astra");
  assert.equal(scrape.fields.Model, "1.4 Enjoy");
  assert.equal(scrape.fields.Yıl, "2017");
  assert.equal(scrape.fields["Motor Gücü"], "100 hp");
  assert.equal(scrape.fields["New engine code"], "B14XE");
});

test("agents receive the primary product description even without a description block", () => {
  const page = loadContentScript(`<script type="application/ld+json">${JSON.stringify({
    "@type": "Product", name: "Example R2", description: "16 GB, model R2, new condition",
  })}</script>`);
  const scrape = page.buildScrape([], {});
  assert.equal(scrape.description, "16 GB, model R2, new condition");
  assert.equal(scrape.title, "Example R2");
});

test("the extension routes a web search separately from installed pack search", async () => {
  const h = loadBackground({ routes: { "/api/extension/web-search?q=Opel%20Astra": {
    items: [{ title: "Astra specs", url: "https://example.com/astra" }],
  } } });
  const reply = await send(h, { type: "WEB_SEARCH", payload: { q: "Opel Astra" } });
  assert.equal(reply.ok, true);
  assert.equal(reply.items[0].title, "Astra specs");
  assert.match(h.state.requests[0].url, /\/api\/extension\/web-search\?q=Opel%20Astra/);
});

test("web mode shows clickable public results and ignores script URLs", () => {
  const p = loadPanel({ workerResponse: (message) => message.type === "WEB_SEARCH" ? {
    ok: true, items: [
      { title: "Astra specifications", url: "https://example.com/astra", snippet: "100 hp" },
      { title: "Bad link", url: "javascript:alert(1)" },
    ],
  } : { ok: true } });
  p.openPanel();
  p.click(".lite-btn-search");
  p.type(".lite-search-field", "Opel Astra");
  p.click(".lite-search-web");
  p.flushTimers();
  assert.ok(p.sent.some((m) => m.type === "WEB_SEARCH" && m.payload.q === "Opel Astra"));
  const links = p.shadow().querySelectorAll("a.lite-search-hit");
  assert.equal(links.length, 1);
  assert.equal(links[0].href, "https://example.com/astra");
  assert.match(links[0].textContent, /100 hp/);
});

test("research starts from the extracted product identity before a seller's headline", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ok: true, listing: { title: "ÖZAK BOYASIZ 105.000 KM KIRMIZI" }, result: {
    identity: { brand: "Opel", model: "Astra", version: "1.4 Enjoy" },
    context: { build_year: 2017 }, subjects: [], claims: [], coverage: "NOT_MATCHED",
  } });
  p.click(".lite-research-product");
  assert.equal(p.shadow().querySelector(".lite-research-name").value, "Opel Astra 1.4 Enjoy");
});
