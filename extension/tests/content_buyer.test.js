// The buyer's half of the scraper: the price a page shows, a cart, and marks on a results page.
const test = require("node:test");
const assert = require("node:assert");

const { loadContentScript } = require("./harness.js");

const PRODUCT = (price) => `<html><head><title>Kettle X200 | Shop</title></head><body>
  <h1>Kettle X200</h1>
  <div class="buy-box">${price}</div>
  <meta property="og:type" content="product">
</body></html>`;

test("a shop with no structured price still has its shown price read, with the struck-through one", () => {
  const s = loadContentScript(PRODUCT(`
    <span class="old-price">1.299,00 TL</span>
    <span class="product-price">999,90 TL</span>`), "https://shop.example/p/kettle-x200");
  const scrape = s.buildScrape([], {});
  assert.equal(scrape.fields["shown:price"], "999,90");
  assert.equal(scrape.fields["shown:currency"], "TL");
  assert.equal(scrape.fields["shown:was"], "1.299,00");
});

test("a struck-through price is never taken for the price", () => {
  const s = loadContentScript(PRODUCT(`<del class="price">500</del>`), "https://shop.example/p/x");
  const scrape = s.buildScrape([], {});
  assert.equal(scrape.fields["shown:price"], undefined);
});

test("the structured price wins and the shown price is not even read", () => {
  const s = loadContentScript(`<html><head>
    <script type="application/ld+json">{"@type":"Product","name":"Kettle X200","offers":{"@type":"Offer",
      "price":"49.90","priceCurrency":"EUR","priceSpecification":{"priceType":"https://schema.org/ListPrice","price":"79.90"}}}</script>
  </head><body><h1>Kettle X200</h1><span class="price">1 EUR</span></body></html>`, "https://shop.example/p/1");
  const scrape = s.buildScrape([], {});
  assert.equal(scrape.fields["ld:price"], "49.90");
  assert.equal(scrape.fields["ld:listPrice"], "79.90");
  assert.equal(scrape.fields["shown:price"], undefined);
});

test("a page that is not a product shows no price to read", () => {
  const s = loadContentScript(`<html><body><h1>News</h1><span class="price">12</span></body></html>`,
    "https://news.example/a");
  assert.equal(s.buildScrape([], {}).fields["shown:price"], undefined);
});

test("a cart is read as lines with their prices, and the page's words ride along", () => {
  const s = loadContentScript(`<html><body><main>
    <div class="cart-item"><a href="/p/kettle">Kettle X200</a><span class="item-price">49,90 €</span></div>
    <div class="cart-item"><a href="/p/filter">Filter pack</a><del class="item-price">9,00 €</del><span class="item-price">7,50 €</span></div>
    <p>Free returns within 30 days.</p></main></body></html>`, "https://shop.example/cart");
  const cart = s.readCart();
  assert.deepEqual(cart.items.map((one) => [one.name, one.price, one.currency]),
    [["Kettle X200", "49,90", "€"], ["Filter pack", "7,50", "€"]]);
  assert.match(cart.text, /Free returns within 30 days/);
});

const CARDS = (n) => Array.from({ length: n }, (_, i) => `
  <li class="card"><a href="/p/${i}"><img src="a.jpg"><h3>Phone ${i} Acme</h3></a>
    <span class="price">${100 + i} €</span></li>`).join("");

test("six alike products with a link, an image and a price are a results page", () => {
  const s = loadContentScript(`<html><body><ul>${CARDS(7)}</ul></body></html>`, "https://shop.example/search");
  const cards = s.findResultCards();
  assert.equal(cards.length, 7);
  const read = s.readResultCard(cards[0]);
  assert.equal(read.name, "Phone 0 Acme");
  assert.equal(read.price, "100");
  assert.equal(read.currency, "€");
});

test("a product page with one price block is not a results page", () => {
  const s = loadContentScript(`<html><body><ul>${CARDS(2)}</ul></body></html>`, "https://shop.example/p/1");
  assert.equal(s.findResultCards().length, 0);
});

test("a mark is drawn beside the price: red when the reader's limits break, green when it fits, none when unknown", () => {
  const s = loadContentScript(`<html><body><ul>${CARDS(6)}</ul></body></html>`, "https://shop.example/search");
  const cards = s.findResultCards();
  const reads = cards.map((card) => s.readResultCard(card));
  s.markResultCard(cards[0], reads[0], { score: 15, reasons: [{ message: "mentions Acme, which you avoid" }], breaks: ["avoid"] });
  s.markResultCard(cards[1], reads[1], { score: 70, reasons: [{ message: "says it has usb-c" }], breaks: [] });
  s.markResultCard(cards[2], reads[2], { score: 50, reasons: [], breaks: [] });
  const marks = [...cards].map((card) => card.querySelector("[data-kriko-fit]"));
  assert.equal(marks[0].textContent, "Not for you: avoid");
  assert.equal(marks[0].title, "mentions Acme, which you avoid");
  assert.equal(marks[1].textContent, "Fits you");
  assert.equal(marks[2], null);
  // Marking again replaces the mark rather than stacking one.
  s.markResultCard(cards[0], reads[0], { score: 15, reasons: [{ message: "x" }], breaks: ["budget"] });
  assert.equal(cards[0].querySelectorAll("[data-kriko-fit]").length, 1);
});
