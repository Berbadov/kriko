const test = require("node:test");
const assert = require("node:assert/strict");
const { loadBackground, send } = require("./background_harness.js");

test("follow-ups post only the question to the saved check's endpoint", async () => {
  const h = loadBackground({ routes: {
    "/api/lookup/a%2Fb/questions": { job_id: "j1", kind: "lookup_ask" },
  } });
  const reply = await send(h, { type: "LOOKUP_ASK", payload: {
    lookup_id: "a/b", question: "  What should I inspect?  ", claims: [{ title: "Page-supplied claim" }],
  } });
  assert.equal(reply.ok, true);
  assert.equal(reply.job_id, "j1");
  const request = h.state.requests.find(r => r.url.includes("/questions"));
  assert.deepEqual(request.body, { question: "What should I inspect?" });
});

test("saved follow-up jobs can be read through a restarted service worker", async () => {
  const h = loadBackground({ routes: {
    "/api/lookup/abc/questions": { items: [{ job_id: "j1", done: true, result: { answer: "Check the seal." } }] },
  } });
  const reply = await send(h, { type: "LOOKUP_QUESTIONS", payload: { lookup_id: "abc" } });
  assert.equal(reply.items[0].result.answer, "Check the seal.");
});

test("empty and oversized questions never reach the app", async () => {
  const h = loadBackground();
  for (const question of ["", "   ", "q".repeat(2001)]) {
    assert.equal((await send(h, { type: "LOOKUP_ASK", payload: { lookup_id: "abc", question } })).ok, false);
  }
  assert.equal(h.state.requests.filter(r => r.url.includes("/questions")).length, 0);
});

test("an unreachable app returns a useful error to the inline form", async () => {
  const h = loadBackground({ offline: true });
  const reply = await send(h, { type: "LOOKUP_ASK", payload: { lookup_id: "abc", question: "Why?" } });
  assert.equal(reply.ok, false);
  assert.match(reply.error, /Kriko|running|reach/i);
});
