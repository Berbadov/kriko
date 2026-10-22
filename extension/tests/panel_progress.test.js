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
