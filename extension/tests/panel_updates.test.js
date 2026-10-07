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
  p.type(".lite-followup-input", "What should I check first?");
  p.click(".lite-followup-send");
  const sent = p.sent.find(m => m.type === "LOOKUP_ASK");
  assert.equal(sent.payload.lookup_id, "answer-1");
  assert.equal(sent.payload.question, "What should I check first?");
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
          result: { risks: [claim("Quick risk")], deepen_job_id: "deep" } } }
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
  progress = 0.5;
  p.flushTimers();
  assert.ok(card.isConnected, "a progress poll replaced the quick-look card");
  assert.equal(card.dataset.open, "1");
  const status = p.shadow().querySelector(".lite-research-status").textContent;
  assert.match(status, /Reading sources · \d+s/);
  assert.doesNotMatch(status, /%/);
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
