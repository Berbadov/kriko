// Loads the hub page + hub.js into jsdom with a stubbed API, so the Models
// tab's picker can be tested without a browser or a running server.
//
// The picker is the hub's main control surface — make → model → generation →
// task → run — and it had no tests at all: every check was "does the page
// still render", which a state-machine bug walks straight past.
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM, VirtualConsole } = require("jsdom");

const STATIC = path.join(__dirname, "..", "static");

const DEMAND = {
  makes: [
    {
      make: "Volkswagen", slug: "volkswagen", hits: 18,
      models: [
        { model: "VW CC 1.4 TSI", slug: "vw_cc_1_4_tsi", hits: 12,
          reason: "not_onboarded" },
        { model: "Golf", slug: "golf", hits: 6, reason: "catalog_gap" },
      ],
    },
    { make: "Renault", slug: "renault", hits: 10,
      models: [{ model: "Clio", slug: "clio", hits: 10, reason: "catalog_gap" }] },
  ],
};

const HARNESSES = {
  harnesses: [
    { name: "claude", available: true, models: ["opus", "sonnet"], paid_models: [] },
    { name: "opencode", available: true, models: ["opencode/free-1"],
      paid_models: ["openrouter/pricey-1"] },
  ],
};

// Renault Clio has a researched lineup; the VW display-slug does not.
const GENERATIONS = {
  "renault/clio": {
    make: "renault", model: "clio", researched: true,
    generations: [
      { generation: 4, name: "IV", year_from: 2012, year_to: 2019, source_urls: ["x"] },
      { generation: 5, name: "V", year_from: 2019, year_to: null, source_urls: ["x"] },
    ],
  },
};

const STATE = {
  counts: { documents: 3, evidence: 4, clusters: 2, verdicts: 2 },
  spend: { rows: [], total_usd: 0, verdicts_import: 2, verdicts_llm: 0 },
  pending: { extract_chunks: 0, verdict_pending: 0, import_ready: 0, llm: 0,
             extract_usd: 0, verdict_usd: 0 },
  parts: [], documents: [], runs: [], last_remediation: null,
  catalog: { parts: 1, variants: 1, fitment: 1, claims: 5 },
};

function jsonResponse(body) {
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

/** Load the hub with a stubbed API. `opts.generations` overrides lineups. */
function loadHub(opts = {}) {
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8")
    .replace('<script src="/static/hub.js"></script>', "");
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(String(e.message)));

  const dom = new JSDOM(html, {
    url: "http://127.0.0.1:8787/#models",
    runScripts: "dangerously",
    pretendToBeVisual: true,
    virtualConsole,
  });
  const { window } = dom;
  const calls = [];
  const generations = { ...GENERATIONS, ...(opts.generations || {}) };

  window.fetch = (url, init) => {
    const u = String(url);
    calls.push({ url: u, init });
    if (u.startsWith("/api/state")) return jsonResponse(STATE);
    if (u.startsWith("/api/log"))
      return jsonResponse({ cmd: "", buf: "", running: false, exit: null });
    if (u.startsWith("/api/models")) return jsonResponse({ models: [] });
    if (u.startsWith("/api/activity")) return jsonResponse({ events: [] });
    if (u.startsWith("/api/demand")) return jsonResponse(opts.demand || DEMAND);
    if (u.startsWith("/api/harnesses")) return jsonResponse(opts.harnesses || HARNESSES);
    if (u.startsWith("/api/runs") || u.startsWith("/api/agent-runs"))
      return jsonResponse({ runs: [] });
    if (u.startsWith("/api/generations/")) {
      const key = u.replace("/api/generations/", "");
      return jsonResponse(generations[key]
        || { make: key.split("/")[0], model: key.split("/")[1],
             researched: false, generations: [] });
    }
    if (u.startsWith("/api/agent-preview")) {
      // Mirrors web.py's _agent_command: an onboard target carries the
      // generation suffix (`clio_5`), a generations run does not.
      const body = JSON.parse(init.body);
      const target = body.task === "onboard" && body.generation
        ? `${body.model}_${body.generation}` : body.model;
      return jsonResponse({
        argv: ["/bin/claude", "-p", body.task, body.make, target],
        display: `/bin/claude -p ${body.task} ${body.make} ${target}`,
      });
    }
    return jsonResponse({});
  };

  const script = window.document.createElement("script");
  script.textContent = fs.readFileSync(path.join(STATIC, "hub.js"), "utf8");
  window.document.body.appendChild(script);

  const $ = (sel) => window.document.querySelector(sel);
  const all = (sel) => [...window.document.querySelectorAll(sel)];
  const click = (el) => el.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const tick = (ms = 60) => new Promise((r) => setTimeout(r, ms));

  return {
    window, dom, calls, errors, $, all, click, tick,
    chips: (sel) => all(`${sel} .chip`),
    clickChip: async (sel, i = 0) => { click(all(`${sel} .chip`)[i]); await tick(); },
    close: () => dom.window.close(),
  };
}

module.exports = { loadHub, DEMAND, HARNESSES, GENERATIONS };
