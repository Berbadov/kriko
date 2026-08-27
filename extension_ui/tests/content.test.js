// The scraper's job, after Phase 6c: report what the page says, and interpret
// nothing.
//
// Everything this file used to assert — that "Yakıt" means fuel, that "Seri"
// holds the model and "Model" the trim, that "110 hp" under "Engine Capacity"
// is not a displacement — is now the cars pack's business, tested in
// `kriko/tests/test_adapters.py`. What is left here is the part only a browser
// can do: find label/value pairs in markup that changes without notice.
//
// The split matters because of how this used to fail. A Sahibinden redesign
// would zero every field, the extension would go on reporting success, and the
// only symptom was the server answering "Missing required fields". Keeping the
// meaning server-side means a site change is a pack edit, not a release.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { loadContentScript } = require("./harness.js");

const fixture = (name) =>
  fs.readFileSync(path.join(__dirname, "fixtures", name), "utf8");

// The labels the server hands down from the installed pack's adapter. The
// content script has no vocabulary of its own — that is the point.
const PACK_LABELS = [
  "marka", "make", "brand", "seri", "series", "yıl", "yil", "year",
  "yakıt", "yakit", "fuel", "vites", "gear", "kilometre", "km",
  "motor hacmi", "engine capacity", "motor gücü", "engine power",
  "renk", "color", "model", "trim", "kasa tipi", "body type",
];

// ── the page's own labels, uninterpreted ────────────────────────────────

test("classic info list: labels and values are reported exactly as written", () => {
  const s = loadContentScript(fixture("sahibinden_classic.html"));
  const { fields } = s.buildScrape(PACK_LABELS);

  assert.equal(fields["Marka"], "Volkswagen");
  assert.equal(fields["Seri"], "Golf");
  assert.equal(fields["Yıl"], "2014");
  assert.equal(fields["Yakıt"], "Dizel");
  assert.equal(fields["Vites"], "Otomatik");
  assert.equal(fields["Kilometre"], "190.000");
});

test("a label the pack considers noise is still reported, not filtered here", () => {
  // "Yakıt Tüketimi" is a near-miss for the fuel rule, and dropping it is the
  // adapter's call. A client-side filter would put that decision in the one
  // place that cannot be changed without shipping a new extension.
  const s = loadContentScript(`
    <h1>2014 Volkswagen Golf</h1>
    <ul class="classifiedInfoList">
      <li><strong>Yakıt Tüketimi</strong><span>4,5 lt</span></li>
    </ul>`);
  assert.equal(s.buildScrape(PACK_LABELS).fields["Yakıt Tüketimi"], "4,5 lt");
});

test("english locale is not a special case — the labels are just different", () => {
  const s = loadContentScript(fixture("sahibinden_english.html"));
  const { fields } = s.buildScrape(PACK_LABELS);

  assert.equal(fields["Make"], "Volkswagen");
  assert.equal(fields["Series"], "Golf");
  assert.equal(fields["Year"], "2016");
  assert.equal(fields["KM"], "132.000");
});

test("the technical panel is merged in without overwriting the info list", () => {
  const s = loadContentScript(fixture("sahibinden_english.html"));
  const { fields } = s.buildScrape(PACK_LABELS);

  assert.equal(fields["Transmission / Drive Type"],
               "DSG / 7 Gear / Front Wheel Drive");
  // Sahibinden's own bug: "Engine Capacity" labels the power row in one table
  // and the real capacity in another. The scraper keeps the first and lets the
  // adapter's range bound decide — it does not guess here.
  assert.ok(fields["Engine Capacity"]);
});

// ── surviving a redesign ────────────────────────────────────────────────

test("labels are found by text when no known container selector matches", () => {
  const s = loadContentScript(`
    <h1>2014 Volkswagen Golf 1.6 TDI</h1>
    <div class="brand-new-info-wrapper">
      <div class="row"><span>Yıl</span><span>2014</span></div>
      <div class="row"><span>Yakıt</span><span>Dizel</span></div>
      <div class="row"><span>Kilometre</span><span>190.000</span></div>
    </div>`);
  const { fields } = s.buildScrape(PACK_LABELS);
  assert.equal(fields["Yıl"], "2014");
  assert.equal(fields["Yakıt"], "Dizel");
  assert.equal(fields["Kilometre"], "190.000");
});

test("the text scan looks only for labels the server supplied", () => {
  // No built-in list. If the pack does not know a label, the scraper does not
  // hunt for it — which is what makes the pack the single source of truth.
  const s = loadContentScript(`
    <div class="row"><span>Yıl</span><span>2014</span></div>`);
  assert.deepEqual(s.buildScrape([]).fields, {});
  assert.equal(s.buildScrape(["yıl"]).fields["Yıl"], "2014");
});

// ── what goes on the wire ───────────────────────────────────────────────

test("the scrape carries the url, the title and the description", () => {
  const s = loadContentScript(`
    <h1 class="classifiedTitle">2014 Volkswagen Golf 1.6 TDI</h1>
    <div id="classifiedDescription">Bakımlı araç.</div>`);
  const scrape = s.buildScrape(PACK_LABELS);
  assert.match(scrape.url, /sahibinden\.com/);
  assert.equal(scrape.title, "2014 Volkswagen Golf 1.6 TDI");
  assert.equal(scrape.description, "Bakımlı araç.");
});

test("damage and equipment stay local and never enter the posted fields", () => {
  // The panel renders these; the engine has no rule for them. Sending them
  // would put listing-specific personal-ish detail on the wire for nothing.
  const s = loadContentScript(fixture("sahibinden_classic.html"));
  const scrape = s.buildScrape(PACK_LABELS);
  assert.ok(scrape.listing);
  assert.ok(scrape.listing.damage_info);
  assert.ok(scrape.listing.equipment);
  assert.ok(!("damage_info" in scrape.fields));
  assert.ok(!("equipment" in scrape.fields));
});

test("the scraper reports no identity of its own", () => {
  // A regression guard for the whole point of Phase 6c: if `make`, `year` or
  // `fuel_type` reappear on the scrape, the interpretation has crept back into
  // the client and the pack has stopped being the source of truth.
  const s = loadContentScript(fixture("sahibinden_classic.html"));
  const scrape = s.buildScrape(PACK_LABELS);
  for (const key of ["make", "model", "year", "fuel_type", "transmission",
                     "engine_volume_cc", "power_hp", "mileage_km"]) {
    assert.ok(!(key in scrape), `scrape must not interpret ${key}`);
  }
});

// ── the two ends must fold labels identically ───────────────────────────
//
// The server hands down labels it has already reduced: lowercased, with
// combining marks stripped, so a pack author writes "motor gucu" once instead
// of enumerating every accented spelling. If this end folds differently the
// scan silently finds nothing — the exact failure mode the label scan exists
// to prevent, reintroduced by a mismatch nobody would think to look for.

test("an accented label on the page matches the server's folded spelling", () => {
  const s = loadContentScript(`
    <div class="row"><span>Motor Gücü</span><span>110 hp</span></div>`);
  assert.equal(s.buildScrape(["motor gucu"]).fields["Motor Gücü"], "110 hp");
});

test("Turkish dotted capital İ folds the same way the server folds it", () => {
  const s = loadContentScript(`
    <div class="row"><span>İlan No</span><span>1326798939</span></div>`);
  assert.equal(s.buildScrape(["ilan no"]).fields["İlan No"], "1326798939");
});

test("a trailing colon on the page's label does not defeat the match", () => {
  const s = loadContentScript(`
    <div class="row"><span>Yıl:</span><span>2014</span></div>`);
  assert.equal(s.buildScrape(["yıl"]).fields["Yıl:"], "2014");
});
