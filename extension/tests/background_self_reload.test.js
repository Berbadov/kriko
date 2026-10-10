// B151: the browser ran a background.js two releases old while both ends said
// 0.3.0, so "Research this product" sent a listing's name and none of its
// facts. The app now answers with the digest of the files Chrome loads from;
// a worker whose own stamp differs reloads itself from them.
const test = require("node:test");
const assert = require("node:assert");

const { loadBackground, send } = require("./background_harness.js");

const OLD = "a".repeat(64);
const NEW = "b".repeat(64);
const ROUTES = { "/api/jobs/j1/cancel": { job_id: "j1", state: "cancelled" } };

async function oneRequest(h) {
  await send(h, { type: "CANCEL_JOB", payload: { job_id: "j1" } });
  await new Promise((resolve) => setImmediate(resolve));
}

test("a worker running older files than the folder reloads itself", async () => {
  const h = loadBackground({ routes: ROUTES, loadedDigest: OLD,
                             responseHeaders: { "x-kriko-staged-digest": NEW } });
  await oneRequest(h);
  assert.equal(h.state.selfReloads, 1);
  assert.equal(h.state.local.krikoSelfReload.digest, NEW);
});

test("the files it runs are the files on disk: nothing happens", async () => {
  const h = loadBackground({ routes: ROUTES, loadedDigest: NEW,
                             responseHeaders: { "x-kriko-staged-digest": NEW } });
  await oneRequest(h);
  assert.equal(h.state.selfReloads, 0);
});

test("an unstamped worker (a developer's checkout) never reloads", async () => {
  const h = loadBackground({ routes: ROUTES,
                             responseHeaders: { "x-kriko-staged-digest": NEW } });
  await oneRequest(h);
  assert.equal(h.state.selfReloads, 0);
});

test("a folder that cannot be loaded does not loop the reload", async () => {
  const h = loadBackground({ routes: ROUTES, loadedDigest: OLD,
                             responseHeaders: { "x-kriko-staged-digest": NEW } });
  await oneRequest(h);
  await oneRequest(h);
  assert.equal(h.state.selfReloads, 1);
});

test("after its own reload it refreshes the listing tabs left on the old script", async () => {
  const h = loadBackground({ routes: ROUTES });
  h.state.registered.push({ id: "kriko-anysite", matches: ["https://*/*"] });
  h.state.local.krikoSelfReload = { digest: NEW, at: Date.now(), pending: true };
  for (const fn of h.installedListeners) await fn({ reason: "update" });
  assert.deepEqual(h.state.tabsReloaded, [1]);
  assert.equal(h.state.local.krikoSelfReload.pending, false);
});

test("a reload nobody asked for refreshes no tabs", async () => {
  const h = loadBackground({ routes: ROUTES });
  for (const fn of h.installedListeners) await fn({ reason: "update" });
  assert.deepEqual(h.state.tabsReloaded, []);
});
