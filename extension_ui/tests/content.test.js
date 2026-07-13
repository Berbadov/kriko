// Scraper regression tests. The listing scraper had no tests, which is exactly
// why a label change could silently zero out a required field: the extension
// still "worked", the backend just answered "Missing required fields".
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { loadContentScript } = require("./harness.js");

const fixture = (name) =>
  fs.readFileSync(path.join(__dirname, "fixtures", name), "utf8");

// ── Classic markup: <ul class="classifiedInfoList"> ──────────────────────────

test("classic info list: every field the matcher requires is extracted", () => {
  const s = loadContentScript(fixture("sahibinden_classic.html"));
  const m = s.buildMetadata();

  assert.equal(m.make, "Volkswagen");
  assert.equal(m.model, "Golf");
  assert.equal(m.year, 2014);
  // Regression: the info-list label is bare "Yakıt", not "Yakıt Tipi". The
  // mapping only carried "yakıt tipi", so fuel_type came back null and the
  // backend rejected the listing with Missing required fields: ['fuel'].
  assert.equal(m.fuel_type, "Dizel");
  assert.equal(m.transmission, "Otomatik");
  assert.equal(m.engine_volume_cc, 1598);
  assert.equal(m.power_hp, 105);
  assert.equal(m.mileage_km, 190000);
});

test("'Yakıt Tipi' (technical-details spelling) still maps to fuel_type", () => {
  const s = loadContentScript(`
    <h1>2014 Volkswagen Golf</h1>
    <ul class="classifiedInfoList">
      <li><strong>Yakıt Tipi</strong><span>Benzin</span></li>
    </ul>`);
  assert.equal(s.buildMetadata().fuel_type, "Benzin");
});

test("'Yakıt Tüketimi' / 'Yakıt Deposu' are NOT mistaken for the fuel type", () => {
  // A bare "yakıt" substring match would otherwise capture consumption/tank
  // size and hand the matcher garbage like "4,5 lt" as a fuel.
  const s = loadContentScript(`
    <h1>2014 Volkswagen Golf</h1>
    <ul class="classifiedInfoList">
      <li><strong>Yakıt Tüketimi</strong><span>4,5 lt</span></li>
      <li><strong>Yakıt Deposu</strong><span>50 lt</span></li>
    </ul>`);
  assert.equal(s.buildMetadata().fuel_type, null);
});

// ── Resilience: the info list is the single point of failure ─────────────────

test("year falls back to the title when the info list cannot be read", () => {
  // The live failure: a DOM the info-list selectors don't match. make/model
  // already fall back to the title; year did not, so it came back null and the
  // backend rejected the listing with Missing required fields: ['year'].
  const s = loadContentScript(`
    <h1 class="classifiedTitle">2014 Volkswagen Golf 1.6 TDI Comfortline</h1>
    <div class="some-new-layout">nothing the selectors know</div>`);
  const m = s.buildMetadata();
  assert.equal(m.make, "Volkswagen");
  assert.equal(m.model, "Golf");
  assert.equal(m.year, 2014);
});

test("a title with no year does not invent one", () => {
  const s = loadContentScript(`<h1>Volkswagen Golf 1.6 TDI</h1>`);
  assert.equal(s.buildMetadata().year, null);
});

test("a number in the title that is not a plausible model year is ignored", () => {
  const s = loadContentScript(`<h1>Volkswagen Golf 1.6 TDI 190.000 km</h1>`);
  assert.equal(s.buildMetadata().year, null);
});

// ── Layout-agnostic fallback ────────────────────────────────────────────────

test("labels are still found when the info list uses an unknown container", () => {
  // Sahibinden has redesigned this markup repeatedly. When no known selector
  // matches, fall back to scanning for the known Turkish labels themselves, so
  // a class rename degrades gracefully instead of zeroing every field.
  const s = loadContentScript(`
    <h1>2014 Volkswagen Golf 1.6 TDI</h1>
    <div class="brand-new-info-wrapper">
      <div class="row"><span>Yıl</span><span>2014</span></div>
      <div class="row"><span>Yakıt</span><span>Dizel</span></div>
      <div class="row"><span>Vites</span><span>Otomatik</span></div>
      <div class="row"><span>Kilometre</span><span>190.000</span></div>
    </div>`);
  const m = s.buildMetadata();
  assert.equal(m.year, 2014);
  assert.equal(m.fuel_type, "Dizel");
  assert.equal(m.transmission, "Otomatik");
  assert.equal(m.mileage_km, 190000);
});
