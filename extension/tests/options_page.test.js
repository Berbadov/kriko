// The options page, as the reader meets it.
const test = require("node:test");
const assert = require("node:assert");

const { loadOptions, settle } = require("./options_harness.js");

const PENDING = [{ site: "otoparca.example", pattern: "https://*.otoparca.example/*", state: "pending" }];

test("the step the worker opened the page for is ringed, scrolled to and given the keyboard", async () => {
  const page = loadOptions({ local: { krikoOptionsFocus: "sites" }, sites: PENDING });
  await settle();
  const section = page.document.getElementById("sites-section");
  assert.equal(section.dataset.focus, "1");
  assert.equal(section.dataset.scrolled, "1");
  assert.equal(page.document.activeElement, page.document.getElementById("grant"));
  assert.equal(page.document.getElementById("form").dataset.focus, undefined, "only one step is marked");
  assert.equal("krikoOptionsFocus" in page.bag, false, "read once, so a plain visit later marks nothing");
});

test("the address step puts the keyboard in the address field", async () => {
  const page = loadOptions({ local: { krikoOptionsFocus: "address" } });
  await settle();
  assert.equal(page.document.getElementById("form").dataset.focus, "1");
  assert.equal(page.document.activeElement, page.document.getElementById("base"));
});

test("a plain visit marks nothing", async () => {
  const page = loadOptions({ sites: PENDING });
  await settle();
  assert.equal(page.document.querySelector("[data-focus]"), null);
});

test("opening the page again while it is open moves the ring to the new step", async () => {
  const page = loadOptions({ local: { krikoOptionsFocus: "address" } });
  await settle();
  page.set({ krikoOptionsFocus: "sites" });
  await settle();
  assert.equal(page.document.getElementById("sites-section").dataset.focus, "1");
  assert.equal(page.document.getElementById("form").dataset.focus, undefined);
});

// ── the off switch, and what Kriko kept (E7) ────────────────────────────
//
// The grant to read pages covers the whole web; there was no way to leave one
// site alone, and no surface that said what the extension had kept or that
// let the reader clear it. Both are the worker's answers, rendered here.

const MUTED = [{ site: "otoparca.example", pattern: "https://*.otoparca.example/*", state: "muted" }];
const ACTIVE = [{ site: "otoparca.example", pattern: "https://*.otoparca.example/*", state: "active" }];

test("a site the reader stopped reading says so, and offers to read it again", async () => {
  const page = loadOptions({ sites: MUTED });
  await settle();
  const row = page.document.querySelector("#sites li");
  assert.equal(row.dataset.state, "muted");
  assert.match(row.querySelector(".site-state").textContent, /not read/);
  assert.equal(row.querySelector(".site-mute").textContent, "Read this site");
});

test("stopping a site, and starting it again, are asked of the worker", async () => {
  const page = loadOptions({ sites: ACTIVE });
  await settle();
  page.document.querySelector("#sites .site-mute").click();
  await settle();
  assert.deepEqual(page.sent.find((m) => m.type === "KRIKO_SET_MUTED").payload,
    { site: "otoparca.example", muted: true });

  const back = loadOptions({ sites: MUTED });
  await settle();
  back.document.querySelector("#sites .site-mute").click();
  await settle();
  assert.deepEqual(back.sent.find((m) => m.type === "KRIKO_SET_MUTED").payload,
    { site: "otoparca.example", muted: false });
});

test("what Kriko kept is a count, and never an address", async () => {
  const page = loadOptions({ answer: (m) => (m.type === "KRIKO_KEPT"
    ? { ok: true, kept: { answers: 3, pages: 5, intents: 1, sites: 2, muted: [] } }
    : undefined) });
  await settle();
  const text = page.document.getElementById("kept-counts").textContent;
  assert.match(text, /3 saved answers/);
  assert.match(text, /5 pages/);
  assert.match(text, /1 retry id/);
  assert.doesNotMatch(text, /otoparca|example|https?:/);
});

test("clearing asks for one store at a time and repaints from the answer", async () => {
  const page = loadOptions({ answer: (m) => (m.type === "KRIKO_CLEAR"
    ? { ok: true, kept: { answers: 0, pages: 5, intents: 0, sites: 0, muted: [] } }
    : undefined) });
  await settle();
  page.document.getElementById("clear-answers").click();
  await settle();
  assert.deepEqual(page.sent.find((m) => m.type === "KRIKO_CLEAR").payload, { what: "answers" });
  assert.match(page.document.getElementById("kept-counts").textContent, /5 pages/);
  assert.match(page.document.getElementById("kept-status").textContent, /saved answers are gone/);
});

test("a cache that stopped being written is said here, not only in the console", async () => {
  const page = loadOptions({ answer: (m) => (m.type === "KRIKO_KEPT"
    ? { ok: true, kept: { answers: 0, pages: 0, intents: 0, sites: 0, muted: [],
        trouble: { at: 1, detail: "QUOTA_BYTES quota exceeded" } } }
    : undefined) });
  await settle();
  assert.match(page.document.getElementById("kept-status").textContent, /storage is full/i);
});
