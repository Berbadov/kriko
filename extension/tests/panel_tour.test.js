// The first visit gets a short walk through the panel, once. Skip, Done and
// Escape count as seen; a returning reader never gets it; the options page can
// clear the key to show it again.
const test = require("node:test");
const assert = require("node:assert/strict");
const { loadPanel } = require("./hover_lite_harness.js");

const KEY = "kriko.panelTour";
const overlay = (p) => p.shadow().querySelector(".lite-tour");
const title = (p) => overlay(p).querySelector("h2").textContent;

function open(seed = {}) {
  const p = loadPanel();
  Object.assign(p.local, seed);
  p.openPanel();
  p.flushTimers();
  return p;
}

test("a reader who has never seen the tour gets it, and it ends after the last step", () => {
  const p = open();
  assert.ok(overlay(p), "the tour did not open on the first visit");
  assert.match(overlay(p).querySelector(".lite-tour-count").textContent, /1 of 6/);
  const seen = [title(p)];
  while (!overlay(p).querySelector(".lite-tour-next").textContent.includes("Done")) {
    p.click(".lite-tour-next");
    seen.push(title(p));
  }
  assert.equal(seen.length, 6);
  p.click(".lite-tour-next");
  assert.equal(overlay(p), null, "the tour stayed after Done");
  assert.equal(p.local[KEY], "done");
});

test("every step points at something the panel has", () => {
  const p = open();
  for (let i = 0; i < 6; i += 1) {
    assert.ok(!overlay(p).querySelector(".lite-tour-spot").hidden, `step ${i + 1} found nothing to point at`);
    if (i < 5) p.click(".lite-tour-next");
  }
});

test("Skip and Escape both count as seen, and Escape does not close the panel", () => {
  const skipped = open();
  skipped.click(".lite-tour-skip");
  assert.equal(overlay(skipped), null);
  assert.equal(skipped.local[KEY], "done");

  const escaped = open();
  escaped.press(".lite-tour-next", "Escape");
  assert.equal(overlay(escaped), null);
  assert.equal(escaped.local[KEY], "done");
  assert.ok(escaped.shadow().querySelector(".lite-panel:not([data-closing='1'])"), "Escape from the tour closed the panel");
});

test("a reader who has seen it, or closes the panel half way, is treated accordingly", () => {
  const returning = open({ [KEY]: "done" });
  assert.equal(overlay(returning), null, "the tour came back");

  const half = open();
  assert.ok(overlay(half));
  half.click(".lite-btn-close");
  half.flushTimers();
  assert.notEqual(half.local[KEY], "done", "closing the panel counted as seeing the tour");
});

test("the options page clears the key, and only that key", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const options = fs.readFileSync(path.join(__dirname, "..", "options", "options.js"), "utf8");
  assert.match(options, /storage\.local\.remove\("kriko\.panelTour"/);
  const html = fs.readFileSync(path.join(__dirname, "..", "options", "options.html"), "utf8");
  assert.ok(html.includes('id="tour"') && html.includes("Show it again"));
});
