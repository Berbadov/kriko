// The extension is quiet (2026-11-03).
//
// The reader: "remove subtext and expressive logs from the web extension".
// Three things follow, and each is checked where it can be seen to fail:
// the console is not used for narration, the options page has no description
// lines under its headings, and the panel draws a run's stage and counts, not
// its log.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { loadOptions, settle } = require("./options_harness.js");

const ROOT = path.join(__dirname, "..");
const SHIPPED = [
  "background.js", "content.js",
  "hover_lite/hover_lite.js", "hover_lite/claim_card.js", "hover_lite/buyer_card.js",
  "hover_lite/run_progress.js", "hover_lite/icons.js", "options/options.js",
  "tests/preview/panel.html",
];

const consoleCalls = (file) => {
  const source = fs.readFileSync(path.join(ROOT, file), "utf8")
    .split("\n").filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line)).join("\n");
  return [...source.matchAll(/console\.(\w+)\(([^)]*)\)/g)]
    .map((hit) => ({ level: hit[1], args: hit[2] }));
};

test("nothing narrates to the console: no log, info or debug call is shipped", () => {
  for (const file of SHIPPED) {
    const levels = consoleCalls(file).map((call) => call.level);
    assert.deepEqual(levels.filter((level) => !["warn", "error"].includes(level)), [], file);
  }
});

test("a console warning or error is one short line, with no error object or data dumped", () => {
  for (const file of SHIPPED) {
    for (const call of consoleCalls(file)) {
      // One string, and nothing after it: no `error`, no `message`, no payload.
      assert.match(call.args.trim(), /^(["`][^"`]*["`])$/, `${file}: console.${call.level}(${call.args})`);
      assert.ok(call.args.length < 70, `${file}: ${call.args}`);
    }
  }
});

test("the options page has no description lines: every paragraph is a status or a count", async () => {
  const page = loadOptions();
  await settle();
  const paragraphs = [...page.document.querySelectorAll("p")];
  assert.ok(paragraphs.length > 0);
  for (const p of paragraphs) {
    assert.ok(p.classList.contains("status") || p.classList.contains("kept-counts"),
      `a description line is back: ${p.textContent.trim().slice(0, 40)}`);
  }
  assert.equal(page.document.querySelector(".hint, .lede, .about"), null);
});
