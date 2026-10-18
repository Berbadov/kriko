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
const PLANE = { ok: true, items: [], plane: { backend: "agent", budget_usd: 0 } };

// Frames run until the slot says its reply is whole.
const typeOut = (p, selector) => {
  for (let i = 0; i < 500 && p.shadow().querySelector(selector).dataset.phase !== "done"; i += 1) p.flushFrames();
};

// A listing follow-up, asked the way a reader asks it.
const askListing = (p, question) => {
  p.type(".lite-followup-input", question);
  p.click(".lite-followup-send");
};

test("a question the agent has not begun answering shows dots, not a waiting sentence", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "LOOKUP_ASK") return { ok: true, job_id: "q1" };
    if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "q1", state: "running", done: false, result: {} } };
    return PLANE;
  } });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  askListing(p, "Is the timing belt due?");

  const slot = p.shadow().querySelector(".lite-followup-answer");
  assert.equal(slot.dataset.phase, "waiting");
  const dots = slot.querySelector(".lite-answer-loading");
  assert.ok(dots, "the reply slot shows the loading dots");
  assert.equal(dots.getAttribute("role"), "status");
  assert.equal(dots.querySelectorAll("i").length, 3);
  assert.doesNotMatch(p.shadow().textContent, /Waiting for the answer/);
});

test("a running reply grows as the agent writes it, one frame at a time", () => {
  let text = "";
  let done = false;
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "LOOKUP_ASK") return { ok: true, job_id: "q2" };
    if (m.type === "JOB_STATUS") return { ok: true, job: {
      job_id: "q2", state: done ? "succeeded" : "running", done,
      result: { answer: text, agent: { label: "Local model" } },
    } };
    return PLANE;
  } });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  text = "The timing belt is due at";
  askListing(p, "When is it due?");

  const slot = () => p.shadow().querySelector(".lite-followup-answer");
  p.flushFrames();
  const first = slot().textContent;
  assert.equal(slot().dataset.phase, "streaming");
  assert.ok(first.length > 0, "the first words appear on the first frame");
  assert.ok(text.startsWith(first) && first.length < text.length, "the reply is shown as a prefix of what is written");

  text = "The timing belt is due at 120000 km or every five years.";
  p.flushTimers();
  assert.equal(slot().dataset.phase, "streaming", "a longer partial reply keeps typing");
  for (let i = 0; i < 200 && slot().textContent !== text; i += 1) p.flushFrames();
  assert.equal(slot().textContent, text, "the typing catches up with what the agent has written");

  done = true;
  p.flushTimers();
  assert.equal(slot().dataset.phase, "done", "the finished reply is shown whole, with no caret");
  assert.equal(slot().textContent, text);
  assert.equal(p.shadow().querySelector(".lite-followup-job-status").textContent, "Answered");
});

test("a reply that arrives whole is still typed out, and its sources are links", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "LOOKUP_ASK") return { ok: true, job_id: "q3" };
    if (m.type === "JOB_STATUS") return { ok: true, job: {
      job_id: "q3", state: "succeeded", done: true,
      result: {
        answer: "A recall covered the belt in 2019.", agent: { label: "Local model" },
        sources: [
          { url: "https://recalls.example.test/golf", domain: "recalls.example.test" },
          { url: "javascript:alert(1)", domain: "not-a-page" },
        ],
      },
    } };
    return PLANE;
  } });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  askListing(p, "Any recall?");

  const slot = p.shadow().querySelector(".lite-followup-answer");
  assert.equal(slot.dataset.phase, "waiting", "a whole reply still starts with nothing on screen");
  typeOut(p, ".lite-followup-answer");
  assert.match(slot.textContent, /A recall covered the belt in 2019\./);

  const links = slot.querySelectorAll(".lite-answer-sources a");
  assert.equal(links.length, 1, "only web addresses become links");
  assert.equal(links[0].getAttribute("href"), "https://recalls.example.test/golf");
  assert.equal(links[0].textContent, "recalls.example.test");
  assert.equal(links[0].getAttribute("rel"), "noopener noreferrer");
});

test("with reduced motion a running reply appears at once, with no typing", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "LOOKUP_ASK") return { ok: true, job_id: "q4" };
    if (m.type === "JOB_STATUS") return { ok: true, job: {
      job_id: "q4", state: "running", done: false,
      result: { answer: "The timing belt is due soon." },
    } };
    return PLANE;
  } });
  p.dom.window.matchMedia = () => ({ matches: true });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  askListing(p, "When?");

  const slot = p.shadow().querySelector(".lite-followup-answer");
  assert.equal(slot.textContent, "The timing belt is due soon.");
  assert.equal(slot.dataset.phase, "streaming");
});

test("a quick look's question shows dots, then types its answer as it is written", () => {
  const qa = { text: "", done: false, question: "" };
  const asks = () => (qa.question
    ? [{ job_id: "qa1", q: qa.question, answer: qa.text, done: qa.done, sources: [] }]
    : []);
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "SAVED_QUICK_LOOK") return { ok: true, job: {
      job_id: "ql1", kind: "quick_look", state: "succeeded", done: true,
      params: { product: "VW Golf 1.6 TDI" },
      result: { product: "VW Golf 1.6 TDI", risks: [claim("belt", { title: "Timing belt" })], specs: [] },
    } };
    if (m.type === "QUICK_ASKS") return { ok: true, asks: asks() };
    if (m.type === "QUICK_ASK") {
      qa.question = m.payload.q;
      return { ok: true, job: { job_id: "qa1" } };
    }
    if (m.type === "JOB_STATUS") return { ok: true, job: {
      job_id: "qa1", state: qa.done ? "succeeded" : "running", done: qa.done,
      result: { answer: qa.text },
    } };
    return PLANE;
  } });
  p.openPanel();
  const full = "The timing belt is due at 120000 km or every five years.";
  qa.text = full.slice(0, 20);
  p.type(".lite-follow-input", "When is the belt due?");
  p.click(".lite-follow-ask");

  const reply = () => p.shadow().querySelector(".lite-follow-answer");
  assert.equal(reply().dataset.phase, "waiting", "the new question shows dots until its first words");
  assert.equal(reply().getAttribute("data-answer"), "qa1", "the reply is tied to the engine's job");
  p.flushFrames();
  assert.equal(reply().dataset.phase, "streaming");
  assert.ok(full.startsWith(reply().textContent) && reply().textContent.length < full.length);

  qa.text = full;
  qa.done = true;
  p.flushTimers();
  typeOut(p, ".lite-follow-answer");
  assert.match(reply().textContent, /120000 km/);
  assert.doesNotMatch(p.shadow().textContent, /Answering…/);
});

/* The cap on a paid follow-up is the engine's number, not the panel's. A
 * literal in the tooltip is a claim about the engine that nothing keeps true:
 * the panel said "$0.20 per question" for as long as it took the engine's own
 * budget to change, and a stale number on the one prompt whose job is to say
 * the cost before the click is worse than no number. */
test("the paid cap in the follow-up tooltips is the engine's own number", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") {
      return { ok: true, plane: { backend: "api", budget_usd: 0.35 } };
    }
    return PLANE;
  } });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));

  const input = p.shadow().querySelector(".lite-followup-input");
  const send = p.shadow().querySelector(".lite-followup-send");
  assert.match(input.getAttribute("title"), /\$0\.35 per question/);
  assert.match(send.getAttribute("title"), /\$0\.35 per question/);
  assert.doesNotMatch(input.getAttribute("title"), /\$0\.20/);
});

test("a follow-up that costs nothing per question claims no cap", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") {
      return { ok: true, plane: { backend: "local", budget_usd: 0 } };
    }
    return PLANE;
  } });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));

  const input = p.shadow().querySelector(".lite-followup-input");
  const send = p.shadow().querySelector(".lite-followup-send");
  assert.doesNotMatch(input.getAttribute("title"), /capped at/);
  assert.equal(send.getAttribute("title") ?? "", "");
});
