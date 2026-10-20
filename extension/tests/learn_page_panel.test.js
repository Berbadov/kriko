// "Learn this page", and the agent picked in the panel. The reader's report was
// a quick look that searched the page's whole title and came back with chemistry
// lessons, and no way to tell Kriko "study this page and learn what to take from
// it". The card shows what an agent took, the agent can be chosen without
// leaving the page, and a pick is remembered.
const test = require("node:test");
const assert = require("node:assert/strict");
const { loadPanel } = require("./hover_lite_harness.js");

const AGENTS = [
  { id: "local", label: "Local agent", kind: "local" },
  { id: "claude", label: "Claude Code", kind: "cli" },
];

function worker(extra = {}) {
  return (message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local", budget_usd: 0 } };
    if (message.type === "AGENTS") return { ok: true, chosen: "local", agents: AGENTS };
    if (extra[message.type]) return extra[message.type](message);
    return { ok: true };
  };
}

function openCard(workerResponse) {
  const p = loadPanel({
    analyzeResponse: { ok: false, code: "UNKNOWN_PRODUCT", productName: "Acme Roadster" },
    workerResponse,
  });
  p.openPanel();
  p.click(".lite-cta");
  return p;
}

const status = (p) => p.shadow().querySelector(".lite-learn-status").textContent;

test("the research card offers the agents the app says are ready, and remembers the pick", () => {
  const p = openCard(worker());
  const select = p.shadow().querySelector(".lite-agent-select");
  assert.ok(select, "no agent picker");
  assert.deepEqual([...select.options].map((o) => o.value), ["local", "claude"]);
  assert.equal(select.value, "local", "the app's own pick is the starting point");

  select.value = "claude";
  select.dispatchEvent(new p.dom.window.Event("change", { bubbles: true }));
  assert.equal(p.local["kriko.panelAgent"], "claude");
  assert.match(p.shadow().querySelector(".lite-gap-cost").textContent, /coding agent/);
});

test("with one agent there is nothing to pick, and no picker", () => {
  const p = openCard((message) => message.type === "AGENTS"
    ? { ok: true, chosen: "local", agents: [AGENTS[0]] }
    : worker()(message));
  assert.equal(p.shadow().querySelector(".lite-agent-select"), null);
});

test("a run uses the agent picked here, and the app's own when none was picked", () => {
  const p = openCard(worker({ RESEARCH_PRODUCT: () => ({ ok: true, job: { job_id: "j1", kind: "quick_look" } }) }));
  p.click(".lite-research-start");
  assert.equal(p.sent.find((m) => m.type === "RESEARCH_PRODUCT").payload.harness, undefined);

  const picked = openCard(worker({ RESEARCH_PRODUCT: () => ({ ok: true, job: { job_id: "j1", kind: "quick_look" } }) }));
  const select = picked.shadow().querySelector(".lite-agent-select");
  select.value = "claude";
  select.dispatchEvent(new picked.dom.window.Event("change", { bubbles: true }));
  picked.click(".lite-research-start");
  assert.equal(picked.sent.find((m) => m.type === "RESEARCH_PRODUCT").payload.harness, "claude");
});

test("pressing Learn this page shows what was taken, and swaps the title for the product's name", () => {
  const p = openCard(worker({
    LEARN_PAGE: () => ({
      ok: true,
      lesson: {
        mode: "local", learned: true, host: "shop.example", name: "Acme Roadster", reason: "",
        grabs: [{ as: "brand", value: "Acme", kind: "identity" }, { as: "model", value: "Roadster", kind: "identity" }],
      },
    }),
  }));
  assert.equal(p.shadow().querySelector(".lite-learn-btn").textContent, "Learn this page");
  assert.match(p.shadow().querySelector(".lite-gap-cost").textContent, /Free · on this computer/);

  p.click(".lite-learn-btn");

  assert.equal(p.sent.find((m) => m.type === "LEARN_PAGE").payload.agent, "local");
  assert.match(status(p), /Learned shop\.example\. It takes 2 things from this page/);
  const grabs = [...p.shadow().querySelectorAll(".lite-learn-grabs li")].map((li) => li.textContent);
  assert.deepEqual(grabs, ["brandAcme", "modelRoadster"]);
  assert.equal(p.shadow().querySelector(".lite-learn-btn").textContent, "Learn again");
  const asks = p.sent.filter((m) => m.type === "ANALYZE").length;
  assert.ok(asks >= 1, "a page that can be read now is looked at again");
});

test("a press that taught nothing says why, in the card, and shows no lesson", () => {
  const p = openCard(worker({
    LEARN_PAGE: () => ({ ok: true, lesson: { mode: "local", learned: false, reason: "This page prints no labelled facts to learn from.", grabs: [] } }),
  }));
  p.click(".lite-learn-btn");
  assert.equal(status(p), "This page prints no labelled facts to learn from.");
  assert.equal(p.shadow().querySelector(".lite-learn-grabs"), null);
  assert.equal(p.shadow().querySelector(".lite-learn-btn").textContent, "Learn this page");
});

test("Kriko not answering is said as such, not as a page that cannot be learned", () => {
  const p = openCard(worker({ LEARN_PAGE: () => ({ ok: false, error: "Kriko is not running." }) }));
  p.click(".lite-learn-btn");
  assert.equal(status(p), "Kriko is not running.");
});

test("another agent is a job the panel follows until it ends", () => {
  let polls = 0;
  const p = openCard(worker({
    LEARN_PAGE: () => ({ ok: true, lesson: { mode: "agent", job_id: "site-1", host: "shop.example", name: "Acme Roadster" } }),
    JOB_STATUS: () => {
      polls += 1;
      return polls < 2
        ? { ok: true, job: { state: "running", done: false, message: "Reading the page" } }
        : { ok: true, job: { state: "succeeded", done: true,
          result: { reading: { identity: { brand: "kingston", series: "a400" }, context: {} } } } };
    },
  }));
  const select = p.shadow().querySelector(".lite-agent-select");
  select.value = "claude";
  select.dispatchEvent(new p.dom.window.Event("change", { bubbles: true }));

  p.click(".lite-learn-btn");
  assert.equal(p.sent.find((m) => m.type === "LEARN_PAGE").payload.agent, "claude");
  assert.match(status(p), /Reading the page/);
  assert.equal(p.shadow().querySelector(".lite-learn-btn").disabled, true, "pressed twice would start two runs");

  p.flushTimers();
  assert.match(status(p), /^Learned shop\.example\. It takes 2 things/);
  assert.deepEqual([...p.shadow().querySelectorAll(".lite-learn-grabs li")].map((li) => li.textContent),
    ["brandkingston", "seriesa400"]);
  assert.equal(p.shadow().querySelector(".lite-learn-btn").disabled, false);
});

test("an agent job that failed says so", () => {
  const p = openCard(worker({
    LEARN_PAGE: () => ({ ok: true, lesson: { mode: "agent", job_id: "site-1", host: "shop.example" } }),
    JOB_STATUS: () => ({ ok: true, job: { state: "failed", done: true, error: "The agent could not read the page." } }),
  }));
  p.click(".lite-learn-btn");
  assert.equal(status(p), "The agent could not read the page.");
});
