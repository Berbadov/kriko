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

// ── English locale (the live failure) ───────────────────────────────────────
//
// Sahibinden serves the listing in English for some users: the info-list labels
// are "Make"/"Series"/"Year"/"Fuel Type"/"Gear"/"KM", not the Turkish ones the
// scraper knew. Every label missed, the info list read as empty, and the backend
// answered "Missing required fields: ['make', 'fuel']". Fixture is a real
// captured page.

test("english locale: every field the matcher requires is extracted", () => {
  const s = loadContentScript(fixture("sahibinden_english.html"));
  const m = s.buildMetadata();

  assert.equal(m.make, "Volkswagen");
  assert.equal(m.model, "Golf");        // "Series" holds the model name
  assert.equal(m.trim, "1.2 TSI Comfortline");  // "Model" holds the trim
  assert.equal(m.year, 2016);
  assert.equal(m.fuel_type, "Gasoline");
  // The technical panel's "Transmission / Drive Type" ("DSG / 7 Gear / Front
  // Wheel Drive") wins over the info list's "Gear: Automatic" — deliberately:
  // it names the actual gearbox family, and normalize_transmission maps DSG to
  // automatic anyway. The drive type is the LAST segment, not the second.
  assert.equal(m.transmission, "DSG");
  assert.equal(m.drivetrain, "Front Wheel Drive");
  assert.equal(m.mileage_km, 132000);           // label is "KM"
  assert.equal(m.power_hp, 110);
  assert.equal(m.engine_volume_cc, 1197);
});

test("english locale: 'Engine Capacity' reading '110 hp' is not taken as cc", () => {
  // Sahibinden's own bug: the Overview table labels the POWER row
  // "Engine Capacity" (110 hp), while the real capacity (1197 cc) is in the
  // Engine and Performance table under the same label. Taking the first hit
  // would send the matcher engine_volume_cc=110 and match nothing.
  const s = loadContentScript(fixture("sahibinden_english.html"));
  assert.equal(s.buildMetadata().engine_volume_cc, 1197);
});

test("english locale: 'Fuel Consumption' is not mistaken for the fuel type", () => {
  const s = loadContentScript(fixture("sahibinden_english.html"));
  assert.equal(s.buildMetadata().fuel_type, "Gasoline");
});
