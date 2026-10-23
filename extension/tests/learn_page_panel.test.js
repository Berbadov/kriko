// "Learn this page", and the agent picked in the panel. The reader's report was
// a quick look that searched the page's whole title and came back with chemistry
// lessons, and no way to tell Kriko "study this page and learn what to take from
// it". The card shows what an agent took, the agent can be chosen without
// leaving the page, and a pick is remembered.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { loadPanel } = require("./hover_lite_harness.js");

const CSS = fs.readFileSync(path.join(__dirname, "..", "hover_lite", "hover_lite.css"), "utf8");

/* The classes the stylesheet has a rule for.
 *
 * The panel lives in a shadow root with one `<link>`, so nothing else reaches
 * it: a class the markup carries and this sheet does not name renders as the
 * browser's own default. That is exactly what "Learn this page" was — a grey
 * system button in the middle of a styled card — and no test noticed, because
 * the checks that read the sheet asked what it *declares*, never whether the
 * markup's controls were in it. Comments are stripped first, so a class only
 * mentioned in prose does not count as covered.
 */
function declaredClasses() {
  const sheet = CSS.replace(/\/\*[\s\S]*?\*\//g, "");
  const names = new Set();
  for (const part of sheet.split("{")) {
    const selector = part.slice(part.lastIndexOf("}") + 1);
    for (const hit of selector.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) names.add(hit[1]);
  }
  return names;
}

// Every one of these is a control or a text block the learn card and the two
// agent rows draw: each must have a rule of its own, or the reader is looking
// at a piece of somebody else's browser.
const STYLED_BY_THE_PANEL = [
  "lite-learn", "lite-learn-row", "lite-learn-btn", "lite-learn-status", "lite-learn-grabs",
  "lite-agent-row", "lite-agent-select",
  "lite-quick-agent-row", "lite-quick-agent-select", "lite-quick-agent-note",
];

test("the panel's own stylesheet covers every control the learn card draws", () => {
  const declared = declaredClasses();
  const missing = STYLED_BY_THE_PANEL.filter((name) => !declared.has(name));
  assert.deepEqual(missing, [], `hover_lite.css has no rule for: ${missing.join(", ")}`);
});

// The page-learning picker is the one select that does not have a rule of its
// own: it borrows the shared `.lite-agent-select` face and adds a class for the
// wiring to find it by. Dropping the borrowed one leaves it as the browser's
// own control with nothing to notice.
test("the page-learning picker borrows the panel's select face", () => {
  const p = loadPanel({
    analyzeResponse: { ok: false, code: "NO_ADAPTER", hostKnown: false, learnable: true },
    workerResponse: worker(),
  });
  p.openPanel();
  p.click(".lite-cta");
  const select = p.shadow().querySelector(".lite-learn-agent-select");
  assert.ok(select, "no page-learning picker");
  assert.ok(select.classList.contains("lite-agent-select"),
    "the picker carries no class the stylesheet declares");
});

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

function openCard(workerResponse, localSettings = {}) {
  const p = loadPanel({
    analyzeResponse: { ok: false, code: "UNKNOWN_PRODUCT", productName: "Acme Roadster" },
    workerResponse,
    localSettings,
  });
  p.openPanel();
  p.click(".lite-cta");
  return p;
}

const status = (p) => p.shadow().querySelector(".lite-learn-status").textContent;

test("Quick Look has its own agent choice and remembers it separately", () => {
  const p = openCard(worker());
  const select = p.shadow().querySelector(".lite-quick-agent-select");
  assert.ok(select, "no agent picker");
  assert.deepEqual([...select.options].map((o) => o.value), ["", "local", "claude"]);
  assert.equal(select.value, "local", "the app's own pick is the starting point");

  select.value = "claude";
  select.dispatchEvent(new p.dom.window.Event("change", { bubbles: true }));
  assert.equal(p.local["kriko.quickLookAgent"], "claude");
  assert.equal(p.local["kriko.panelAgent"], undefined, "Quick Look does not change page learning");
  assert.match(p.shadow().querySelector(".lite-gap-cost").textContent, /coding agent/);
  const reopened = openCard(worker(), p.local);
  assert.equal(reopened.shadow().querySelector(".lite-quick-agent-select").value, "claude",
    "the Quick Look choice survives reopening the panel");
});

test("Quick Look keeps its selector visible when the roster has one agent", () => {
  const p = openCard((message) => message.type === "AGENTS"
    ? { ok: true, chosen: "local", agents: [AGENTS[0]] }
    : worker()(message));
  assert.ok(p.shadow().querySelector(".lite-quick-agent-select"));
});

test("Quick Look forwards the selected agent as the engine's one input", () => {
  const p = openCard(worker({ RESEARCH_PRODUCT: () => ({ ok: true, job: { job_id: "j1", kind: "quick_look" } }) }));
  p.click(".lite-research-start");
  assert.deepEqual({ ...p.sent.find((m) => m.type === "RESEARCH_PRODUCT").payload },
    { q: "Acme Roadster", allow_draft: true, url: p.dom.window.location.href, harness: "local" });

  const picked = openCard(worker({ RESEARCH_PRODUCT: () => ({ ok: true, job: { job_id: "j1", kind: "quick_look" } }) }));
  const select = picked.shadow().querySelector(".lite-quick-agent-select");
  select.value = "claude";
  select.dispatchEvent(new picked.dom.window.Event("change", { bubbles: true }));
  picked.click(".lite-research-start");
  assert.deepEqual({ ...picked.sent.find((m) => m.type === "RESEARCH_PRODUCT").payload },
    { q: "Acme Roadster", allow_draft: true, url: picked.dom.window.location.href, harness: "claude" });
});

// An older app has no agent roster to answer with, and the engine still runs a
// quick look on its own stored pick. Disabling the button there would take the
// reader's one way to answer a page off the screen because a *chooser* could
// not be filled in.
test("a roster the app never answered leaves the quick look runnable, unnamed", () => {
  const p = openCard((message) => {
    if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local", budget_usd: 0 } };
    if (message.type === "AGENTS") return { ok: false, error: "no such route" };
    if (message.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "j1", kind: "quick_look" } };
    return { ok: true };
  });
  assert.equal(p.shadow().querySelector(".lite-quick-agent-select"), null,
    "an empty selector claims a choice this panel cannot offer");
  assert.equal(p.shadow().querySelector(".lite-research-start").disabled, false);
  p.click(".lite-research-start");
  assert.deepEqual({ ...p.sent.find((m) => m.type === "RESEARCH_PRODUCT").payload },
    { q: "Acme Roadster", allow_draft: true, url: p.dom.window.location.href });
});

// And that unnamed run is only for a reader who never picked: a saved choice
// outlives a roster the app could not answer, because the engine is the one
// that can say whether the agent is still there.
test("a saved Quick Look agent still travels when the roster never arrived", () => {
  const p = loadPanel({
    analyzeResponse: { ok: false, code: "UNKNOWN_PRODUCT", productName: "Acme Roadster", learnable: true },
    localSettings: { "kriko.quickLookAgent": "claude" },
    workerResponse: (message) => {
      if (message.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local", budget_usd: 0 } };
      if (message.type === "AGENTS") return { ok: false, error: "no such route" };
      if (message.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "j1", kind: "quick_look" } };
      return { ok: true };
    },
  });
  p.openPanel();
  p.click(".lite-cta");
  p.click(".lite-research-start");
  assert.deepEqual({ ...p.sent.find((m) => m.type === "RESEARCH_PRODUCT").payload },
    { q: "Acme Roadster", allow_draft: true, url: p.dom.window.location.href, harness: "claude" });
});

test("no available Quick Look agent leaves research disabled", () => {
  const p = openCard((message) => message.type === "AGENTS"
    ? { ok: true, chosen: "", agents: [] }
    : worker()(message));
  assert.equal(p.shadow().querySelector(".lite-research-start").disabled, true);
  assert.match(p.shadow().querySelector(".lite-quick-agent-note").textContent, /No research agent is available/);
  assert.equal(p.sent.some((m) => m.type === "RESEARCH_PRODUCT"), false);
});

test("a stale saved Quick Look choice does not fall back to the app agent", () => {
  const p = loadPanel({
    analyzeResponse: { ok: false, code: "UNKNOWN_PRODUCT", productName: "Acme Roadster" },
    localSettings: { "kriko.quickLookAgent": "removed-agent" },
    workerResponse: worker({ RESEARCH_PRODUCT: () => ({ ok: true, job: { job_id: "j1", kind: "quick_look" } }) }),
  });
  p.openPanel();
  p.click(".lite-cta");
  const select = p.shadow().querySelector(".lite-quick-agent-select");
  assert.equal(select.value, "removed-agent");
  assert.match(p.shadow().querySelector(".lite-quick-agent-note").textContent, /saved agent is unavailable/i);
  assert.equal(p.shadow().querySelector(".lite-research-start").disabled, true);
  p.click(".lite-research-start");
  assert.equal(p.sent.some((m) => m.type === "RESEARCH_PRODUCT"), false);
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
  const p = loadPanel({ analyzeResponse: { ok: false, code: "NO_ADAPTER", learnable: true }, workerResponse: worker({
    LEARN_PAGE: () => ({ ok: true, lesson: { mode: "agent", job_id: "site-1", host: "shop.example", name: "Acme Roadster" } }),
    JOB_STATUS: () => {
      polls += 1;
      return polls < 2
        ? { ok: true, job: { state: "running", done: false, message: "Reading the page" } }
        : { ok: true, job: { state: "succeeded", done: true,
          result: { reading: { identity: { brand: "kingston", series: "a400" }, context: {} } } } };
    },
  }) });
  p.openPanel();
  p.click(".lite-cta");
  const select = p.shadow().querySelector(".lite-learn-agent-select");
  select.value = "claude";
  select.dispatchEvent(new p.dom.window.Event("change", { bubbles: true }));
  assert.equal(p.local["kriko.panelAgent"], "claude");
  assert.equal(p.local["kriko.quickLookAgent"], undefined);

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
