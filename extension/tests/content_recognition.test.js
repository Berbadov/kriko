const test = require("node:test");
const assert = require("node:assert/strict");
const { loadContentScript } = require("./harness.js");

function read(data, heading = "Northstar AX-1040R2", extra = "") {
  return loadContentScript(`<html><head><script type="application/ld+json">${JSON.stringify(data)}</script>${extra}</head><body><h1>${heading}</h1></body></html>`,
    "https://shop.example/p/ax-1040r2").buildScrape([], {});
}

test("a recommendation preceding the main product cannot supply its identity", () => {
  const result = read([
    { "@type": "Product", name: "Northstar AX-1040R1", sku: "AX-1040R1", url: "/p/ax-1040r1" },
    { "@type": "Product", name: "Northstar AX-1040R2", sku: "AX-1040R2", url: "/p/ax-1040r2" },
  ]);
  assert.equal(result.product.name, "Northstar AX-1040R2");
  assert.equal(result.fields["ld:sku"], "AX-1040R2");
  assert.equal(result.product.typed, true);
});

test("a search or collection page containing products is not a product listing", () => {
  for (const type of ["CollectionPage", "SearchResultsPage"]) {
    const result = read({ "@type": type, mainEntity: { "@type": "ItemList", itemListElement: [
      { "@type": "Product", name: "Northstar AX-1040R1", sku: "AX-1040R1" },
      { "@type": "Product", name: "Northstar AX-1040R2", sku: "AX-1040R2" },
    ] } }, "Search results");
    assert.equal(result.product.typed, false);
    assert.equal(result.fields["ld:sku"], undefined);
  }
});

test("graph mainEntity references select the requested product and preserve its code", () => {
  const result = read({ "@graph": [
    { "@type": "WebPage", mainEntity: { "@id": "#target" }, url: "https://shop.example/p/ax-1040r2" },
    { "@type": "Product", "@id": "#other", name: "Other AX-1040R1", sku: "AX-1040R1" },
    { "@type": "Product", "@id": "#target", name: "Northstar AX-1040R2", mpn: "AX-1040R2", brand: { name: "Northstar" } },
  ] });
  assert.equal(result.fields["ld:mpn"], "AX-1040R2");
  assert.equal(result.fields["ld:brand"], "Northstar");
});

test("an article mentioning a product does not trigger automatic product research", () => {
  const result = read({ "@type": "Article", headline: "How to choose", mentions: {
    "@type": "Product", name: "Northstar AX-1040R2", sku: "AX-1040R2",
  } }, "How to choose a notebook");
  assert.equal(result.product.typed, false);
  assert.equal(result.fields["ld:sku"], undefined);
});

test("multiple unanchored products are reported as ambiguous rather than the first one", () => {
  const result = read([
    { "@type": "Product", name: "Northstar AX-1040R1" },
    { "@type": "Product", name: "Northstar AX-1040R2" },
  ], "Notebook offers");
  assert.equal(result.product.typed, false);
  assert.equal(result.product.recognition.status, "ambiguous");
});

test("microdata product identity is recognized without JSON-LD", () => {
  const sandbox = loadContentScript(`<html><body><div itemscope itemtype="https://schema.org/Product">
    <h1 itemprop="name">Northstar AX-1040R2</h1><meta itemprop="sku" content="AX-1040R2">
    <span itemprop="brand" itemscope itemtype="https://schema.org/Brand"><meta itemprop="name" content="Northstar"></span>
  </div></body></html>`, "https://shop.example/p/ax-1040r2");
  const result = sandbox.buildScrape([], {});
  assert.equal(result.product.typed, true);
  assert.equal(result.fields["ld:sku"], "AX-1040R2");
  assert.equal(result.fields["ld:brand"], "Northstar");
});

test("a later reference cannot overwrite an earlier complete graph node", () => {
  const result = read({ "@graph": [
    { "@type": "Product", "@id": "#target", name: "Northstar AX-1040R2", sku: "AX-1040R2" },
    { "@type": "Product", name: "Other AX-1040R1", sku: "AX-1040R1" },
    { "@type": "WebPage", url: "/p/ax-1040r2", mainEntity: { "@id": "https://shop.example/p/ax-1040r2#target" } },
  ] }, "Notebook");
  assert.equal(result.fields["ld:sku"], "AX-1040R2");
});

test("a foreign webpage cannot appoint its own recommendation as the main product", () => {
  const result = read({ "@graph": [
    { "@type": "WebPage", url: "/p/other", mainEntity: { "@id": "#other" } },
    { "@type": "Product", "@id": "#other", name: "Other AX-1040R1", sku: "AX-1040R1" },
    { "@type": "Product", name: "Northstar AX-1040R2", sku: "AX-1040R2", url: "/p/ax-1040r2" },
  ] });
  assert.equal(result.fields["ld:sku"], "AX-1040R2");
});

test("identical product names with conflicting unanchored codes remain ambiguous", () => {
  const result = read([
    { "@type": "Product", name: "Northstar notebook", sku: "AX-1040R1" },
    { "@type": "Product", name: "Northstar notebook", sku: "AX-1040R2" },
  ], "Notebook offers");
  assert.equal(result.product.typed, false);
});

test("all additionalProperty fields retain the page's component codes and units", () => {
  const result = read({ "@type": "Product", name: "Northstar AX-1040R2", additionalProperty: [
    { "@type": "PropertyValue", name: "Board code", value: "BRD-2040R2" },
    { "@type": "PropertyValue", name: "Memory", value: 16, unitText: "GB" },
  ] });
  assert.equal(result.fields["ld:additionalProperty.Board code"], "BRD-2040R2");
  assert.equal(result.fields["ld:additionalProperty.Memory"], "16 GB");
});

test("a compatible host cannot displace the consumable being sold", () => {
  for (const relation of ["isConsumableFor", "isAccessoryOrSparePartFor"]) {
    const result = read({ "@type": "Product", name: "Filter kit FK-40", sku: "FK-40",
      brand: { name: "MANN" }, [relation]: { "@type": "Car", name: "Renault Megane 4",
        manufacturer: "Renault", model: "Megane", vehicleEngine: { fuelType: "Diesel" } } }, "Filter kit FK-40");
    assert.equal(result.product.name, "Filter kit FK-40");
    assert.equal(result.product.typed, true);
    assert.equal(result.fields["ld:@type"], "product");
    assert.equal(result.fields["ld:model"], undefined);
    assert.equal(result.fields[`ld:${relation}`], "Renault Megane 4");
  }
});

test("graph references to fitment hosts are not independent sale candidates", () => {
  const result = read({ "@graph": [
    { "@type": "Product", name: "Battery BT-40", sku: "BT-40", isAccessoryOrSparePartFor: { "@id": "#host" } },
    { "@type": "Product", "@id": "#host", name: "Northstar AX-1040R2", sku: "AX-1040R2" },
  ] }, "Battery BT-40 for Northstar AX-1040R2");
  assert.equal(result.product.name, "Battery BT-40");
  assert.equal(result.fields["ld:sku"], "BT-40");
  assert.equal(result.fields["ld:isAccessoryOrSparePartFor"], "Northstar AX-1040R2");
});
