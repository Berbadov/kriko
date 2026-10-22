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
