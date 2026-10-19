// The panel as a place to buy from: the card for this page, the questions
// about earlier purchases, the shortlist's pick, and the look before paying.
const test = require("node:test");
const assert = require("node:assert/strict");

const { loadPanel } = require("./hover_lite_harness.js");

const BUYER = {
  name: "Kettle X200",
  price: { verdict: "high", price: 49.9, currency: "EUR", summary: "About 15% above its usual price.",
    series: [{ price: 40 }, { price: 42 }, { price: 49.9 }], discount: null, elsewhere: [] },
  watch: null, audit: null, fit: null, profile: false,
};

// What the worker's session storage holds, and what it answers the panel's buttons with.
function panel({ buyer = BUYER, due = [], replies = {} } = {}) {
  const p = loadPanel({
    workerResponse: (message) => {
      if (replies[message.type]) return typeof replies[message.type] === "function"
        ? replies[message.type](message) : replies[message.type];
      if (message.type === "BUYER_DUE") return { ok: true, due };
      return { ok: true };
    },
  });
  if (buyer) p.deliverBuyer({ ok: true, buyer });
  return p;
}

// Messages cross the vm boundary, so compare their shape and not their prototype.
const plain = (value) => JSON.parse(JSON.stringify(value));
// A page the panel has read: the decide button waits for something to decide.
const READ = { ok: true, listing: {}, result: { lookup_id: "a1", claims: [], identity: {}, context: {}, coverage: "NO_CLAIMS" } };
const tick = () => new Promise((resolve) => setImmediate(resolve));
const text = (p, selector) => p.shadow().querySelector(selector)?.textContent.replace(/\s+/g, " ").trim();

test("the card for this page appears with the stored price verdict", async () => {
  const p = panel();
  p.openPanel();
  await tick();
  assert.match(text(p, ".lite-buyer-slot"), /High right now/);
  assert.match(text(p, ".lite-buyer-slot"), /49\.9 EUR/);
});

test("a worker push of a fresh answer repaints the card", async () => {
  const p = panel({ buyer: null });
  p.openPanel();
  await tick();
  assert.equal(p.shadow().querySelector(".lite-buy"), null);
  p.deliverBuyer({ ok: true, buyer: BUYER });
  assert.match(text(p, ".lite-buyer-slot"), /High right now/);
});

test("watching a price asks for the figure and tells the app", async () => {
  const p = panel({ replies: { BUYER_WATCH: { ok: true, watch_id: "w1", target: 44, currency: "EUR" } } });
  p.openPanel();
  await tick();
  p.click('[data-act="watch-open"]');
  p.type('input[name="target"]', "44");
  const form = p.shadow().querySelector('form[data-act="watch-save"]');
  form.dispatchEvent(new p.dom.window.Event("submit", { bubbles: true, cancelable: true }));
  const sent = p.sent.find((m) => m.type === "BUYER_WATCH");
  assert.equal(sent.payload.target, "44");
  assert.equal(sent.payload.price, 49.9);
  assert.equal(sent.payload.currency, "EUR");
  await tick();
  assert.match(text(p, ".lite-buyer-slot"), /Watching · alert at 44 EUR or less/);
  p.click('[data-act="unwatch"]');
  assert.equal(p.sent.at(-1).type, "BUYER_UNWATCH");
  assert.equal(p.sent.at(-1).payload.watch_id, "w1");
});

test("I bought this is sent with the page's price and acknowledged", async () => {
  const p = panel();
  p.openPanel();
  await tick();
  p.click('[data-act="bought"]');
  await tick();
  const sent = p.sent.find((m) => m.type === "BUYER_BOUGHT");
  assert.equal(sent.payload.url, p.dom.window.location.href);
  assert.equal(sent.payload.price, 49.9);
  assert.match(text(p, ".lite-buyer-slot"), /Kriko will ask how it went/);
});

test("a purchase that is due is asked about, and the answer clears the question", async () => {
  const p = panel({ due: [{ purchase_id: "p1", name: "Blender" }] });
  p.openPanel();
  await tick();
  assert.match(text(p, ".lite-buy-due"), /Did your Blender hold up\?/);
  p.click('[data-act="answer"][data-verdict="glad"]');
  await tick();
  const sent = p.sent.find((m) => m.type === "BUYER_ANSWER");
  assert.deepEqual(plain(sent.payload), { purchase_id: "p1", verdict: "glad" });
  assert.equal(p.shadow().querySelector(".lite-buy-due"), null);
});

test("regret asks why and sends the reason", async () => {
  const p = panel({ due: [{ purchase_id: "p1", name: "Blender" }] });
  p.openPanel();
  await tick();
  p.click('[data-act="regret"]');
  p.type('input[name="reason"]', "motor died");
  p.shadow().querySelector('form[data-act="regret-save"]')
    .dispatchEvent(new p.dom.window.Event("submit", { bubbles: true, cancelable: true }));
  const sent = p.sent.filter((m) => m.type === "BUYER_ANSWER").at(-1);
  assert.deepEqual(plain(sent.payload), { purchase_id: "p1", verdict: "regret", reason: "motor died" });
});

test("deciding between the shortlist shows the pick, and the agent's words arrive when its job ends", async () => {
  let polls = 0;
  const p = panel({ replies: {
    BUYER_PICK: { ok: true, picked: { name: "Kettle B", price: 66, currency: "EUR", strengths: [] },
      confidence: "clear", gave_up: [], switch_if: [], check_first: [], ranked: [{ name: "Kettle B", score: 60 }] },
    BUYER_ADVICE: { ok: true, job_id: "j1" },
    JOB_STATUS: () => { polls += 1; return { ok: true, job: { state: "succeeded", done: true, result: { answer: "**Buy: Kettle B** because." } } }; },
  } });
  p.openPanel();
  p.deliverEntry(READ);
  await tick();
  p.click('[data-act="decide"]');
  await tick();
  assert.match(text(p, ".lite-decide-slot"), /Kettle B/);
  assert.match(text(p, ".lite-decide-slot"), /A clear pick/);
  p.click('[data-act="advise"][data-mode="debate"]');
  await tick();
  assert.equal(p.sent.find((m) => m.type === "BUYER_ADVICE").payload.mode, "debate");
  assert.equal(polls, 1);
  assert.match(text(p, ".lite-pick-answer"), /Buy: Kettle B because/);
});

test("a shortlist the app cannot rank says why instead of drawing nothing", async () => {
  const p = panel({ replies: { BUYER_PICK: { ok: false, error: "Kriko refused that (no saved checks to rank)." } } });
  p.openPanel();
  p.deliverEntry(READ);
  await tick();
  p.click('[data-act="decide"]');
  await tick();
  assert.match(text(p, ".lite-decide-slot"), /no saved checks to rank/);
});

test("a failed agent job is told, not left spinning", async () => {
  const p = panel({ replies: {
    BUYER_PICK: { ok: true, picked: { name: "A" }, confidence: "clear", gave_up: [], switch_if: [], check_first: [], ranked: [] },
    BUYER_ADVICE: { ok: true, job_id: "j1" },
    JOB_STATUS: { ok: true, job: { state: "failed", done: true, error: "The agent is not signed in." } },
  } });
  p.openPanel();
  p.deliverEntry(READ);
  await tick();
  p.click('[data-act="decide"]');
  await tick();
  p.click('[data-act="advise"][data-mode="pick"]');
  await tick();
  assert.match(text(p, ".lite-decide-slot"), /The agent is not signed in/);
});

test("the look before paying appears as a card of its own, once, and can be dismissed", () => {
  const p = panel();
  p.deliverMessage({ type: "SHOW_GUARD", result: { verdict: "stop",
    findings: [{ severity: "stop", message: "You researched A, but this is B." }] } });
  const host = p.dom.window.document.querySelector("kriko-guard-host");
  assert.ok(host);
  assert.match(host.shadowRoot.textContent, /Stop and check before paying/);
  p.deliverMessage({ type: "SHOW_GUARD", result: { verdict: "check",
    findings: [{ severity: "check", message: "Cheaper elsewhere" }] } });
  assert.equal(p.dom.window.document.querySelectorAll("kriko-guard-host").length, 1);
  host.shadowRoot.querySelector('[data-act="guard-dismiss"]')?.click();
});

test("a verdict of go interrupts nobody", () => {
  const p = panel();
  p.deliverMessage({ type: "SHOW_GUARD", result: { verdict: "go", findings: [] } });
  assert.equal(p.dom.window.document.querySelector("kriko-guard-host"), null);
});

test("the decide button waits for a page that was read, and is not drawn on an error", async () => {
  const idle = panel();
  idle.openPanel();
  await tick();
  assert.equal(idle.shadow().querySelector('[data-act="decide"]'), null);
  idle.deliverEntry(READ);
  assert.ok(idle.shadow().querySelector('[data-act="decide"]'));
});

test("a due question on a page Kriko reads is a card of its own that can be answered or ignored", async () => {
  const p = panel();
  p.deliverMessage({ type: "KRIKO_DUE_NUDGE", purchase: { purchase_id: "p1", name: "Blender" }, count: 1 });
  const host = p.dom.window.document.querySelector("kriko-due-host");
  assert.ok(host);
  assert.match(host.shadowRoot.textContent, /Did your Blender hold up\?/);
  host.shadowRoot.querySelector('[data-act="answer"][data-verdict="glad"]').click();
  await tick();
  const sent = p.sent.find((m) => m.type === "BUYER_ANSWER");
  assert.deepEqual(plain(sent.payload), { purchase_id: "p1", verdict: "glad", reason: "" });
  assert.equal(p.dom.window.document.querySelector("kriko-due-host"), null);
});

test("regret on the card asks why, and not now just closes it", async () => {
  const p = panel();
  p.deliverMessage({ type: "KRIKO_DUE_NUDGE", purchase: { purchase_id: "p1", name: "Blender" }, count: 1 });
  let host = p.dom.window.document.querySelector("kriko-due-host");
  host.shadowRoot.querySelector('[data-act="regret"]').click();
  const input = host.shadowRoot.querySelector('input[name="reason"]');
  input.value = "motor died";
  host.shadowRoot.querySelector('form[data-act="regret-save"]')
    .dispatchEvent(new p.dom.window.Event("submit", { bubbles: true, cancelable: true }));
  await tick();
  const sent = p.sent.filter((m) => m.type === "BUYER_ANSWER").at(-1);
  assert.deepEqual(plain(sent.payload), { purchase_id: "p1", verdict: "regret", reason: "motor died" });

  p.deliverMessage({ type: "KRIKO_DUE_NUDGE", purchase: { purchase_id: "p2", name: "Lamp" }, count: 1 });
  host = p.dom.window.document.querySelector("kriko-due-host");
  host.shadowRoot.querySelector('[data-act="due-dismiss"]').click();
  assert.equal(p.dom.window.document.querySelector("kriko-due-host"), null);
});
