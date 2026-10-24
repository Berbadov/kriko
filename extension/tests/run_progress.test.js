// A running look-up shown as real stages and true page counts (#262).
//
// The reader's words: "revamp of web extension progress bars text and info
// representation". Done when progress shows real stages (reading the page,
// searching, reading sources, checking quotes) with the true count of pages
// read out of attempted, not an invented percentage, and the words say what
// is happening now. The log lines below are the engine's own wording
// (local_agent.py `_say`, harness.py `_tool_line`), not invented ones.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "hover_lite", "run_progress.js"), "utf8"), sandbox);
// Out of the vm realm, so deepEqual compares values and not prototypes.
const plain = (value) => JSON.parse(JSON.stringify(value));
const mod = sandbox.window.__KrikoRunProgress;
const describeRun = (job) => plain(mod.describeRun(job));
const coverageSummary = (coverage) => plain(mod.coverageSummary(coverage));
const STAGES = plain(mod.STAGES);

const log = (...lines) => lines.join("\n");
const running = (lines, extra = {}) => describeRun({ kind: "quick_look", state: "running", log: log(...lines), ...extra });
const states = (run) => run.stages.map((s) => s.state);

const SEARCH = ["search language: en; queries: gearbox judder; clutch problems", "searching: gearbox judder known problems"];
const READS = ["found 6 page(s); reading up to 6", "read: https://a.example/1", "read: https://a.example/2",
  "could not read: https://b.example/blocked", "read: https://a.example/3"];

test("the four stages are the ones a run really has, in order", () => {
  assert.deepEqual(STAGES.map((s) => s.label),
    ["Reading the page", "Searching", "Reading sources", "Checking quotes"]);
});

test("a run that has said nothing yet is on the first stage and claims no counts", () => {
  const run = describeRun({ kind: "quick_look", state: "queued", log: "" });
  assert.deepEqual(states(run), ["now", "todo", "todo", "todo"]);
  assert.equal(run.headline, "Reading the page");
  assert.equal(run.pages, "");
  assert.equal(run.detail, "");
});

test("searching moves the run to the second stage and counts the searches it ran", () => {
  const run = running(SEARCH);
  assert.deepEqual(states(run), ["done", "now", "todo", "todo"]);
  assert.equal(run.headline, "Searching");
  assert.equal(run.counts.searches, 1);
  assert.equal(run.detail, "1 search run");
  const two = running(["searching: a; b", 'searched "c"']);
  assert.equal(two.counts.searches, 3);
});

test("pages read are counted out of pages attempted, never out of a guess", () => {
  const run = running([...SEARCH, ...READS]);
  assert.deepEqual(states(run), ["done", "done", "now", "todo"]);
  assert.equal(run.headline, "Reading sources");
  assert.deepEqual([run.counts.read, run.counts.failed, run.counts.attempted], [3, 1, 4]);
  assert.equal(run.pages, "3 of 4 pages read");
  // "found 6" is what the run planned, not what it did: not in the count.
  assert.doesNotMatch(run.pages, /6/);
});

test("when every page tried was read it says so without an 'of'", () => {
  const run = running([...SEARCH, "read: https://a.example/1", "read: https://a.example/2"]);
  assert.equal(run.pages, "2 pages read");
  assert.equal(running([...SEARCH, "read: https://a.example/1"]).pages, "1 page read");
});

test("extracting a source is the quote-checking stage, and says which source", () => {
  const run = running([...SEARCH, ...READS, "extracting source 2/4: https://a.example/2"]);
  assert.deepEqual(states(run), ["done", "done", "done", "now"]);
  assert.equal(run.headline, "Checking quotes");
  assert.equal(run.detail, "source 2 of 4");
  assert.equal(run.pages, "3 of 4 pages read", "the page count stays while quotes are checked");
  assert.match(run.spoken, /Step 4 of 4: Checking quotes/);
});

test("the CLI agent's own tool lines place the run too", () => {
  const run = running(['searched "gearbox judder"', "fetched https://a.example/1", "fetched https://a.example/2"]);
  assert.equal(run.headline, "Reading sources");
  assert.equal(run.counts.read, 2);
});

test("a stage is never taken back by a later line that looks earlier", () => {
  const run = running([...SEARCH, ...READS, "extracting source 1/4: x", 'searched "one more"']);
  assert.equal(run.headline, "Checking quotes");
});

test("a page title that merely contains a stage word moves nothing", () => {
  const run = running(["page fetched; checking product match: https://a.example/reading-searching"]);
  assert.equal(run.headline, "Reading the page");
});

test("no figure is a percentage", () => {
  const run = running([...SEARCH, ...READS], { progress: 0.45 });
  for (const text of [run.headline, run.detail, run.pages, run.spoken]) assert.doesNotMatch(text, /%|percent/i);
});

test("a finished run takes its counts from its own coverage block", () => {
  const run = describeRun({
    kind: "quick_look", state: "succeeded", done: true,
    log: log(...SEARCH, "read: https://a.example/1"),
    result: { coverage: { pages_read: 7, pages_unreadable: 1, pages_timed_out: 1 } },
  });
  assert.equal(run.finished, true);
  assert.equal(run.pages, "7 of 9 pages read");
  assert.deepEqual(states(run), ["done", "done", "done", "done"]);
  assert.equal(run.headline, "Done");
});

test("a run that stopped early marks the stage it stopped on", () => {
  const run = describeRun({ kind: "quick_look", state: "failed", done: true, log: log(...SEARCH, ...READS) });
  assert.deepEqual(states(run), ["done", "done", "stopped", "todo"]);
  assert.equal(run.headline, "Stopped early");
  assert.equal(describeRun({ kind: "quick_look", state: "cancelled", done: true, log: "" }).headline, "Stopped");
});

test("a job whose log says nothing this knows has no stages, only its own message", () => {
  const run = describeRun({ kind: "pack_author", state: "running", message: "Filing it", log: "writing the draft" });
  assert.equal(run.staged, false);
  assert.equal(run.stages, null);
  assert.equal(run.headline, "Filing it");
});

test("a job that is not a quick look is staged once its log reaches a stage", () => {
  const run = describeRun({ kind: "research", state: "running", log: log(...SEARCH) });
  assert.equal(run.staged, true);
  assert.equal(run.headline, "Searching");
});

test("what a finished look covered is said pages first, and a zero is said, not hidden", () => {
  const some = coverageSummary({ pages_read: 4, pages_unreadable: 1, pages_relevant: 2, pages_extracted: 2, sources_cited: 1 });
  assert.equal(some.pages, "4 of 5 pages read");
  assert.deepEqual(some.rest, ["2 about this product", "2 checked", "1 cited"]);
  const none = coverageSummary({ pages_read: 3, pages_relevant: 0, sources_cited: 0 });
  assert.equal(none.pages, "3 pages read");
  assert.deepEqual(none.rest, ["0 about this product", "0 cited"], "a run that cited nothing says so");
  // A figure the run never reported is left out rather than shown as 0.
  assert.deepEqual(coverageSummary({ pages_read: 2 }).rest, []);
  assert.deepEqual(coverageSummary(null), { pages: "", rest: [] });
});

test("a run that reported no pages is not said to have read none; a reported zero still is", () => {
  // A quick look whose agent searched for itself reports `{}`. That is not a
  // reading of zero pages, so the count is left out.
  assert.deepEqual(coverageSummary({}), { pages: "", rest: [] });
  assert.equal(mod.reportsPages({}), false);
  assert.equal(mod.reportsPages(null), false);
  // A zero the run did report is a finding, and is said.
  assert.equal(mod.reportsPages({ pages_read: 0 }), true);
  assert.equal(coverageSummary({ pages_read: 0 }).pages, "0 pages read");
});
