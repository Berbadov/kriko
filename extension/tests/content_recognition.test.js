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

test("research retains the selected product's description, graph components, arrays and units", () => {
  const result = read({ "@graph": [
    { "@type": "Product", name: "Northstar AX-1040R2", description: "Revision two with replaceable memory.",
      sku: "AX-1040R2", color: ["Black", "Silver"], hasPart: { "@id": "#board" } },
    { "@id": "#board", "@type": "Product", name: "Main board", model: "BRD-2040R2",
      weight: { "@type": "QuantitativeValue", value: 250, unitText: "g" } },
  ] });
  assert.equal(result.description, "Revision two with replaceable memory.");
  assert.equal(result.fields["ld:color"], "Black; Silver");
  assert.equal(result.fields["ld:hasPart.model"], "BRD-2040R2");
  assert.equal(result.fields["ld:hasPart.weight"], "250 g");
});

test("generic specification tables and description are read on an unfamiliar shop", () => {
  const s = loadContentScript(`<html><body><main><h1>Northstar AX-1040R2</h1>
    <section id="specifications"><table><tr><th>Board revision</th><td>BRD-2040R2</td></tr>
    <tr><td>Memory</td><td>16 GB</td></tr></table></section>
    <section id="product-description">Ships with the revision two board.</section>
    <script type="application/ld+json">{"@type":"Product","name":"Northstar AX-1040R2"}</script>
    </main></body></html>`, "https://shop.example/p/ax-1040r2");
  const result = s.buildScrape([], {});
  assert.equal(result.fields["Board revision"], "BRD-2040R2");
  assert.equal(result.fields.Memory, "16 GB");
  assert.equal(result.description, "Ships with the revision two board.");
});

test("query-selected variants are distinguished even when paths are identical", () => {
  const s = loadContentScript(`<html><body><h1>Northstar notebook</h1><script type="application/ld+json">${JSON.stringify([
    { "@type": "Product", name: "Northstar notebook", sku: "AX-1040R1", url: "?variant=r1" },
    { "@type": "Product", name: "Northstar notebook", sku: "AX-1040R2", url: "?variant=r2" },
  ])}</script></body></html>`, "https://shop.example/p/notebook?variant=r2&utm_source=mail");
  assert.equal(s.buildScrape([], {}).fields["ld:sku"], "AX-1040R2");
});

test("Open Graph product pages contribute brand, codes and description to research", () => {
  const result = loadContentScript(`<html><head>
    <meta property="og:type" content="product"><meta property="og:title" content="Northstar AX-1040R2">
    <meta property="product:brand" content="Northstar"><meta property="product:retailer_item_id" content="AX-1040R2">
    <meta property="og:description" content="Revision two, 16 GB memory.">
    </head><body><h1>Northstar AX-1040R2</h1></body></html>`, "https://shop.example/p/ax-1040r2").buildScrape([], {});
  assert.equal(result.fields["meta:product:brand"], "Northstar");
  assert.equal(result.description, "Revision two, 16 GB memory.");
});

test("mixed markup retains specifications beyond the first info list", () => {
  const result = loadContentScript(`<body><h1>Northstar AX-1040R2</h1>
    <ul class="classifiedInfoList"><li><strong>Brand</strong>Northstar</li></ul>
    <dl><dt>Revision</dt><dd>R2</dd></dl>
    <table class="classifiedInfo"><tr><th>Memory</th><td>16 GB</td></tr></table>
    </body>`).buildScrape([], {});
  assert.equal(result.fields.Brand, "Northstar");
  assert.equal(result.fields.Revision, "R2");
  assert.equal(result.fields.Memory, "16 GB");
});

test("specifications from recommendations are excluded from generic reading", () => {
  const result = loadContentScript(`<body><main><h1>Northstar AX-1040R2</h1>
    <aside><section class="specifications"><table><tr><th>Revision</th><td>R1</td></tr></table></section></aside>
    <section class="specifications"><dl><dt>Revision</dt><dd>R2</dd></dl></section>
    </main></body>`).buildScrape([], {});
  assert.equal(result.fields.Revision, "R2");
});

test("comparison links inside a product heading do not contaminate search queries", () => {
  const result = loadContentScript(`<body><main><h1>Northstar AX-1040R2<a href="/compare">Compare this model</a></h1></main></body>`,
    "https://shop.example/p/ax-1040r2").buildScrape([], {});
  assert.equal(result.product.name, "Northstar AX-1040R2");
});

test("repeated microdata properties retain every declared value", () => {
  const result = loadContentScript(`<body><h1>Northstar AX-1040R2</h1>
    <main itemscope itemtype="https://schema.org/Product"><span itemprop="name">Northstar AX-1040R2</span>
      <span itemprop="color">Black</span><span itemprop="color">Silver</span>
      <div itemprop="additionalProperty" itemscope itemtype="https://schema.org/PropertyValue">
        <span itemprop="name">Memory</span><meta itemprop="value" content="16"><span itemprop="unitText">GB</span>
      </div>
      <div itemprop="additionalProperty" itemscope itemtype="https://schema.org/PropertyValue">
        <span itemprop="name">Board revision</span><span itemprop="value">BRD-2040R2</span>
      </div>
    </main></body>`, "https://shop.example/p/ax-1040r2").buildScrape([], {});
  assert.equal(result.fields["ld:color"], "Black; Silver");
  assert.equal(result.fields["ld:additionalProperty.Memory"], "16 GB");
  assert.equal(result.fields["ld:additionalProperty.Board revision"], "BRD-2040R2");
});

test("graph property references resolve without mixing a related product's identity", () => {
  const result = read({ "@graph": [
    { "@type": "Product", name: "Northstar AX-1040R2", additionalProperty: { "@id": "#memory" },
      isRelatedTo: { name: "Other AX-1040R1", sku: "AX-1040R1" } },
    { "@id": "#memory", "@type": "PropertyValue", name: "Memory", value: 16, unitText: "GB" },
  ] });
  assert.equal(result.fields["ld:additionalProperty.Memory"], "16 GB");
  assert.equal(result.fields["ld:isRelatedTo"], undefined);
  assert.equal(result.fields["ld:isRelatedTo.sku"], undefined);
});
