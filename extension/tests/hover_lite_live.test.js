// What the panel says while it is working, and what else is working.
//
// The status line used to be a constant. It named two steps the engine does
// not perform, and it read as progress while carrying none — worse than a
// spinner, which at least admits it knows nothing. These pin the replacement:
// six stages the worker writes as it begins them, and an aside naming whatever
// else this installation is doing right now.
const test = require("node:test");
const assert = require("node:assert");

const { loadPanel } = require("./hover_lite_harness.js");

/* A panel with a run in flight — which is simply an open panel.
 *
 * Opening asks the worker for a cached answer and, finding none, starts one;
 * `analyzeResponse: {ok: true}` is the worker saying it has begun, with the
 * outcome still to arrive over storage. That is the state the status line
 * exists for, so it is the state every test here starts in. */
function analyzing(options = {}) {
  const p = loadPanel({ analyzeResponse: { ok: true }, ...options });
  p.openPanel();
  return p;
}

// ── the stage line ─────────────────────────────────────────────────────

test("before any stage lands, the panel says it is starting and nothing more", () => {
  const p = analyzing();
  assert.equal(p.statusText(), "Starting…");
});

test("each stage the worker writes becomes the status line", () => {
  const p = analyzing();

  p.deliverStage("adapters");
  assert.match(p.statusText(), /pack reads this site/);

  p.deliverStage("asking");
  assert.match(p.statusText(), /Asking Kriko/);
});

test("a stage's detail is shown beside it", () => {
  // The detail is the whole reason a stage beats a spinner: "reading this
  // page" is a promise, "reading this page, org.kriko.cars" is a fact.
  const p = analyzing();
  p.deliverStage("reading", "org.kriko.cars");

  assert.match(p.statusText(), /Reading this page/);
  assert.match(p.statusText(), /org\.kriko\.cars/);
});

test("a cached answer says so rather than pretending to work", () => {
  const p = analyzing();
  p.deliverStage("cached");

  assert.match(p.statusText(), /already stored/);
});

test("a stage nobody has words for renders its own name, not a blank", () => {
  // A worker that grows a stage before the panel learns the sentence must
  // degrade to something true, never to an empty line.
  const p = analyzing();
  p.deliverStage("regrounding");

  assert.match(p.statusText(), /regrounding/);
});

test("a fresh run does not open on the last run's final stage", () => {
  // "Done" is the worst possible opening line for work that has not started.
  const p = analyzing();
  p.deliverStage("done", "3");
  assert.match(p.statusText(), /Done/);

  // Pressed again, which is a fresh run.
  p.click(".lite-cta");
  assert.equal(p.statusText(), "Starting…");
});

// ── the live feed ──────────────────────────────────────────────────────

const RUNNING = {
  ok: true,
  feed: {
    items: [
      { op_id: 1, door: "mcp", name: "research_brief", state: "running" },
      { op_id: 2, door: "job", name: "research", state: "running",
        note: "extraction", progress: 0.5 },
    ],
  },
};

test("nothing running paints nothing", () => {
  const p = analyzing();
  assert.deepEqual(p.liveRows(), []);
});

test("what else is running is named, with who started it", () => {
  const p = analyzing({ operationsResponse: RUNNING });

  const rows = p.liveRows();
  assert.equal(rows.length, 2);
  assert.match(rows[0], /research_brief/);
  assert.match(rows[0], /your agent/);
  assert.match(rows[1], /the app/);
});

test("a row that carries a stage and a share shows both", () => {
  const p = analyzing({ operationsResponse: RUNNING });

  assert.match(p.liveRows()[1], /extraction/);
  assert.match(p.liveRows()[1], /50%/);
});

test("an operation that has ended is not still listed as running", () => {
  const p = analyzing({ operationsResponse: { ok: true, feed: { items: [
    { op_id: 1, door: "job", name: "research", state: "ok" },
  ] } } });

  assert.deepEqual(p.liveRows(), []);
});

test("an app that cannot be reached falls quiet rather than shouting", () => {
  // The analysis path above this already says the app is unreachable, loudly.
  // A second banner in an aside is noise, and "nothing is running" is the
  // honest reading of "cannot tell".
  const p = analyzing({ operationsResponse: { ok: false, error: "no app" } });

  assert.deepEqual(p.liveRows(), []);
  assert.equal(p.errorText(), null);
});

test("the feed keeps being asked while the panel is open", () => {
  const p = analyzing({ operationsResponse: RUNNING });
  const asked = () => p.sent.filter((one) => one.type === "OPERATIONS").length;
  const first = asked();

  p.flushTimers();

  assert.ok(asked() > first, "the poll stopped after one answer");
});
