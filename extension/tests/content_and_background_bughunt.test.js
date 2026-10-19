// Regressions from the 0.2.6 bug hunt: what the page shows, how a cart is counted, addresses that change
// without a load, and who a pack's match pattern may claim.
const test = require("node:test");
const assert = require("node:assert");

const { loadContentScript } = require("./harness.js");
const { loadBackground, send } = require("./background_harness.js");

const PRODUCT = (body) => `<html><head><title>Kettle X200 | Shop</title></head><body>${body}
  <meta property="og:type" content="product"></body></html>`;

test("the product's price is the one after its heading, not a mini-cart total in the header", () => {
  const s = loadContentScript(PRODUCT(`<header><span class="mini-cart-price">349,90 TL</span></header>
    <h1>Kettle X200</h1><span class="product-price">1.299,90 TL</span>`), "https://shop.example/p/kettle");
  assert.equal(s.buildScrape([], {}).fields["shown:price"], "1.299,90");
});

test("a price before the heading is used only when nothing follows it", () => {
  const s = loadContentScript(PRODUCT(`<span class="product-price">10 TL</span><h1>Kettle X200</h1>`),
    "https://shop.example/p/kettle");
  assert.equal(s.buildScrape([], {}).fields["shown:price"], "10");
});

test("an amount keeps its currency whichever side the sign is on, as an ISO code", () => {
  const s = loadContentScript(`<html><body></body></html>`, "https://shop.example/");
  const read = (text) => { const parts = s._priceParts(text); return [parts.amount, parts.sign]; };
  assert.deepEqual(read("2.450.000 TL"), ["2.450.000", "TRY"]);
  assert.deepEqual(read("₺ 2.450.000"), ["2.450.000", "TRY"]);
  assert.deepEqual(read("€ 120.000"), ["120.000", "EUR"]);
  assert.deepEqual(read("$19.99"), ["19.99", "USD"]);
  assert.deepEqual(read("1.299,90"), ["1.299,90", ""]);
});

test("a utility class that contains old, was or list is not a struck-through price", () => {
  for (const tag of ["price font-bold", "price-holder", "price gold", "price playlist", "price washer"]) {
    const s = loadContentScript(PRODUCT(`<h1>Kettle X200</h1><span class="${tag}">1.299,90 TL</span>`),
      "https://shop.example/p/kettle");
    assert.equal(s.buildScrape([], {}).fields["shown:price"], "1.299,90", tag);
  }
  for (const tag of ["old-price", "oldPrice", "price was", "price-list"]) {
    const s = loadContentScript(PRODUCT(`<h1>Kettle X200</h1><span class="${tag}">1.299,90 TL</span>`),
      "https://shop.example/p/kettle");
    assert.equal(s.buildScrape([], {}).fields["shown:price"], undefined, tag);
  }
});

test("a cart line is one line whatever its parts and its list are called", () => {
  const parts = loadContentScript(`<html><body><ul>
    <li class="cart-item"><a class="cart-item__name" href="/p/1">Kettle X200</a><span class="cart-item__price">49,90 €</span></li>
    <li class="cart-item"><a class="cart-item__name" href="/p/2">Filter pack</a><span class="cart-item__price">7,50 €</span></li>
  </ul></body></html>`, "https://shop.example/cart");
  assert.deepEqual(parts.readCart().items.map((one) => one.name), ["Kettle X200", "Filter pack"]);
  const wrapped = loadContentScript(`<html><body><div class="cart-items">
    <div class="cart-item"><a href="/p/1">Kettle X200</a><span class="price">49,90 €</span></div>
    <div class="cart-item"><a href="/p/2">Filter pack</a><span class="price">7,50 €</span></div>
  </div></body></html>`, "https://shop.example/cart");
  assert.deepEqual(wrapped.readCart().items.map((one) => one.name), ["Kettle X200", "Filter pack"]);
  const single = loadContentScript(`<html><body><div class="cart-items">
    <div class="cart-item"><a href="/p/1">Kettle X200</a><span class="price">49,90 €</span></div></div></body></html>`,
  "https://shop.example/cart");
  assert.deepEqual(single.readCart().items.map((one) => one.name), ["Kettle X200"]);
});

test("a damage amount keeps its decimal comma and may follow a word after the term", () => {
  const s = loadContentScript(`<html><body><p id="d">Tramer: 5.240,00 TL</p><p id="e">Tramer kaydı: 12.500 TL</p>
    <p id="z">Tramer: 0 TL</p></body></html>`, "https://shop.example/ilan/1");
  const panel = (id) => ({ measures: [{ key: "tramer_amount", currency_key: "tramer_currency",
    text_selectors: [`#${id}`], terms: ["tramer"], currencies: { TL: "TRY" }, default_currency: "TRY" }] });
  assert.equal(s._readMeasures(panel("d")).tramer_amount, 5240);
  assert.equal(s._readMeasures(panel("e")).tramer_amount, 12500);
  assert.equal(s._readMeasures(panel("z")).tramer_amount, 0);
});

test("a shop that changes its address without loading is read again", () => {
  const s = loadContentScript(PRODUCT(`<h1>Kettle X200</h1>`), "https://shop.example/p/kettle");
  const sent = [];
  s.chrome.runtime.sendMessage = (message) => sent.push(message);
  s.setTimeout = (fn) => { fn(); return 1; };
  s.window.history.pushState({}, "", "/p/toaster-t1");
  s.window.dispatchEvent(new s.window.Event("popstate"));
  assert.equal(sent.at(-1).type, "PAGE_LOADED");
  assert.equal(sent.at(-1).payload.url, "https://shop.example/p/toaster-t1");
  const before = sent.length;
  s.window.dispatchEvent(new s.window.Event("popstate"));
  assert.equal(sent.length, before, "the same address is not read twice");
});

test("a refused unwatch is a refusal, not a watch that is gone", async () => {
  const h = loadBackground({
    routes: { "/api/prices/watches/w1": { detail: "database is locked" } },
    statuses: { "/api/prices/watches/w1": 500 } });
  const reply = await send(h, { type: "BUYER_UNWATCH", payload: { watch_id: "w1" } });
  assert.equal(reply.ok, false);
});

test("a pack's match pattern claims its own site and not a lookalike or an address in a query", () => {
  const { sandbox } = loadBackground();
  const matches = (pattern, url) => sandbox.globToRegExp(pattern).test(url);
  const pattern = "*shop.example/urun/*";
  assert.ok(matches(pattern, "https://shop.example/urun/kettle-x200"));
  assert.ok(matches(pattern, "https://www.shop.example/urun/kettle-x200"));
  assert.ok(matches(pattern, "http://m.shop.example/urun/kettle-x200"));
  assert.ok(!matches(pattern, "https://evilshop.example/urun/x"));
  assert.ok(!matches(pattern, "https://www.google.com/search?src=https://shop.example/urun/kettle-x200"));
  assert.ok(!matches(pattern, "https://web.archive.org/web/2020/https://shop.example/urun/x"));
});
