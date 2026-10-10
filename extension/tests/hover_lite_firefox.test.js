const test = require("node:test");
const assert = require("node:assert/strict");
const { loadPanel } = require("./hover_lite_harness.js");

test("Firefox panel renders progress and a result without content-script session access", () => {
  const p = loadPanel({ firefox: true, analyzeResponse: { ok: true } });
  p.openPanel();
  p.deliverFirefoxUpdate({ stage: { name: "reading", detail: "Exact component codes", at: Date.now() } });
  assert.match(p.statusText(), /Exact component codes/);
  p.deliverFirefoxUpdate({ result: { ok: true, result: {
    claims: [], packs: [{ pack_id: "org.example.devices", version: "1.0.0" }],
  } } });
  assert.equal(p.footer().textContent, "org.example.devices · 1.0.0");
  p.deliverFirefoxUpdate({ url: "https://other.example/", result: { ok: false, error: "Other tab" } });
  assert.equal(p.footer().hidden, false);
  assert.notEqual(p.errorText(), "Other tab");
});
