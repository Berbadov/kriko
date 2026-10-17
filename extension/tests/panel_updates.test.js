const test = require("node:test");
const assert = require("node:assert/strict");
const { loadPanel } = require("./hover_lite_harness.js");

const claim = (id, extra = {}) => ({
  pack_id: "p", claim_id: id, title: id, body: `Details of ${id}`,
  severity: "high", domain: "components", ...extra,
});
const answer = (claims, lookup_id = "answer-1") => ({
  ok: true, listing: {},
  result: { lookup_id, claims, identity: {}, context: {}, coverage: "RISKS_FOUND" },
});
// A reply is typed out a frame at a time, even when it arrives whole; run
// frames until the slot says it is complete.
const typeOut = (p, selector = ".lite-followup-answer") => {
  for (let i = 0; i < 500 && p.shadow().querySelector(selector).dataset.phase !== "done"; i += 1) p.flushFrames();
};

test("live knowledge keeps existing cards, expansion, group state and focus", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  const card = p.shadow().querySelector(".lite-rc");
  const wrap = card.parentElement;
  const group = card.closest(".lite-domain-group");
  p.click(".lite-rc-toggle");
  p.click(".lite-domain-head");
  const button = card.querySelector(".lite-rc-toggle");
  button.focus();
  p.deliverEntry(answer([claim("new"), claim("old")]));
  assert.ok(card.isConnected, "an existing card was removed during a live update");
  assert.equal(card.parentElement, wrap);
  assert.equal(card.dataset.open, "1");
  assert.equal(group.dataset.open, "0");
  assert.equal(p.shadow().activeElement, button);
  button.click();
  assert.equal(card.dataset.open, "0", "a reordered card toggled the wrong claim");
  p.click(".lite-chip-expand");
  assert.ok([...p.shadow().querySelectorAll(".lite-rc")].every(c => c.dataset.open === "1"));
});

test("unchanged refreshes keep New cards and their controls in the DOM", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  p.deliverEntry(answer([claim("old"), claim("new")]));
  const card = p.shadow().querySelector('[data-fresh="1"]');
  p.deliverEntry(answer([claim("old"), claim("new")]));
  assert.ok(card.isConnected, "the New card blinked out on the next update");
  assert.equal(p.shadow().querySelectorAll(".lite-rc-new").length, 1);
});

test("changed and removed claims update without keeping stale text or expansion", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(answer([claim("old"), claim("removed")]));
  p.click(".lite-rc-toggle");
  p.deliverEntry(answer([claim("old", { body: "Updated evidence", domain: "other" })]));
  assert.equal(p.shadow().querySelectorAll(".lite-rc").length, 1);
  assert.match(p.claims().textContent, /Updated evidence/);
  assert.doesNotMatch(p.claims().textContent, /Details of old|removed/);
  assert.equal(p.shadow().querySelector(".lite-rc").dataset.open, "1");
  p.deliverEntry(answer([claim("old")], "answer-2"));
  assert.equal(p.shadow().querySelector(".lite-rc").dataset.open, "0");
  assert.equal(p.shadow().querySelector(".lite-rc-new"), null);
});

test("queue help explains the workflow without adding a product", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  const help = p.click(".lite-queue-help");
  assert.equal(help.getAttribute("aria-expanded"), "true");
  const text = p.shadow().querySelector(".lite-queue-guide");
  assert.equal(text.hidden, false);
  assert.match(text.textContent, /listing|page/i);
  assert.match(text.textContent, /Compare/);
  assert.match(text.textContent, /Start queue/);
  assert.equal(p.sent.filter(m => m.type === "QUEUE_ADD").length, 0);
  p.deliverEntry(answer([claim("old"), claim("new")]));
  assert.equal(p.shadow().querySelector(".lite-queue-guide").hidden, false);
  p.click(".lite-queue-help");
  assert.equal(p.shadow().querySelector(".lite-queue-guide").hidden, true);
});

test("a follow-up asks about the saved answer and renders the agent reply inline", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "LOOKUP_ASK") return { ok: true, job_id: "question-job" };
    if (m.type === "JOB_STATUS") return { ok: true, job: {
      job_id: "question-job", state: "succeeded", done: true,
      result: { answer: "Ask for the service record. <script>unsafe</script>",
        agent: { id: "local", label: "Local model", model: "small-model" } },
    } };
    return { ok: true, items: [], plane: { backend: "agent", budget_usd: 0 } };
  } });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  // The block is one line now: no heading, no lede, no visible label.
  assert.equal(p.shadow().querySelector(".lite-followup-note"), null);
  assert.equal(p.shadow().querySelector(".lite-followup label"), null);
  assert.match(p.shadow().querySelector(".lite-followup-input").placeholder, /Ask about this product/);
  assert.equal(p.shadow().querySelector(".lite-followup-send").textContent, "Ask");
  p.type(".lite-followup-input", "What should I check first?");
  p.click(".lite-followup-send");
  const sent = p.sent.find(m => m.type === "LOOKUP_ASK");
  assert.equal(sent.payload.lookup_id, "answer-1");
  assert.equal(sent.payload.question, "What should I check first?");
  typeOut(p);
  assert.match(p.shadow().querySelector(".lite-followup-answer").textContent, /Ask for the service record/);
  assert.equal(p.shadow().querySelector(".lite-followup-answer script"), null);
  assert.equal(p.shadow().querySelector(".lite-followup-user-label").textContent, "You · Question");
  assert.equal(p.shadow().querySelector(".lite-followup-agent-label").textContent, "Local model · Answer");
  assert.equal(p.shadow().querySelector(".lite-followup-model").textContent, "small-model");
  assert.equal(p.shadow().querySelector(".lite-followup-job-status").textContent, "Answered");
  p.type(".lite-followup-input", "And what else?");
  const input = p.shadow().querySelector(".lite-followup-input");
  input.focus();
  p.deliverEntry(answer([claim("old"), claim("new")]));
  assert.equal(p.shadow().querySelector(".lite-followup-input"), input);
  assert.equal(input.value, "And what else?");
  assert.equal(p.shadow().activeElement, input);
  assert.match(p.shadow().querySelector(".lite-followup-answer").textContent, /service record/);
});

test("a running follow-up identifies the agent and transitions to a labelled saved answer", () => {
  let done = false;
  const job = () => ({ job_id: "j", params: { question: "Why?" },
    state: done ? "succeeded" : "running", done,
    result: { agent: { label: "Agent <unsafe>", model: "model <unsafe>" },
      ...(done ? { answer: "The saved answer" } : {}) },
  });
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "LOOKUP_QUESTIONS") return { ok: true, items: [job()] };
    if (m.type === "JOB_STATUS") return { ok: true, job: job() };
    return { ok: true, plane: { backend: "agent" } };
  } });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  assert.equal(p.shadow().querySelector(".lite-followup-agent-label").textContent, "Agent <unsafe> · Answer");
  assert.equal(p.shadow().querySelector(".lite-followup-model").textContent, "model <unsafe>");
  assert.equal(p.shadow().querySelector(".lite-followup-job-status").textContent, "Answering…");
  assert.equal(p.shadow().querySelector(".lite-followup-history unsafe"), null);
  done = true;
  p.flushTimers();
  assert.equal(p.shadow().querySelector(".lite-followup-job-status").textContent, "Answered");
  typeOut(p);
  assert.match(p.shadow().querySelector(".lite-followup-answer").textContent, /The saved answer/);
});

test("a failed follow-up can be retried and never blanks the knowledge cards", () => {
  let fail = true;
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "LOOKUP_ASK") return fail
      ? { ok: false, error: "Open Kriko and try again." }
      : { ok: true, job_id: "j" };
    if (m.type === "JOB_STATUS") return { ok: true, job: { state: "failed", done: true, error: "No agent configured." } };
    return { ok: true, items: [], plane: { backend: "agent", budget_usd: 0 } };
  } });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  p.type(".lite-followup-input", "What next?");
  p.click(".lite-followup-send");
  assert.match(p.shadow().querySelector(".lite-followup-status").textContent, /Open Kriko/);
  assert.equal(p.shadow().querySelector(".lite-followup-send").disabled, false);
  fail = false;
  p.click(".lite-followup-send");
  assert.match(p.shadow().querySelector(".lite-followup-status").textContent, /No agent configured/);
  assert.equal(p.shadow().querySelectorAll(".lite-rc").length, 1);
});

test("an agent question without options accepts a typed answer in the panel", () => {
  const p = loadPanel({ workerResponse: () => ({ ok: true, plane: { backend: "agent" }, delivered: true,
    job: { job_id: "research", kind: "research", state: "running", attention: {
      questions: [{ id: "version", ask: "Which version is listed?", options: [] }],
    } },
  }) });
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result,
    subjects: [{ subject_id: "product", label: "Product", claims: 0 }],
  } });
  p.click(".lite-gap-btn");
  p.click(".lite-research-start");
  p.type(".lite-question-input", "The revised version");
  p.flushTimers();
  assert.equal(p.shadow().querySelector(".lite-question-input").value, "The revised version");
  p.shadow().querySelector(".lite-question-form").dispatchEvent(new p.dom.window.Event("submit", { bubbles: true, cancelable: true }));
  const told = p.sent.find(m => m.type === "JOB_SAY");
  assert.ok(told);
  assert.match(told.payload.text, /The revised version/);
});

test("deeper research progress keeps quick-look cards expanded without blinking", () => {
  let progress = 0.2;
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "quick", kind: "quick_look" } };
    if (m.type === "JOB_STATUS") return m.payload.job_id === "quick"
      ? { ok: true, job: { kind: "quick_look", state: "succeeded", done: true,
          result: { risks: [claim("Quick risk")] } } }
      : { ok: true, job: { state: "running", progress, message: "Reading sources" } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "An uncovered product" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "An uncovered product");
  p.click(".lite-research-start");
  const card = p.shadow().querySelector(".lite-quick .lite-rc");
  assert.ok(card);
  card.querySelector(".lite-rc-toggle").click();
  // #114: no deep run is followed on its own any more, so nothing re-renders
  // the quick-look cards at all — the expanded state simply stays.
  p.flushTimers();
  assert.ok(card.isConnected, "a progress poll replaced the quick-look card");
  assert.equal(card.dataset.open, "1");
  const status = p.shadow().querySelector(".lite-research-status").textContent;
  assert.match(status, /1 thing to know, from a quick look/);
  assert.doesNotMatch(status, /%/);
  assert.equal(p.sent.filter(m => m.type === "JOB_STATUS" && m.payload.job_id !== "quick").length, 0);
});

test("a research run that kept nothing says no data showed an issue", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "research", kind: "research",
      state: "succeeded", done: true,
      result: { documents: 4, outcome: "read 4 source(s), none of them said anything keepable",
        accepted: [], rejected: [], brief: "" } } };
    return { ok: true, delivered: true, job: { job_id: "research", kind: "research", state: "running" } };
  } });
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result,
    subjects: [{ subject_id: "product", label: "Product", claims: 0 }] } });
  p.click(".lite-gap-btn");
  p.click(".lite-research-start");
  p.flushTimers();
  const status = p.shadow().querySelector(".lite-research-status").textContent;
  assert.match(status, /No data found that shows an issue/);
  assert.match(status, /read 4 source\(s\), none of them said anything keepable/);
  assert.match(status, /not proof that there is no issue/);
  assert.doesNotMatch(status, /Open the research job for findings/);
});

test("a research run with a kept claim or a brief is not called empty", () => {
  for (const result of [
    { documents: 2, accepted: [{ title: "Kept" }], rejected: [], outcome: "1 claim(s) kept", brief: "" },
    { documents: 3, accepted: [], rejected: [], outcome: "read 3 source(s), none of them said anything keepable", brief: "A brief to open." },
  ]) {
    const p = loadPanel({ workerResponse: m => {
      if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
      if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "research", kind: "research",
        state: "succeeded", done: true, result } };
      return { ok: true, delivered: true, job: { job_id: "research", kind: "research", state: "running" } };
    } });
    p.openPanel();
    p.deliverEntry({ ...answer([]), result: { ...answer([]).result,
      subjects: [{ subject_id: "product", label: "Product", claims: 0 }] } });
    p.click(".lite-gap-btn");
    p.click(".lite-research-start");
    p.flushTimers();
    const status = p.shadow().querySelector(".lite-research-status").textContent;
    assert.match(status, /Open the research job for findings/);
    assert.doesNotMatch(status, /No data found/);
  }
});

test("a quick look is one saved job, and joins a pack only when asked", () => {
  // The reader: "Quick looks shouldn't be a pack but quick looks can be a
  // part of a pack. Quick looks are saved."
  const sent = [];
  const p = loadPanel({ workerResponse: m => {
    sent.push(m);
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "quick", kind: "quick_look" } };
    if (m.type === "QUICK_TO_PACK") return { ok: true, job: { job_id: "deep", kind: "pack_author" } };
    if (m.type === "JOB_STATUS") return m.payload.job_id === "quick"
      ? { ok: true, job: { kind: "quick_look", state: "succeeded", done: true,
          result: { risks: [claim("Quick risk")] } } }
      : { ok: true, job: { state: "running", progress: 0.1, message: "Filing it" } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "An uncovered product" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "An uncovered product");
  p.click(".lite-research-start");
  assert.match(p.shadow().querySelector(".lite-research-status").textContent, /Saved in Kriko/);
  assert.ok(!sent.some(m => m.type === "QUICK_TO_PACK"), "a pack run started by itself");
  p.click(".lite-research-pack");
  const asked = sent.find(m => m.type === "QUICK_TO_PACK");
  assert.equal(asked.payload.job_id, "quick");
  assert.match(p.shadow().querySelector(".lite-research-status").textContent, /Filing it/);
});

test("a zero-issue quick look retains listing facts, evidence and a web follow-up", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "oil-look", kind: "quick_look" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: {
      job_id: "oil-look", kind: "quick_look", state: "succeeded", done: true,
      result: { risks: [], specs: [],
        diagnostic: { code: "no_issues_found", message: "No supported issues found in the pages checked." },
        coverage: { pages_read: 2, pages_relevant: 2, pages_extracted: 2, status: "no_supported_findings" },
        listing: { url: "https://example.test/oil", facts: { Volume: "4 L", Grade: "5W-30" } },
        evidence_pages: [{ url: "https://example.test/datasheet", domain: "example.test", excerpt: "Oil product data" }],
      },
    } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example oil" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example oil");
  p.click(".lite-research-start");
  assert.match(p.shadow().querySelector(".lite-research-status").textContent, /No supported issues found/);
  assert.match(p.shadow().querySelector(".lite-quick-specs").textContent, /Volume: 4 L/);
  assert.equal(p.shadow().querySelector(".lite-quick-source-list a").href, "https://example.test/datasheet");
  const askInput = p.shadow().querySelector(".lite-follow-input");
  assert.ok(askInput);
  assert.equal(askInput.placeholder, "Ask about this product");
  assert.match(askInput.getAttribute("title"), /web/);
  assert.equal(p.shadow().querySelector(".lite-follow-ask").textContent, "Ask");
  assert.equal(p.shadow().querySelector(".lite-follow-lede"), null, "no visible lede remains");
});

// ── the no-issue card ───────────────────────────────────────────────────
//
// A quick look that keeps nothing used to leave a sentence and a hole in the
// research slot. The hole is the finding: it now gets a card with what was
// read, what that warrants, the pages themselves, and the quick look's own
// follow-up input — one answer pipeline, shown in the card instead of under it.

const EMPTY_QUICK = {
  job_id: "oil-look", kind: "quick_look", state: "succeeded", done: true,
  result: {
    risks: [], specs: [],
    diagnostic: { code: "no_issues_found", message: "No supported issues found in the pages checked." },
    coverage: { pages_read: 3, pages_relevant: 2, pages_extracted: 2,
      publishers_read: 2, sources_cited: 1, status: "no_supported_findings" },
    evidence_pages: [
      { url: "https://example.test/datasheet", domain: "example.test", excerpt: "Oil product data" },
    ],
  },
};

/* A quick look that keeps nothing, plus its saved asks, so the card's input is
   answered through the same pipe the panel already follows. */
const emptyQuickWorker = () => {
  const asks = [];
  return (m) => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "oil-look", kind: "quick_look" } };
    if (m.type === "JOB_STATUS" && m.payload.job_id === "oil-look") return { ok: true, job: EMPTY_QUICK };
    if (m.type === "QUICK_ASK") {
      asks.push({ job_id: "ask-1", q: m.payload.q, answer: "Check the product's own spec sheet.",
        done: true, sources: [] });
      return { ok: true, job: { job_id: "ask-1" } };
    }
    if (m.type === "QUICK_ASKS") return { ok: true, asks };
    if (m.type === "JOB_STATUS") {
      return { ok: true, job: { job_id: m.payload.job_id, state: "succeeded", done: true,
        result: { answer: "Check the product's own spec sheet.", sources: [] } } };
    }
    return { ok: true, items: [] };
  };
};

test("a quick look that kept nothing is a card with the pages and a working ask", () => {
  const p = loadPanel({ workerResponse: emptyQuickWorker() });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example oil" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example oil");
  p.click(".lite-research-start");

  const card = p.shadow().querySelector(".lite-noissue");
  assert.ok(card, "the empty quick look rendered a card");
  assert.equal(card.dataset.empty, "quick");
  assert.match(card.querySelector(".lite-noissue-title").textContent, /No sourced issues kept/);
  assert.match(card.querySelector(".lite-noissue-note").textContent,
    /not proof that there is no issue/);
  assert.match(card.querySelector(".lite-noissue-stats").textContent, /3\s*pages read/);
  assert.match(card.querySelector(".lite-noissue-stats").textContent, /1\s*cited/);
  assert.equal(card.querySelector(".lite-quick-source-list a").href,
    "https://example.test/datasheet");
  // The card carries the follow-up; the generic block under it is gone.
  assert.equal(p.shadow().querySelector(".lite-quick"), null);
  assert.ok(card.querySelector(".lite-follow-input"));

  p.type(".lite-noissue .lite-follow-input", "Does it sludge on short trips?");
  p.click(".lite-noissue .lite-follow-ask");
  const asked = p.sent.find((m) => m.type === "QUICK_ASK");
  assert.ok(asked, "the card's input used the quick look's own ask path");
  assert.equal(asked.payload.job_id, "oil-look");
  assert.equal(asked.payload.q, "Does it sludge on short trips?");
  typeOut(p, ".lite-noissue .lite-follow-answer");
  assert.match(p.shadow().querySelector(".lite-noissue .lite-follow-answer").textContent,
    /spec sheet/);
});

test("a deep run that kept nothing shows the same no-issue card", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "research", kind: "research",
      state: "succeeded", done: true,
      result: { documents: 4, outcome: "read 4 source(s), none of them said anything keepable",
        accepted: [], rejected: [], brief: "",
        coverage: { pages_read: 4, pages_relevant: 1, pages_extracted: 1,
          publishers_read: 1, sources_cited: 0 },
        evidence_pages: [{ url: "https://example.test/thread", domain: "example.test" }] } } };
    return { ok: true, delivered: true, job: { job_id: "research", kind: "research", state: "running" } };
  } });
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result,
    subjects: [{ subject_id: "product", label: "Product", claims: 0 }] } });
  p.click(".lite-gap-btn");
  p.click(".lite-research-start");
  p.flushTimers();

  const card = p.shadow().querySelector(".lite-noissue");
  assert.ok(card, "the empty deep run rendered the same card");
  assert.equal(card.dataset.empty, "deep");
  assert.match(card.textContent, /not proof that there is no issue/);
  assert.equal(card.querySelector(".lite-quick-source-list a").href,
    "https://example.test/thread");
  // The status sentence the panel already wrote is still there beside it.
  assert.match(p.shadow().querySelector(".lite-research-status").textContent,
    /not proof that there is no issue/);
});

// ── light and dark ──────────────────────────────────────────────────────

const hostAttr = (p) => p.dom.window.document.querySelector("kriko-panel-host").dataset.theme;

test("the header toggle sets the theme attribute and remembers it", () => {
  const p = loadPanel();
  p.openPanel();
  assert.equal(hostAttr(p), "dark");
  p.click(".lite-btn-theme");
  assert.equal(hostAttr(p), "light");
  assert.equal(p.local["kriko.theme"], "light");
  const button = p.shadow().querySelector(".lite-btn-theme");
  assert.equal(button.getAttribute("aria-pressed"), "true");
  assert.match(button.getAttribute("aria-label"), /dark/);
  p.click(".lite-btn-theme");
  assert.equal(hostAttr(p), "dark");
  assert.equal(p.local["kriko.theme"], "dark");
});

test("a stored choice opens the panel in it, and an unset one follows the system", () => {
  const stored = loadPanel();
  stored.local["kriko.theme"] = "light";
  stored.openPanel();
  assert.equal(hostAttr(stored), "light");

  const system = loadPanel();
  system.dom.window.matchMedia = (q) => ({ matches: /prefers-color-scheme: light/.test(q), media: q,
    addEventListener() {}, removeEventListener() {} });
  system.openPanel();
  assert.equal(hostAttr(system), "light");
});

test("reduced motion draws no ripple, and motion on draws one that removes itself", () => {
  const still = loadPanel();
  still.dom.window.matchMedia = (q) => ({ matches: /reduce/.test(q), media: q,
    addEventListener() {}, removeEventListener() {} });
  still.openPanel();
  const stillPanel = still.shadow().querySelector(".lite-panel");
  stillPanel.dispatchEvent(new still.dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 20, clientY: 20 }));
  assert.equal(still.shadow().querySelector(".lite-ripple"), null);

  const moving = loadPanel();
  moving.openPanel();
  const movingPanel = moving.shadow().querySelector(".lite-panel");
  movingPanel.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 600, right: 400, bottom: 600 });
  movingPanel.dispatchEvent(new moving.dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 30, clientY: 40 }));
  const dot = moving.shadow().querySelector(".lite-ripple");
  assert.ok(dot, "a press inside the panel drew a ripple");
  dot.dispatchEvent(new moving.dom.window.Event("animationend"));
  assert.equal(moving.shadow().querySelector(".lite-ripple"), null);
});

// ── the motion profile ──────────────────────────────────────────────────
//
// Calm / Standard / Vivid, the same three the desktop app offers, stored
// under `kriko.motion` and worn as a single `data-motion` attribute on the
// host. The stylesheet scales every distance and tempo from it, so the panel
// only has to put the attribute where the sheet can see it — and follow a
// switch made on the options page while it is open.

const hostMotion = (p) =>
  p.dom.window.document.querySelector("kriko-panel-host").dataset.motion;

test("the motion profile paints the host, follows a switch, and reduced motion still wins", () => {
  // A stored profile opens the panel in it, read from chrome.storage.local.
  const p = loadPanel();
  p.local["kriko.motion"] = "vivid";
  p.openPanel();
  assert.equal(hostMotion(p), "vivid");

  // The options page switching the profile reaches the open panel through
  // chrome.storage.onChanged, and the choice is the one durable value the two
  // surfaces share.
  p.setLocal("kriko.motion", "calm");
  assert.equal(hostMotion(p), "calm");
  assert.equal(p.local["kriko.motion"], "calm");

  // Reduced motion outranks the profile: even on Vivid, a reader who asked for
  // stillness gets no ripple.
  const still = loadPanel();
  still.dom.window.matchMedia = (q) => ({ matches: /reduce/.test(q), media: q,
    addEventListener() {}, removeEventListener() {} });
  still.local["kriko.motion"] = "vivid";
  still.openPanel();
  assert.equal(hostMotion(still), "vivid");
  still.shadow().querySelector(".lite-panel").dispatchEvent(
    new still.dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 20, clientY: 20 }));
  assert.equal(still.shadow().querySelector(".lite-ripple"), null);
});

// ── minimal by default ──────────────────────────────────────────────────

test("a recognised gap is a phrase, with the engine's sentence as the title", () => {
  const say = "This one is recognised, but the installed packs hold nothing "
    + "about it yet. That is a gap, not a clean bill of health.";
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result, verdict: "recognised",
    next_step: { action: "research", say } } });

  const box = p.shadow().querySelector(".lite-verdict");
  assert.equal(box.dataset.verdict, "recognised");
  assert.equal(box.querySelector(".lite-verdict-say").textContent,
    "Recognised. Nothing installed covers it yet.");
  assert.equal(box.title, say, "the engine's sentence survived as the tooltip");
  const button = box.querySelector(".lite-verdict-btn");
  assert.equal(button.textContent, "Research");
  assert.equal(button.title, say);
});

test("no claims means no count row and no expand/collapse controls", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result, verdict: "recognised",
    next_step: { action: "research", say: "gap" } } });
  assert.equal(p.shadow().querySelector(".lite-counts"), null);
  assert.equal(p.shadow().querySelector(".lite-claims-head"), null);

  p.deliverEntry(answer([claim("a")]));
  assert.ok(p.shadow().querySelector(".lite-counts"), "counts return with a claim");
  assert.ok(p.shadow().querySelector(".lite-claims-head"), "expand/collapse return too");
  assert.equal(p.shadow().querySelector(".lite-claims-label").textContent, "Risks · 1");
});
