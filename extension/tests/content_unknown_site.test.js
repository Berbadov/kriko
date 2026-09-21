// What the scraper reads on a site whose markup it has never seen.
//
// `content.test.js` covers the site the extension shipped against, whose class
// names are written into the selectors. This file covers every *other* site —
// the ones a reader adds — where none of those selectors match and the only
// thing left is the scan for labels the pack declared.
//
// That scan used to be a fallback: it ran only when the site-specific
// selectors had returned nothing at all. On an unknown site the sole generic
// selector among them is `dl dt`, so one stray `<dl>` in a footer or a cookie
// notice was enough to count as success and suppress the scan entirely. The
// panel came up holding one junk pair and none of the real ones, and no test
// noticed because every fixture was a page the selectors did match.
const test = require("node:test");
const assert = require("node:assert");

const { loadContentScript } = require("./harness.js");

// Standing in for what the server hands down off the installed pack's adapter.
// The content script has no vocabulary of its own; these are the pack's words.
const LABELS = ["yıl", "kilometre", "vites", "yakıt"];

// A site the extension was never written against: no `classifiedInfoList`, no
// `classifiedInfo`, no `.classified-properties`. Just labelled rows, the way
// most of the web writes them.
const UNKNOWN_SITE = `
  <html><body>
    <nav>
      <dl><dt>Çerez</dt><dd>Kabul et</dd></dl>
    </nav>
    <main>
      <div class="row"><span class="k">Yıl</span><span class="v">2014</span></div>
      <div class="row"><span class="k">Kilometre</span><span class="v">185.000</span></div>
      <div class="row"><span class="k">Vites</span> Otomatik</div>
      <div class="wrap"><span class="k">Yakıt</span></div><div class="v">Dizel</div>
    </main>
  </body></html>
`;

test("a stray <dl> no longer suppresses the whole scan", () => {
  const s = loadContentScript(UNKNOWN_SITE, "https://otoparca.example/ilan/1");
  const details = s.extractInfoList(LABELS);

  // The regression, stated as the reader saw it: four facts on the page, and
  // the panel knew none of them because a cookie notice answered first.
  assert.equal(details["Yıl"], "2014");
  assert.equal(details["Kilometre"], "185.000");
});

test("the three row shapes each yield their value", () => {
  const s = loadContentScript(UNKNOWN_SITE, "https://otoparca.example/ilan/1");
  const details = s.extractInfoList(LABELS);

  // Sibling element — the one shape that always worked.
  assert.equal(details["Yıl"], "2014");
  // Loose text after the label, with no element around it.
  assert.equal(details["Vites"], "Otomatik");
  // The parent's other half: label wrapped one level deeper than the value.
  // The comment in content.js promised this shape for a long time before
  // anything implemented it.
  assert.equal(details["Yakıt"], "Dizel");
});

test("what the site's own selectors found still wins", () => {
  // Both readings are available for `Yıl` and they disagree. The specific
  // extractor is the one that knows this site, so it must not be overwritten
  // by the generic scan merged in underneath it.
  const s = loadContentScript(
    `<html><body>
       <ul class="classifiedInfoList">
         <li><strong>Yıl</strong>2014</li>
       </ul>
       <div><span>Yıl</span><span>1999</span></div>
     </body></html>`,
    "https://otoparca.example/ilan/1",
  );
  assert.equal(s.extractInfoList(LABELS)["Yıl"], "2014");
});

test("a label the pack never declared is not read", () => {
  // The scan is bounded by the pack's vocabulary, and stays bounded now that
  // it always runs. Otherwise "always scan" would mean scraping every short
  // string on the page into the panel.
  const s = loadContentScript(
    `<html><body>
       <div><span>Yıl</span><span>2014</span></div>
       <div><span>Satıcı Notu</span><span>Acil satılık</span></div>
     </body></html>`,
    "https://otoparca.example/ilan/1",
  );
  const details = s.extractInfoList(LABELS);
  assert.equal(details["Yıl"], "2014");
  assert.equal(details["Satıcı Notu"], undefined);
});

test("a label with nothing beside it yields nothing rather than itself", () => {
  // The failure mode of reading the parent: climb one level and the label is
  // inside what you just read, so the row reports its own name as its value.
  const s = loadContentScript(
    `<html><body><div><span>Yıl</span></div></body></html>`,
    "https://otoparca.example/ilan/1",
  );
  const details = s.extractInfoList(LABELS);
  assert.ok(
    details["Yıl"] === undefined || details["Yıl"] !== "Yıl",
    `an empty row reported ${JSON.stringify(details["Yıl"])} as its value`,
  );
});
