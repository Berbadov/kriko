const test = require("node:test");
const assert = require("node:assert/strict");
const { loadBackground, send } = require("./background_harness.js");

test("Firefox Promise APIs complete research and cache a result without chrome", async () => {
  const h = loadBackground({ firefox: true, routes: {
    "/api/extension/research-plane": { job_id: "firefox-job", kind: "research" },
  } });
  const answer = await send(h, { type: "RESEARCH_PRODUCT", payload: { q: "Product SKU-2026" } });
  assert.equal(answer.job.job_id, "firefox-job");
  assert.equal(h.state.requests[0].body.q, "Product SKU-2026");
  assert.equal(h.storageListeners.length, 1);
});

test("Firefox forwards a session result only to its matching page", async () => {
  const h = loadBackground({ firefox: true, tabResponses: { KRIKO_SESSION_UPDATE: {} } });
  const url = "https://shop.example/item/abc";
  h.sandbox.browser.tabs.query = async () => [{ id: 4, url }, { id: 5, url: "https://shop.example/other" }];
  h.storageListeners[0]({ ["kriko_result_" + url]: { newValue: { status: "ok", result: { claims: [] } } } }, "session");
  await new Promise(setImmediate);
  assert.equal(h.state.tabMessages.length, 1);
  assert.equal(h.state.tabMessages[0].tabId, 4);
  assert.equal(h.state.tabMessages[0].message.url, url);
  h.storageListeners[0]({ secret: { newValue: "unrelated" } }, "session");
  await new Promise(setImmediate);
  assert.equal(h.state.tabMessages.length, 1);
});

test("Firefox follow-up cache uses the sending tab URL and rejects extension-page callers", async () => {
  const h = loadBackground({ firefox: true });
  const listener = h.messageListeners[0];
  const ask = (message, sender) => new Promise(resolve => listener(message, sender, resolve));
  const sender = { tab: { url: "https://shop.example/current" } };
  const value = { quick: { risks: [{ title: "Risk" }] }, asks: [] };
  assert.equal((await ask({ type: "SAVE_FOLLOW_UPS", value, url: "https://other.example/" }, sender)).ok, true);
  const restored = await ask({ type: "RESTORE_FOLLOW_UPS" }, sender);
  assert.deepEqual(restored.value, value);
  assert.equal((await ask({ type: "RESTORE_FOLLOW_UPS" }, {})).ok, false);
  assert.equal(h.state.session["kriko_followups_https://other.example/"], undefined);
});
