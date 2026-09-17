// The panel the reader sees over their own page, and the fact that none of it
// is written down in this extension any more.
//
// Two halves of one mechanism. The scraper reads the damage silhouette and the
// equipment block through selectors and words the adapter declared; the panel
// names, tones and interprets them through titles, hints and alert rules the
// same block declared. Between them they used to hold: four Turkish state
// headings, five Turkish-to-English equipment buckets, eleven alert rules with
// their thresholds, and the English advice attached to each. All of it was an
// extension release away from a site redesign, a second listing site, or a
// category that is not cars.
//
// The tests below matter more than they look. Before this change the suite
// asserted only that `damage_info` was *truthy* — which the old hardcoded
// version and a version that read nothing at all both satisfied. The whole
// rewrite passed the existing suite after one plumbing fix. So these assert
// the values.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { loadContentScript } = require("./harness.js");
const { loadPanel } = require("./hover_lite_harness.js");

// The shipped rules, not a copy of them. A test carrying its own block cannot
// notice the real one going stale, and going stale is the failure this whole
// change exists to make impossible.
const PANEL = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "..", "..", "packs", "cars", "adapters", "sahibinden.json"),
    "utf8"
  )
).local_panel;

// ── the scraper reads what the pack declared ────────────────────────────

// Real sahibinden markup: one block per state, its heading in Turkish, its
// parts as list items. The headings are spelled with the site's own diacritics
// on purpose — the adapter declares "degisen" and the fold is what makes those
// meet.
const DAMAGE_HTML = `
  <div class="car-damage-info-list">
    <h3>Değişen Parçalar</h3>
    <ul>
      <li class="selected-damage">Motor Kaputu</li>
      <li class="selected-damage">Sol Ön Çamurluk</li>
    </ul>
  </div>
  <div class="car-damage-info-list">
    <h3>Lokal Boyalı Parçalar</h3>
    <ul><li class="selected-damage">Sağ Arka Kapı</li></ul>
  </div>
  <div class="car-damage-info-list">
    <h3>Boyalı Parçalar</h3>
    <ul><li class="selected-damage">Tavan</li></ul>
  </div>`;

test("a damage state is read under the key the pack declared, not one we chose", () => {
  const s = loadContentScript(DAMAGE_HTML);
  const damage = s.buildScrape([], PANEL).listing.damage_info;
  assert.deepEqual(damage.changed, ["Motor Kaputu", "Sol Ön Çamurluk"]);
  assert.deepEqual(damage.painted, ["Tavan"]);
  assert.deepEqual(damage.local_painted, ["Sağ Arka Kapı"]);
});

test("the narrower heading wins, because the broader one is a substring of it", () => {
  // "Lokal Boyalı" contains "Boyalı". Precedence is the order of `states` in
  // the adapter, and a pack author who reverses it silently loses a state —
  // which is why the block says so and this test holds it.
  const s = loadContentScript(DAMAGE_HTML);
  const damage = s.buildScrape([], PANEL).listing.damage_info;
  assert.ok(!damage.painted.includes("Sağ Arka Kapı"), "local paint leaked into painted");
});

test("with no declared block the scraper reads nothing local and says so", () => {
  // Fails open. A page whose adapter declares no panel is a page we have no
  // rules for, and inventing rules is how a wrong answer gets rendered
  // confidently. `null` is distinguishable from "read it, found nothing".
  const s = loadContentScript(DAMAGE_HTML);
  const scrape = s.buildScrape([]);
  assert.equal(scrape.listing.damage_info, null);
  assert.deepEqual(scrape.listing.equipment, {});
});

test("a measure is read through the declared terms and currency table", () => {
  const s = loadContentScript(`
    <div class="tramer-box">Tramer: 22.500 TL</div>`);
  const damage = s.buildScrape([], PANEL).listing.damage_info;
  assert.equal(damage.tramer_amount, 22500);
  assert.equal(damage.tramer_currency, "TRY");
});

test("equipment lands in the buckets the pack named, in the pack's language", () => {
  const s = loadContentScript(`
    <div id="classifiedProperties">
      <h3>Güvenlik</h3>
      <ul><li class="selected">ABS</li><li class="unselected">ESP</li></ul>
      <h3>Multimedya</h3>
      <ul><li class="selected">Bluetooth</li></ul>
    </div>`);
  const equipment = s.buildScrape([], PANEL).listing.equipment;
  assert.deepEqual(equipment.Safety, ["ABS"]);
  assert.deepEqual(equipment.Multimedia, ["Bluetooth"]);
});

test("the presentation half rides with the local data and the selectors do not", () => {
  // The renderer needs titles, tones, hints, sides and rules. It does not need
  // selectors — the DOM has already been read by the time the scrape returns,
  // and handing them on would invite a second reader of the page.
  const s = loadContentScript(DAMAGE_HTML);
  const panel = s.buildScrape([], PANEL).listing.panel;
  assert.ok(panel.alerts.length, "no rules reached the renderer");
  assert.ok(panel.states.length, "no state labels reached the renderer");
  const serialised = JSON.stringify(panel);
  assert.ok(!serialised.includes("car-damage-info-list"), "a selector reached the renderer");
  assert.ok(!serialised.includes("legacy"), "the legacy fallback reached the renderer");
});

// ── the panel interprets what the pack declared ─────────────────────────

const RESULT = { claims: [], coverage: "RISKS_FOUND", identity: {}, context: {} };

/** Deliver one damage reading to a freshly opened panel. */
function withDamage(damage, panel = null) {
  const p = loadPanel();
  p.openPanel();
  const scraped = loadContentScript(DAMAGE_HTML);
  p.deliverEntry({
    ok: true,
    result: RESULT,
    listing: {
      damage_info: damage,
      equipment: {},
      panel: panel || scraped.presentationOf(PANEL),
    },
  });
  return p;
}

const alertTexts = (p) =>
  Array.from(p.shadow().querySelectorAll(".lite-alerts-row")).map((n) => n.textContent.trim());

test("a declared term fires its alert, matched through the fold", () => {
  const said = alertTexts(withDamage({ changed: ["Motor Kaputu"], painted: [] }));
  assert.equal(said.length, 1);
  assert.match(said[0], /^Hood replaced/);
});

test("panels replaced on one side are counted per declared side", () => {
  const said = alertTexts(
    withDamage({ changed: ["Sol Ön Kapı", "Sol Arka Kapı"], painted: [] })
  );
  assert.equal(said.length, 1);
  assert.match(said[0], /^2 panels replaced on the same side/);
});

test("`unless` keeps the broad rule quiet when the specific one already spoke", () => {
  // Three replaced panels, two of them on the same side. The old code wrote
  // this as `&& sameSideChanged < 2`; the format writes it as data, and the
  // reader must still see one alert rather than two saying the same thing.
  const said = alertTexts(
    withDamage({ changed: ["Sol Ön Kapı", "Sol Arka Kapı", "Sağ Ön Kapı"], painted: [] })
  );
  assert.equal(said.length, 1, said.join(" | "));
  assert.match(said[0], /same side/);
});

test("a painted panel that was also replaced does not get its own alert", () => {
  const said = alertTexts(withDamage({ changed: ["Tavan"], painted: ["Tavan"] }));
  assert.equal(said.length, 1);
  assert.match(said[0], /^Roof replaced/);
});

test("a measure below its declared threshold says nothing", () => {
  assert.deepEqual(alertTexts(withDamage({ changed: [], painted: [], tramer_amount: 900 })), []);
});

test("a measure above it prints the amount and the currency the page gave", () => {
  const said = alertTexts(
    withDamage({ changed: [], painted: [], tramer_amount: 40000, tramer_currency: "TRY" })
  );
  assert.equal(said.length, 1);
  assert.match(said[0], /40,000 TRY/);
});

test("no declared rules means no alerts, and no crash", () => {
  // The panel over a page whose pack ships no block. Silence is the correct
  // output; an exception here would take the whole panel down with it.
  const p = withDamage({ changed: ["Motor Kaputu"], painted: [] }, {});
  assert.deepEqual(alertTexts(p), []);
  assert.ok(p.listing(), "the panel itself stopped rendering");
});

test("the detail rows take their names and warnings from the pack", () => {
  const p = withDamage({ changed: ["Motor Kaputu"], painted: [], original: ["Tavan"] });
  const rows = Array.from(p.shadow().querySelectorAll(".lite-detrow"));
  const titles = rows.map((r) => r.dataset.row);
  assert.deepEqual(titles, ["Replaced"]);
  assert.match(
    rows[0].querySelector(".lite-detrow-hint").textContent,
    /removed and a new one installed/
  );
});

test("a state the pack declares without a title is read but not shown", () => {
  // An untouched panel is the absence of a finding. The rules still read it;
  // a row of them would bury the rows that are findings.
  const p = withDamage({ changed: [], painted: [], original: ["Tavan", "Kaput"] });
  assert.equal(p.shadow().querySelectorAll(".lite-detrow").length, 0);
});
