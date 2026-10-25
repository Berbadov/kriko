// The worker's side of Compare in the panel: the shortlist with what is stored
// about each product on it, and taking one off.
const test = require("node:test");
const assert = require("node:assert");

const { loadBackground, send } = require("./background_harness.js");

const QUEUE = { max: 8, items: [
  { queue_id: "q1", url: "https://a.example/kettle", name: "Kettle A", lookup_id: "l1", state: "done" },
  { queue_id: "q2", url: "https://b.example/kettle", name: "Kettle B", lookup_id: "", state: "waiting" },
  { queue_id: "q3", url: "https://c.example/kettle", name: "Kettle C", lookup_id: "gone", state: "done" },
] };

test("the shortlist carries the severity of every risk in each stored check", async () => {
  const h = loadBackground({
    routes: {
      "/api/queue": QUEUE,
      "/api/lookup/l1": { response: { claims: [
        { severity: "high", title: "Lid hinge cracks" }, { severity: "low", title: "Scale builds up" },
      ] } },
    },
  });
  const reply = await send(h, { type: "COMPARE_LIST", payload: {} });
  assert.equal(reply.ok, true);
  assert.equal(reply.max, 8);
  assert.deepEqual(reply.items.map((one) => one.queue_id), ["q1", "q2", "q3"], "in the app's order");
  assert.deepEqual(Array.from(reply.items[0].severities), ["high", "low"]);
  assert.equal(reply.items[1].severities, null, "a product never checked has no severities");
  assert.equal(reply.items[2].severities, null, "a check the app no longer has is unchecked, not an error");
  assert.deepEqual(h.state.requests.filter((r) => r.url.includes("/api/lookup/")).map((r) => r.url.split("/").pop()).sort(),
    ["gone", "l1"], "no lookup is asked for a row that has none");
  assert.ok(h.state.requests.every((r) => r.method === "GET"), "listing the shortlist changes nothing");
});

test("a stored check that cannot be read leaves that row unchecked, not the list failed", async () => {
  const h = loadBackground({
    routes: { "/api/queue": QUEUE },
  });
  const reply = await send(h, { type: "COMPARE_LIST", payload: {} });
  assert.equal(reply.ok, true);
  assert.equal(reply.items[0].severities, null);
  assert.equal(reply.items.length, 3);
});

test("with no app the shortlist is an error the panel can tell from an empty one", async () => {
  const h = loadBackground({ offline: true });
  const reply = await send(h, { type: "COMPARE_LIST", payload: {} });
  assert.equal(reply.ok, false);
  assert.ok(reply.error);
});

test("a product is taken off the shortlist by its id, and a refusal is not a removal", async () => {
  const h = loadBackground({ routes: { "/api/queue/q1": { removed: "q1" } } });
  const done = await send(h, { type: "COMPARE_REMOVE", payload: { queue_id: "q1" } });
  assert.equal(done.ok, true);
  assert.equal(done.removed, "q1");
  const call = h.state.requests.at(-1);
  assert.equal(call.method, "DELETE");
  assert.ok(call.url.endsWith("/api/queue/q1"));

  const refused = loadBackground({
    routes: { "/api/queue/q9": {} }, statuses: { "/api/queue/q9": 404 } });
  const missing = await send(refused, { type: "COMPARE_REMOVE", payload: { queue_id: "q9" } });
  assert.equal(missing.ok, false);
  assert.equal(missing.status, 404);

  const none = await send(h, { type: "COMPARE_REMOVE", payload: {} });
  assert.equal(none.ok, false, "nothing to remove is refused before it reaches the app");
});
