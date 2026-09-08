// The two clocks, and the one place they are compared.
//
// The seam this closes: an unpacked extension is loaded once and stays
// loaded. The app can update, ship a newer extension to disk, and report both
// its own version and the staged one as current, while the browser is still
// running a copy from months ago. Nothing failed. The reader saw a panel that
// answered oddly or not at all, which from their side is indistinguishable
// from a broken app — and the app had no way to know, because nothing on the
// wire said which extension was talking.
//
// Two headers close it, both riding on requests the worker was going to make
// anyway: `X-Kriko-Extension` on the way out, `X-Kriko-Minimum-Extension` on
// the way back. No poll, no endpoint, no third clock.
const test = require("node:test");
const assert = require("node:assert");

const fs = require("node:fs");
const path = require("node:path");

const { loadBackground, send } = require("./background_harness.js");

const MANIFEST = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "manifest.json"), "utf8"));

const ADAPTERS = "/api/adapters";
const MINIMUM_HEADER = "X-Kriko-Minimum-Extension";
const VERSION_HEADER = "X-Kriko-Extension";

const adapters = [{ id: "a", site: "example.test", match: ["*example.test/*"], fields: {} }];

// The worker's fire-and-forget writes are not awaited by anything in the
// browser either; the tests drain the microtask queue rather than pretend
// there is a handle to hold.
const settle = async () => {
  for (let i = 0; i < 5; i += 1) await new Promise((r) => setImmediate(r));
};

const load = (extra = {}) => loadBackground({
  routes: { [ADAPTERS]: adapters },
  ...extra,
});

test("every request tells the app which extension is asking", async () => {
  const h = load();
  await send(h, { type: "KRIKO_SYNC_SITES" });
  const asked = h.state.requests.filter((r) => r.url.endsWith(ADAPTERS));
  assert.ok(asked.length > 0, "the worker made no request to compare");
  for (const request of asked) {
    assert.equal(request.headers[VERSION_HEADER], MANIFEST.version);
  }
});

test("the version it sends is read off the manifest, not written twice", async () => {
  // A version stated in two places drifts, and the drift is invisible: both
  // numbers look like versions. This is the assertion that the worker holds
  // no literal of its own.
  const source = fs.readFileSync(
    path.join(__dirname, "..", "background.js"), "utf8");
  assert.ok(
    source.includes("getManifest().version"),
    "the worker should read its version from the manifest");
  assert.ok(
    !new RegExp(`["']${MANIFEST.version.replace(/\./g, "\\.")}["']`).test(source),
    "the worker hardcodes its own version somewhere");
});

test("an extension older than the app's floor knows it is stale", async () => {
  const h = load({ responseHeaders: { [MINIMUM_HEADER]: "99.0.0" } });
  await send(h, { type: "KRIKO_SYNC_SITES" });
  await settle();
  const reply = await send(h, { type: "KRIKO_COMPAT" });
  assert.equal(reply.ok, true);
  assert.equal(reply.compat.stale, true);
  assert.equal(reply.compat.minimum, "99.0.0");
  assert.equal(reply.compat.running, MANIFEST.version);
});

test("an extension at or above the floor is not called stale", async () => {
  const h = load({ responseHeaders: { [MINIMUM_HEADER]: "0.0.1" } });
  await send(h, { type: "KRIKO_SYNC_SITES" });
  await settle();
  const reply = await send(h, { type: "KRIKO_COMPAT" });
  assert.equal(reply.compat.stale, false);
});

test("its own version exactly at the floor is current, not behind", async () => {
  const h = load({ responseHeaders: { [MINIMUM_HEADER]: MANIFEST.version } });
  await send(h, { type: "KRIKO_SYNC_SITES" });
  await settle();
  const reply = await send(h, { type: "KRIKO_COMPAT" });
  assert.equal(reply.compat.stale, false);
});

test("an app too old to state a floor is not turned into a complaint", async () => {
  // An older app answers this extension's requests perfectly well. Inventing
  // a warning would put a message in front of the one reader with nothing to
  // fix, and there is no way for them to tell it is spurious.
  const h = load();
  await send(h, { type: "KRIKO_SYNC_SITES" });
  await settle();
  const reply = await send(h, { type: "KRIKO_COMPAT" });
  assert.equal(reply.compat, null);
});

test("the verdict survives the worker being stopped", async () => {
  // The whole reason it is in storage. A reader opens the options page
  // minutes after the last lookup, which in MV3 is a fresh worker with no
  // memory of anything — so the second worker must answer from the first
  // worker's write.
  const first = load({ responseHeaders: { [MINIMUM_HEADER]: "99.0.0" } });
  await send(first, { type: "KRIKO_SYNC_SITES" });
  await settle();

  const second = loadBackground({ routes: { [ADAPTERS]: adapters } });
  // A new worker, handed the same chrome.storage.local — which is what
  // Chrome does. Copy it across rather than reusing the sandbox, so the test
  // cannot pass on a variable that happened to still be in scope.
  Object.assign(second.state.local, first.state.local);
  const reply = await send(second, { type: "KRIKO_COMPAT" });
  assert.equal(reply.compat.stale, true);
});

test("reading the verdict makes no request, so a closed app still answers", async () => {
  const h = load({ responseHeaders: { [MINIMUM_HEADER]: "99.0.0" } });
  await send(h, { type: "KRIKO_SYNC_SITES" });
  await settle();
  const before = h.state.requests.length;
  await send(h, { type: "KRIKO_COMPAT" });
  assert.equal(h.state.requests.length, before);
});

test("a floor with a suffix still compares as a version", async () => {
  // Nobody plans to ship "1.0.0-rc1" as a floor, and a comparison that threw
  // on one would take the panel down over a string nobody reads.
  const h = load({ responseHeaders: { [MINIMUM_HEADER]: "99.0.0-rc1" } });
  await send(h, { type: "KRIKO_SYNC_SITES" });
  await settle();
  const reply = await send(h, { type: "KRIKO_COMPAT" });
  assert.equal(reply.compat.stale, true);
});

test("a floor that is not a version at all is ignored, not obeyed", async () => {
  const h = load({ responseHeaders: { [MINIMUM_HEADER]: "unknown" } });
  await send(h, { type: "KRIKO_SYNC_SITES" });
  await settle();
  const reply = await send(h, { type: "KRIKO_COMPAT" });
  // Recorded — something answered — but not stale: an unparseable floor is
  // below every real version, which is the safe reading.
  assert.equal(reply.compat.stale, false);
});

test("the header names match the app's constants", async () => {
  // The other half is asserted in Python (test_extension_handshake.py). Both
  // sides assert it because either file can be edited alone.
  const source = fs.readFileSync(
    path.join(__dirname, "..", "background.js"), "utf8");
  assert.ok(source.includes(`"${VERSION_HEADER}"`));
  assert.ok(source.includes(`"${MINIMUM_HEADER}"`));
});

test("only the worker stamps the header, because a content script cannot", async () => {
  // A custom header on a content script's fetch turns every lookup into a
  // CORS preflight the app does not answer. The worker is exempt via
  // `host_permissions`; the content scripts are not, and must not fetch.
  for (const name of ["content.js", "hover_lite/hover_lite.js",
                      "hover_lite/risk_card.js", "hover_lite/icons.js"]) {
    const source = fs.readFileSync(path.join(__dirname, "..", name), "utf8");
    assert.ok(
      !/\bfetch\s*\(/.test(source),
      `${name} fetches directly; the worker must be the only caller`);
  }
  assert.ok(
    (MANIFEST.host_permissions || []).some((p) => p.startsWith("http://127.0.0.1")),
    "the worker's CORS exemption comes from this host permission");
});
