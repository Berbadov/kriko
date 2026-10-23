// The panel's research card tells a run's real stage and page counts (#262).
const test = require("node:test");
const assert = require("node:assert/strict");
const { loadPanel } = require("./hover_lite_harness.js");

const LOG = [
  "search language: en; queries: gearbox judder",
  "searching: gearbox judder known problems",
  "found 6 page(s); reading up to 6",
  "read: https://a.example/1",
  "read: https://a.example/2",
  "could not read: https://b.example/blocked",
  "read: https://a.example/3",
].join("\n");

function research(job) {
  const p = loadPanel({ workerResponse: (m) => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "q", kind: "quick_look" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "q", kind: "quick_look", ...job } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example product" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example product");
  p.click(".lite-research-start");
  return p;
}

const segs = (p) => [...p.shadow().querySelectorAll(".lite-run-seg")].map((s) => s.dataset.state);

test("a run in flight shows its stage, which pages were read, and no percentage", () => {
  const p = research({ state: "running", log: LOG, progress: 0.4, message: "a quick look at Example product" });
  const run = p.shadow().querySelector(".lite-run");
  assert.equal(run.hidden, false);
  assert.deepEqual(segs(p), ["done", "done", "now", "todo"]);
  const bar = run.querySelector("[role=progressbar]");
  assert.equal(bar.getAttribute("aria-valuenow"), "3");
  assert.equal(bar.getAttribute("aria-valuemax"), "4");
  assert.match(bar.getAttribute("aria-valuetext"), /Step 3 of 4: Reading sources, 3 of 4 pages read/);
  assert.match(run.querySelector(".lite-run-facts").textContent, /Step 3 of 4 . 3 of 4 pages read/);
  const status = p.shadow().querySelector(".lite-research-status").textContent;
  assert.match(status, /^Reading sources . \d+s$/);
  assert.doesNotMatch(p.shadow().querySelector(".lite-research").textContent, /%|45|40/);
  assert.equal(p.shadow().querySelector(".lite-progress"), null, "the invented fill is gone from the card");
});

test("a run that has not said anything yet starts on reading the page", () => {
  const p = research({ state: "queued", log: "" });
  assert.deepEqual(segs(p), ["now", "todo", "todo", "todo"]);
  assert.match(p.shadow().querySelector(".lite-research-status").textContent, /^Reading the page/);
  assert.equal(p.shadow().querySelector(".lite-run-facts").textContent, "Step 1 of 4");
});

test("a finished run leaves no stage bar behind", () => {
  const p = research({ state: "succeeded", done: true, log: LOG,
    result: { risks: [], specs: [], coverage: { pages_read: 3, pages_unreadable: 1, pages_relevant: 1, pages_extracted: 1, sources_cited: 0 } } });
  assert.equal(p.shadow().querySelector(".lite-run").hidden, true);
  // What it covered is said pages first, out of those tried.
  assert.match(p.shadow().querySelector(".lite-noissue-stats").textContent, /3\s*of 4\s*pages read/);
  assert.match(p.shadow().querySelector(".lite-noissue-stats").textContent, /0\s*cited/);
});

// ── a poll that stops when nobody is looking (D9) ───────────────────────
//
// The stage bar is refreshed by a request a second. Nothing ended that loop:
// closing the panel took the DOM away and left the timer, so a closed panel
// kept waking the worker for the life of the tab, and a background tab did
// the same. `pollLive` had the guard; the run poller grew without it.

const jobStatuses = (p) => p.sent.filter((m) => m.type === "JOB_STATUS").length;

test("closing the panel ends the poll instead of asking the worker forever", () => {
  const p = research({ state: "running", log: LOG });
  const first = jobStatuses(p);
  assert.ok(first >= 1, "the run was not polled at all");
  p.flushTimers();
  assert.ok(jobStatuses(p) > first, "the poll stopped while the panel was open");
  const open = jobStatuses(p);
  p.click(".lite-btn-close");
  p.flushTimers();
  p.flushTimers();
  assert.equal(jobStatuses(p), open, "a closed panel kept asking the worker");
});

test("a background tab parks the poll, and looking again picks the run up", () => {
  const p = research({ state: "running", log: LOG });
  const doc = p.dom.window.document;
  Object.defineProperty(doc, "hidden", { value: true, configurable: true });
  const open = jobStatuses(p);
  p.flushTimers();
  assert.equal(jobStatuses(p), open, "a hidden tab kept asking the worker");
  Object.defineProperty(doc, "hidden", { value: false, configurable: true });
  doc.dispatchEvent(new p.dom.window.Event("visibilitychange"));
  assert.ok(jobStatuses(p) > open, "coming back did not resume the run");
});

// ── the stage comes from the run's own log (phase 3) ────────────────────
//
// The panel read the stage out of the job row, which carries up to 64 KB of
// the run's log and is re-sent whole on every tick. It now reads
// `/api/jobs/{id}/log` through the worker's JOB_PROGRESS, from a cursor: the
// whole log once, then only what the run has written since. `docs/DESIGN.md`:
// "the browser extension reads its stage from the run's own log".

const page = (text, cursor, total, done = false) => ({
  text, next_cursor: cursor, total_chars: total, eof: done, done,
});

function loggedRun(pages, jobState = "running", progress = null) {
  const asked = [];
  const p = loadPanel({ workerResponse: (m) => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "q", kind: "quick_look" } };
    if (m.type === "JOB_PROGRESS") {
      asked.push(m.payload.cursor);
      if (progress) return progress(m);
      return { ok: true, page: pages[Math.min(asked.length - 1, pages.length - 1)] };
    }
    if (m.type === "JOB_STATUS") {
      return { ok: true, job: { job_id: "q", kind: "quick_look", state: jobState,
                               done: jobState !== "running" } };
    }
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example product" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example product");
  p.click(".lite-research-start");
  return { p, asked };
}

test("a run's stage is read from its own log, and only the new part is asked for", () => {
  const first = "search language: en; queries: gearbox judder\n";
  const second = "read: https://a.example/1\nread: https://a.example/2\n";
  const { p, asked } = loggedRun([
    page(first, first.length, first.length),
    page(second, first.length + second.length, first.length + second.length),
  ]);
  assert.deepEqual(asked, [0], "the first tick did not read the log");
  assert.deepEqual(segs(p), ["done", "now", "todo", "todo"]);
  p.flushTimers();
  assert.deepEqual(asked, [0, first.length],
    "the second tick asked from the beginning again");
  assert.deepEqual(segs(p), ["done", "done", "now", "todo"],
    "the stage did not move on with the lines that arrived");
  assert.match(p.shadow().querySelector(".lite-run-facts").textContent, /2 of 2 pages read|2 pages read/);
});

test("the job row is fetched once, when the log says the run is over", () => {
  const { p } = loggedRun([page("searching: x\nread: https://a.example/1\n", 40, 40, true)], "succeeded");
  assert.equal(p.sent.filter((m) => m.type === "JOB_STATUS").length, 1,
    "the row was fetched more than once for one finished run");
  assert.equal(p.sent.filter((m) => m.type === "JOB_PROGRESS").length, 1);
  p.flushTimers();
  assert.equal(p.sent.filter((m) => m.type === "JOB_PROGRESS").length, 1,
    "the log kept being read after the run was over");
});

// The row keeps a tail of the log (`state.JOB_LOG_CHARS`), so a `total_chars`
// smaller than the cursor means the beginning was dropped under it and the
// offset no longer means what it did. Splicing the two texts together would be
// a log that never existed.
test("a log truncated under the cursor restarts from what is still there", () => {
  const { p, asked } = loggedRun([
    page("searching: a\n".repeat(20), 260, 260),
    page("read: https://a.example/1\n", 26, 26),
    page("read: https://a.example/2\n", 26, 52),
  ]);
  assert.deepEqual(asked, [0]);
  assert.deepEqual(segs(p), ["done", "now", "todo", "todo"]);
  p.flushTimers();
  assert.deepEqual(asked, [0, 260], "the second tick did not carry the cursor on");
  assert.deepEqual(segs(p), ["done", "done", "now", "todo"]);
  assert.match(p.shadow().querySelector(".lite-run-facts").textContent, /1 page read/,
    "the dropped part of the log was still being counted");
  p.flushTimers();
  assert.deepEqual(asked, [0, 260, 26],
    "the cursor still pointed into a log the engine had already dropped");
  assert.match(p.shadow().querySelector(".lite-run-facts").textContent, /2 pages read/,
    "the text after the truncation was not kept as one log");
});

test("an app without the log route is followed through the job row instead", () => {
  const { p, asked } = loggedRun([], "running", () => ({ ok: false, code: 404, error: "no such route" }));
  assert.deepEqual(asked, [0]);
  assert.equal(p.sent.filter((m) => m.type === "JOB_STATUS").length, 1,
    "the row was not asked when the log route refused");
  p.flushTimers();
  assert.deepEqual(asked, [0], "the missing route was asked for again on the next tick");
  assert.equal(p.sent.filter((m) => m.type === "JOB_STATUS").length, 2,
    "the run stopped being followed at all");
});

test("an engine that stops answering says so rather than going dark", () => {
  const p = loadPanel({ workerResponse: (m) => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "q", kind: "quick_look" } };
    return { ok: false, code: "APP_NOT_RUNNING", error: "Kriko is not running." };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example product" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example product");
  p.click(".lite-research-start");
  assert.match(p.shadow().querySelector(".lite-research-status").textContent,
    /Cannot check progress/);
  assert.deepEqual(segs(p), ["now", "todo", "todo", "todo"],
    "a stage was drawn from a log nobody could read");
});
