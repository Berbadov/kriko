const test = require("node:test");
const assert = require("node:assert/strict");
const { loadContentScript } = require("./harness.js");
const { loadBackground, send } = require("./background_harness.js");

test("listing findings mark the original words, skip controls, and refresh without nesting", () => {
  const h = loadContentScript(`<body><h1>The best tool</h1><p>Waterproof body</p><button>best</button><div contenteditable="true">best</div><script>best</script></body>`);
  const audit = { claims: { items: [{ phrase: "best", status: "puffery", why: "No measurement backs it" },
    { phrase: "Waterproof", status: "backed" }] } };
  h.annotateListing(audit);
  const marks = h.document.querySelectorAll("[data-kriko-claim]");
  assert.equal(marks.length, 1);
  assert.equal(marks[0].textContent, "best");
  assert.match(marks[0].title, /No measurement/);
  assert.equal(marks[0].tabIndex, 0);
  h.annotateListing(audit);
  assert.equal(h.document.querySelectorAll("mark").length, 1);
  h.annotateListing(null);
  assert.equal(h.document.querySelector("h1").textContent, "The best tool");
  assert.equal(h.document.querySelectorAll("mark").length, 0);
});

test("rating doubts annotate the rating itself without marking unrelated numbers", () => {
  const h = loadContentScript(`<body><p itemprop="ratingValue">4.9</p><p>4.9 kg</p></body>`);
  h.annotateListing({ reviews: { doubtful: true, notes: ["Only two ratings"] } });
  assert.equal(h.document.querySelectorAll("mark").length, 1);
  assert.match(h.document.querySelector("mark").title, /Only two ratings/);
});

test("folded audit phrases preserve accented original text and avoid partial words", () => {
  const h = loadContentScript(`<body><h1>Besteck m\u00fckemmel</h1></body>`);
  h.annotateListing({ claims: { items: [{ phrase: "beste", status: "puffery" }, { phrase: "mukemmel", status: "puffery", why: "Superlative" }] } });
  assert.equal(h.document.querySelectorAll("mark").length, 1);
  assert.equal(h.document.querySelector("mark").textContent, "m\u00fckemmel");
  assert.equal(h.document.querySelector("h1").textContent, "Besteck m\u00fckemmel");
});

test("automatic product recognition adds one button, and a quick check stays on the page", () => {
  const h = loadContentScript(`<body><h1>The best tool</h1><meta property="og:type" content="product"><span class="price">100 EUR</span></body>`);
  h.chrome.runtime.sendMessage = (request, callback) => callback({ ok: true, items: [{ name: "Tool", level: "high", method: "exact", basis: "page text", claims: [{ title: "Bearing fails", severity: "high" }], freshness: { stale: true }, costs: { missing: ["Bearing"] } }] });
  h.detectQuickProduct(); h.detectQuickProduct();
  assert.equal(h.document.querySelectorAll("[data-kriko-quick]").length, 1);
  h.document.querySelector("[data-kriko-quick]").click();
  assert.equal(h.document.querySelector("[data-kriko-quick]").nextElementSibling.getAttribute("data-kriko-summary"), "");
  assert.match(h.document.querySelector("[data-kriko-summary]").textContent, /Bearing fails/);
  assert.match(h.document.querySelector("[data-kriko-summary]").textContent, /Last verified.*Unknown/);
});

test("batch scan badges each result and never presents a gap as low risk", () => {
  const h = loadContentScript(`<body><ul>${Array.from({ length: 6 }, (_, i) => `<li class="card"><a href="/p/${i}"><img src="x"><h3>Tool ${i}</h3></a><span class="price">10 EUR</span></li>`).join("")}</ul></body>`);
  let calls = 0;
  h.chrome.runtime.sendMessage = (request, callback) => {
    calls++;
    assert.equal(request.payload.items.length, 6);
    callback({ ok: true, items: request.payload.items.map((one, i) => ({ ...one, level: i ? "unknown" : "high", claims: [] })) });
  };
  const reads = h.findResultCards().map((card) => ({ card, read: h.readResultCard(card) }));
  h.scanResultCards(reads);
  assert.equal(calls, 1);
  assert.equal(h.document.querySelectorAll("[data-kriko-risk]").length, 6);
  assert.equal(h.document.querySelector("[data-kriko-risk='unknown']").textContent, "Kriko · No rating");
  h.scanResultCards(reads);
  assert.equal(h.document.querySelectorAll("[data-kriko-risk]").length, 6);
  assert.equal(h.document.querySelectorAll("[data-kriko-quick]").length, 6);
});

test("quick summary treats source text as text and rejects script links", () => {
  const h = loadContentScript(`<body><main></main></body>`);
  h.drawQuickSummary(h.document.querySelector("main"), { name: "<img src=x onerror=alert(1)>", claims: [], costs: { items: [{ title: "Part", prices: ["10 EUR"], url: "javascript:alert(1)" }] } });
  assert.equal(h.document.querySelectorAll("img,a").length, 0);
  assert.match(h.document.querySelector("main").textContent, /<img/);
});

test("a long results page is scanned in bounded batches with no cards left out", () => {
  const h = loadContentScript(`<body><ul>${Array.from({ length: 65 }, (_, i) => `<li class="card"><a href="/p/${i}"><img src="x"><h3>Tool ${i}</h3></a><span class="price">10 EUR</span></li>`).join("")}</ul></body>`);
  const sizes = [];
  h.chrome.runtime.sendMessage = (request, callback) => {
    sizes.push(request.payload.items.length);
    callback({ ok: true, items: request.payload.items.map((item) => ({ ...item, level: "unknown", claims: [] })) });
  };
  h.scanResultCards(h.findResultCards().map((card) => ({ card, read: h.readResultCard(card) })));
  assert.deepEqual(sizes, [60, 5]);
  assert.equal(h.document.querySelectorAll("[data-kriko-risk]").length, 65);
});

test("the worker forwards scans through the local batch endpoint", async () => {
  const h = loadBackground({ routes: { "/api/products/scan": { items: [{ level: "unknown" }] } } });
  const reply = await send(h, { type: "PRODUCT_SCAN", payload: { items: [{ name: "Tool" }] } });
  assert.equal(reply.ok, true);
  assert.equal(reply.items[0].level, "unknown");
  assert.equal(h.state.requests[0].url, "http://127.0.0.1:8787/api/products/scan");
});

test("right-click scans selected URLs without fetching or opening the product page", async () => {
  let clicked;
  const menus = [];
  const h = loadBackground({
    contextMenus: { removeAll: async () => { menus.length = 0; }, create: (menu) => menus.push(menu), onClicked: { addListener: (fn) => { clicked = fn; } } },
    routes: { "/api/products/scan": { items: [{ name: "Tool", level: "high", claims: [{ title: "Bearing failure" }], basis: "saved page check", freshness: { stale: true } }] } },
  });
  for (const listener of h.installedListeners) await listener({ reason: "update" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(menus.length, 1);
  assert.ok(menus[0].contexts.includes("selection"));
  h.state.requests.length = 0;
  await clicked({ menuItemId: "kriko-quick-scan", selectionText: "https://shop.invalid/tool" }, { id: 1 });
  assert.equal(h.state.requests.length, 1);
  assert.equal(h.state.requests[0].body.items[0].url, "https://shop.invalid/tool");
  assert.match(h.state.notified.at(-1), /Bearing failure/);
  assert.match(h.state.notified.at(-1), /stale or incomplete/);
  assert.equal(h.state.tabsCreated.length, 0);
});
