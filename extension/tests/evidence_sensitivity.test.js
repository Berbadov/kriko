// How much a finding stands on, a mark for it, and a setting for how much
// doubt to show (#263, the extension's half).
//
// The reader's words: "info sensitivity setting, showing or not showing thin
// evidences, with a indicator next to info cards". Done when a three-step
// setting decides which claims are drawn, each card carries a mark (solid,
// partial, thin) that says why on hover or focus, and hidden items are counted
// with a way to reveal them. The setting changes what is shown, never what is
// stored.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const { loadPanel } = require("./hover_lite_harness.js");
const { loadBackground, send } = require("./background_harness.js");
const { loadOptions, settle } = require("./options_harness.js");

// ── the pure part ───────────────────────────────────────────────────────
const dom = new JSDOM("<!doctype html><body></body>");
const sandbox = { window: dom.window, document: dom.window.document, console };
dom.window.__KrikoPanelIcons = { iconSvg: () => "", domainIconSvg: () => "" };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "hover_lite", "claim_card.js"), "utf8"), sandbox);
const card = dom.window.__KrikoPanelClaimCard;
const plain = (value) => JSON.parse(JSON.stringify(value));
const evidenceOf = (claim) => plain(card.evidenceOf(claim));

const src = (tier, extra = {}) => ({ url: "https://s.example/a", domain: "s.example", quote: "q", tier, ...extra });
const claim = (sources, extra = {}) => ({ claim_id: "c", pack_id: "p", title: "t", severity: "high", sources, ...extra });

test("two sources, one of them of a high trust tier, is solid", () => {
  const got = evidenceOf(claim([src("community"), src("manufacturer")]));
  assert.deepEqual(got, { level: "solid", reasons: [] });
});

test("a single source is partial, and says so", () => {
  const got = evidenceOf(claim([src("manufacturer")]));
  assert.deepEqual(got, { level: "partial", reasons: ["single_source"] });
});

test("sources that are all of a low trust tier are partial", () => {
  const got = evidenceOf(claim([src("community"), src("community")]));
  assert.deepEqual(got, { level: "partial", reasons: ["low_trust_tier"] });
});

test("a single source of a low trust tier is thin: two weaknesses", () => {
  const got = evidenceOf(claim([src("community")]));
  assert.equal(got.level, "thin");
  assert.deepEqual(got.reasons, ["single_source", "low_trust_tier"]);
});

test("nothing behind it is thin outright", () => {
  assert.deepEqual(evidenceOf(claim([])), { level: "thin", reasons: ["no_source"] });
  assert.equal(evidenceOf({ claim_id: "c", title: "t" }).level, "thin");
});

test("an absent trust tier is not a low one: only what a row says is held against it", () => {
  // A quick look's finding has sources and quotes but no tier at all.
  const got = evidenceOf(claim([{ url: "https://a.example", quote: "q" }, { url: "https://b.example", quote: "q" }]));
  assert.deepEqual(got, { level: "solid", reasons: [] });
  const mixed = evidenceOf(claim([src("community"), { url: "https://b.example", quote: "q" }]));
  assert.equal(mixed.level, "solid", "one row with no tier means trust is unknown, not low");
});

test("the engine's own verdict wins over the derived one, in either shape", () => {
  const weak = claim([src("community")]);
  assert.deepEqual(evidenceOf({ ...weak, thin: "solid" }), { level: "solid", reasons: [] });
  assert.deepEqual(evidenceOf({ ...weak, thin: { level: "partial", reasons: ["partial_quote"] } }),
    { level: "partial", reasons: ["partial_quote"] });
  assert.deepEqual(evidenceOf({ ...weak, thin: { thin: true, reasons: ["unmet_condition"] } }),
    { level: "thin", reasons: ["unmet_condition"] });
  assert.equal(evidenceOf({ ...claim([src("manufacturer"), src("manufacturer")]), thin: true }).level, "thin");
});

test("a verdict this does not understand falls back to deriving, never to hiding", () => {
  const good = claim([src("manufacturer"), src("community")]);
  for (const odd of ["maybe", 7, {}, { level: "wobbly" }, [], null]) {
    assert.equal(evidenceOf({ ...good, thin: odd }).level, "solid", JSON.stringify(odd));
  }
});

test("the setting has three steps and anything else shows everything", () => {
  const rows = [
    claim([src("manufacturer"), src("community")], { claim_id: "solid" }),
    claim([src("manufacturer")], { claim_id: "partial" }),
    claim([], { claim_id: "thin" }),
  ];
  const ids = (list) => plain(list).map((c) => c.claim_id);
  const by = (mode, reveal) => card.filterByEvidence(rows, mode, reveal);
  assert.deepEqual([ids(by("all").shown), ids(by("all").hidden)], [["solid", "partial", "thin"], []]);
  assert.deepEqual([ids(by("hide_thin").shown), ids(by("hide_thin").hidden)], [["solid", "partial"], ["thin"]]);
  assert.deepEqual([ids(by("strict").shown), ids(by("strict").hidden)], [["solid"], ["partial", "thin"]]);
  for (const odd of [undefined, null, "", "Strict", "hide-thin", 3]) {
    assert.equal(by(odd).hidden.length, 0, `${JSON.stringify(odd)} hid evidence`);
  }
  assert.equal(by("strict", true).hidden.length, 0, "revealing shows them all");
});

test("hidden findings are counted in words that are true for the step", () => {
  assert.equal(card.hiddenWords(3, "hide_thin"), "3 thin findings hidden");
  assert.equal(card.hiddenWords(1, "hide_thin"), "1 thin finding hidden");
  assert.equal(card.hiddenWords(2, "strict"), "2 findings hidden", "strict hides partial ones too, so not 'thin'");
  assert.equal(card.hiddenWords(3, "hide_thin", true), "3 thin findings shown");
});

// ── the mark on each card ───────────────────────────────────────────────
const markOf = (c) => card.renderClaimCard(c).querySelector(".lite-rc-ev");

test("every card carries a mark whose label says the level and why", () => {
  const thin = markOf(claim([src("community")]));
  assert.equal(thin.dataset.level, "thin");
  assert.equal(thin.getAttribute("role"), "img");
  assert.equal(thin.getAttribute("tabindex"), "0", "reachable by keyboard");
  assert.equal(thin.getAttribute("aria-label"),
    "Thin evidence: it rests on a single source; its sources are of a low trust tier");
  const part = markOf(claim([src("manufacturer")]));
  assert.equal(part.getAttribute("aria-label"), "Partial evidence: it rests on a single source");
  const solid = markOf(claim([src("community"), src("manufacturer")]));
  assert.match(solid.getAttribute("aria-label"), /^Solid evidence: /);
});

test("the mark's shape carries the level without colour: one, two or three bars lit", () => {
  const lit = (c) => markOf(c).querySelectorAll('rect[data-lit="1"]').length;
  assert.equal(lit(claim([src("community")])), 1);
  assert.equal(lit(claim([src("manufacturer")])), 2);
  assert.equal(lit(claim([src("community"), src("manufacturer")])), 3);
  assert.equal(markOf(claim([src("community")])).textContent.trim(), "Thin");
  assert.equal(markOf(claim([src("manufacturer")])).textContent.trim(), "Partial");
  assert.equal(markOf(claim([src("community"), src("manufacturer")])).textContent.trim(), "", "solid needs no word");
});

test("the card says what its mark is the engine's verdict on, with the engine's own reasons", () => {
  const mark = markOf(claim([src("community"), src("manufacturer")], { thin: { level: "thin", reasons: ["partial_quote", "unmet_condition"] } }));
  assert.equal(mark.dataset.level, "thin");
  assert.match(mark.getAttribute("aria-label"), /the quote only partly matches; it depends on a condition your product may not meet/);
});

// ── the panel applies the setting ───────────────────────────────────────
const row = (id, sources, extra = {}) => ({
  pack_id: "p", claim_id: id, title: id, body: `Details of ${id}`, severity: "high", domain: "components", sources, ...extra,
});
const answer = (claims, lookup_id = "a1") => ({
  ok: true, listing: {},
  result: { lookup_id, claims, identity: {}, context: {}, coverage: "RISKS_FOUND" },
});
const SOLID = row("solid-one", [src("manufacturer"), src("community")]);
const PARTIAL = row("partial-one", [src("manufacturer")], { severity: "medium" });
const THIN = row("thin-one", [], { severity: "low" });

function panelWith(sensitivity) {
  const p = loadPanel({ workerResponse: (m) => {
    if (m.type === "INFO_SENSITIVITY") return { ok: true, sensitivity };
    return { ok: true };
  } });
  p.openPanel();
  p.deliverEntry(answer([SOLID, PARTIAL, THIN]));
  return p;
}
const titles = (p) => [...p.shadow().querySelectorAll(".lite-rc-title")].map((t) => t.textContent);
const note = (p) => p.shadow().querySelector(".lite-thin-note");

test("by default everything is drawn and nothing is said to be hidden", () => {
  const p = panelWith("all");
  assert.deepEqual(titles(p).sort(), ["partial-one", "solid-one", "thin-one"]);
  assert.equal(note(p), null);
});

test("an app that cannot be asked never hides anything", () => {
  const p = loadPanel({ workerResponse: { ok: false, error: "Kriko is not running." } });
  p.openPanel();
  p.deliverEntry(answer([SOLID, PARTIAL, THIN]));
  assert.equal(titles(p).length, 3);
});

test("hide thin draws all but the thin card and counts it", () => {
  const p = panelWith("hide_thin");
  assert.deepEqual(titles(p).sort(), ["partial-one", "solid-one"]);
  assert.equal(note(p).querySelector(".lite-thin-text").textContent, "1 thin finding hidden");
  assert.equal(p.shadow().querySelector(".lite-claims-label").textContent, "Risks · 2");
});

test("strict draws only what is solid", () => {
  const p = panelWith("strict");
  assert.deepEqual(titles(p), ["solid-one"]);
  assert.equal(note(p).querySelector(".lite-thin-text").textContent, "2 findings hidden");
});

test("the severity counts follow what is drawn, so no number points at a card that is not there", () => {
  const p = panelWith("strict");
  const text = p.shadow().querySelector(".lite-counts-slot").textContent;
  assert.match(text, /1\s*serious/);
  assert.match(text, /0\s*worth checking/);
});

test("Show them reveals every card, and the note says so and can put them away again", () => {
  const p = panelWith("hide_thin");
  p.click(".lite-thin-toggle");
  assert.equal(titles(p).length, 3);
  assert.equal(note(p).querySelector(".lite-thin-text").textContent, "1 thin finding shown");
  assert.equal(note(p).querySelector(".lite-thin-toggle").getAttribute("aria-pressed"), "true");
  p.click(".lite-thin-toggle");
  assert.equal(titles(p).length, 2);
});

test("a different answer starts hidden again, so a reveal never outlives what it was for", () => {
  const p = panelWith("hide_thin");
  p.click(".lite-thin-toggle");
  p.deliverEntry(answer([SOLID, THIN], "a2"));
  assert.deepEqual(titles(p), ["solid-one"]);
});

test("when every claim is held back the panel says so instead of saying nothing matched", () => {
  const p = loadPanel({ workerResponse: (m) => (m.type === "INFO_SENSITIVITY" ? { ok: true, sensitivity: "strict" } : { ok: true }) });
  p.openPanel();
  p.deliverEntry(answer([THIN, PARTIAL]));
  assert.equal(titles(p).length, 0);
  assert.equal(note(p).querySelector(".lite-thin-text").textContent, "2 findings hidden");
  assert.equal(p.shadow().querySelector(".lite-gap"), null, "held back is not a gap in what is known");
  assert.doesNotMatch(p.claims().textContent, /Nothing matched/);
});

test("the setting is hidden from the card only: the answer itself is untouched", () => {
  const p = panelWith("strict");
  p.click(".lite-thin-toggle");
  assert.equal(titles(p).length, 3);
  // Expand all still means every card on screen, not every card in the answer.
  p.click(".lite-thin-toggle");
  p.click(".lite-chip-expand");
  assert.ok([...p.shadow().querySelectorAll(".lite-rc")].every((c) => c.dataset.open === "1"));
});

test("a mark shows its reason on focus, in one tip that the card cannot clip", () => {
  const p = panelWith("all");
  const mark = p.shadow().querySelector('.lite-rc-ev[data-level="thin"]');
  mark.dispatchEvent(new p.dom.window.FocusEvent("focusin", { bubbles: true }));
  const tip = p.shadow().querySelector(".lite-ev-tip");
  assert.equal(tip.hidden, false);
  assert.equal(tip.textContent, "Thin evidence: no source is attached");
  assert.equal(tip.parentElement, p.shadow().querySelector(".lite-panel"));
  mark.dispatchEvent(new p.dom.window.FocusEvent("focusout", { bubbles: true }));
  assert.equal(tip.hidden, true);
});

// ── the worker and the options page: one setting, the app's ─────────────
test("the worker reads the app's setting and calls anything unknown 'all'", async () => {
  for (const [stored, wanted] of [["hide_thin", "hide_thin"], ["strict", "strict"], ["all", "all"],
    [undefined, "all"], ["everything", "all"]]) {
    const settings = stored === undefined ? { mode: "buyer" } : { info_sensitivity: stored };
    const h = loadBackground({ routes: { "/api/settings": settings } });
    const reply = await send(h, { type: "INFO_SENSITIVITY" });
    assert.equal(reply.ok, true);
    assert.equal(reply.sensitivity, wanted);
  }
});

test("with the app closed the worker answers all, and says it could not ask", async () => {
  const h = loadBackground({ offline: true });
  const reply = await send(h, { type: "INFO_SENSITIVITY" });
  assert.equal(reply.ok, false);
  assert.equal(reply.sensitivity, "all");
});

test("the worker writes the setting to the app's own settings route, and refuses a value it does not know", async () => {
  const h = loadBackground({ routes: { "/api/settings": (body) => ({ info_sensitivity: body.values.info_sensitivity }) } });
  const reply = await send(h, { type: "SET_INFO_SENSITIVITY", payload: { sensitivity: "strict" } });
  assert.deepEqual([reply.ok, reply.sensitivity], [true, "strict"]);
  const posted = h.state.requests.find((r) => r.method === "POST" && r.url.endsWith("/api/settings"));
  assert.deepEqual(posted.body, { values: { info_sensitivity: "strict" } });
  const bad = await send(h, { type: "SET_INFO_SENSITIVITY", payload: { sensitivity: "none" } });
  assert.equal(bad.ok, false);
  assert.equal(h.state.requests.filter((r) => r.method === "POST").length, 1, "a refused value never reached the app");
});

test("the options page shows the app's choice and saves a change through the worker", async () => {
  const asked = [];
  const page = loadOptions({ answer: (message) => {
    asked.push(message);
    if (message.type === "INFO_SENSITIVITY") return { ok: true, sensitivity: "hide_thin" };
    if (message.type === "SET_INFO_SENSITIVITY") return { ok: true, sensitivity: message.payload.sensitivity };
    return undefined;
  } });
  await settle();
  const checked = () => page.document.querySelector('input[name="sensitivity"]:checked').value;
  assert.equal(checked(), "hide_thin");
  const strict = page.document.querySelector('input[name="sensitivity"][value="strict"]');
  strict.checked = true;
  strict.dispatchEvent(new page.window.Event("change"));
  await settle();
  assert.equal(asked.find((m) => m.type === "SET_INFO_SENSITIVITY").payload.sensitivity, "strict");
  assert.equal(page.document.getElementById("sensitivity-status").textContent, "Saved.");
});

test("with the app closed the options page says it cannot read or keep the choice", async () => {
  const page = loadOptions({ answer: (message) => (message.type === "INFO_SENSITIVITY" ? { ok: false, error: "no app" } : undefined) });
  await settle();
  assert.ok([...page.document.querySelectorAll('input[name="sensitivity"]')].every((r) => r.disabled));
  assert.match(page.document.getElementById("sensitivity-status").textContent, /not running/);
});
