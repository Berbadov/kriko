// B149: a product page on a site no pack has an adapter for.
//
// The pages are real, captured from the three sites the reader named ("other
// car sites", "big retail") and trimmed to what this reader uses — see the
// comment at the top of each file in `pages/`.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { loadContentScript } = require("./harness.js");

function page(name, url) {
  const html = fs.readFileSync(path.join(__dirname, "pages", name), "utf8");
  return loadContentScript(html, url);
}

test("an AutoScout24 listing reads as the car it carries (B149)", () => {
  const s = page("autoscout24_car.html", "https://www.autoscout24.com/offers/mercedes-benz-eqa-350");
  const scrape = s.buildScrape([], {});
  assert.equal(scrape.product.name, "Mercedes-Benz EQA 350");
  assert.equal(scrape.product.typed, true);
  assert.equal(scrape.fields["ld:@type"], "car");
  assert.equal(scrape.fields["ld:manufacturer"], "Mercedes-Benz");
  assert.equal(scrape.fields["ld:model"], "EQA 350");
  assert.equal(scrape.fields["ld:productionDate"], "2024-03-01");
  assert.equal(scrape.fields["ld:vehicleTransmission"], "Automatic");
  assert.equal(scrape.fields["ld:mileageFromOdometer"], "22270 KMT");
  assert.equal(scrape.fields["ld:mileageFromOdometer.unitText"], "KMT");
  assert.equal(scrape.fields["ld:vehicleEngine.fuelType"], "Electricity");
  // The outer listing's brand is still there, from the `Product` around it.
  assert.equal(scrape.fields["ld:brand"], "Mercedes-Benz");
});

test("a MediaMarkt product reads by its own name and brand (B149)", () => {
  const s = page("mediamarkt_oven.html", "https://www.mediamarkt.de/de/product/_bosch-hsg-7584-b-1.html");
  const scrape = s.buildScrape([], {});
  assert.match(scrape.product.name, /^BOSCH HSG 7584 B 1 Backofen/);
  assert.equal(scrape.product.typed, true);
  assert.equal(scrape.fields["ld:@type"], "product");
  assert.equal(scrape.fields["ld:brand"], "BOSCH");
  assert.equal(scrape.fields["ld:gtin13"], "4242005327232");
  assert.match(scrape.fields["ld:breadcrumb"], /^home > /);
});

test("a page with no structured data is named by its heading, and not typed (B149)", () => {
  const s = page("trendyol_sticker.html", "https://www.trendyol.com/pd/genel-markalar/kelebekler-duvar-sticker-p-52639639");
  const scrape = s.buildScrape([], {});
  assert.equal(scrape.product.name, "Genel Markalar Kelebekler Duvar Sticker");
  assert.equal(scrape.product.typed, false);
  assert.deepEqual(Object.keys(scrape.fields).filter((k) => k.startsWith("ld:")), []);
});

test("a broken JSON-LD block is skipped, not fatal (B149)", () => {
  const s = loadContentScript(`<html><head>
    <script type="application/ld+json">{ not json</script>
    <script type="application/ld+json">{"@graph":[{"@type":"Product","name":"Thing X1","brand":{"name":"Acme"}}]}</script>
  </head><body><h1>Thing X1 — best price</h1></body></html>`, "https://shop.example/p/1");
  const scrape = s.buildScrape([], {});
  assert.equal(scrape.product.name, "Thing X1");
  assert.equal(scrape.fields["ld:brand"], "Acme");
});
