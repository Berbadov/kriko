// The extension learning a site it was not packaged with.
//
// The seam this closes: a pack ships `packs/<pack>/adapters/<site>.json`, the
// server routes that site's URLs the moment the file exists, and until B69 the
// extension only ran where `manifest.json` said so — a second, hand-edited
// list. Nothing failed when the two drifted. The pack installed, the coverage
// report counted the site, and the reader opened a listing to no panel, which
// from their side is identical to "nothing known about this car".
//
// Every test here is about the *mechanism*, never about sahibinden: the
// fixtures name invented hosts precisely so that passing cannot depend on
// which packs happen to be in the tree.
const test = require("node:test");
const assert = require("node:assert");

const fs = require("node:fs");
const path = require("node:path");

const { loadBackground, send } = require("./background_harness.js");

const MANIFEST = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "manifest.json"), "utf8"));

const ADAPTERS = "/api/adapters";

// A site the packaged manifest has never heard of, and its match pattern.
const NEW_SITE = "otoparca.example";
const NEW_ORIGIN = `https://*.${NEW_SITE}/*`;
const NEW_ID = `kriko-site-${NEW_SITE}`;

const adapter = (site, extra = {}) => ({
  id: site.split(".")[0], site, match: [`*${site}/*`], fields: {}, ...extra,
});

// A host the static manifest genuinely covers, read off the manifest rather
// than named, so trimming a static block moves this test with it.
function aStaticHost() {
  for (const block of MANIFEST.content_scripts || []) {
    for (const pattern of block.matches || []) {
      const host = pattern.split("://")[1].split("/")[0].replace(/^\*\./, "");
      if (host) return host;
    }
  }
  throw new Error("the manifest injects nowhere at all");
}

// An event listener registered with `void syncSites()` answers nobody — an
// alarm and a permission grant are fire-and-forget by nature, and there is no
// handle to await. So the test drains the microtask queue instead, which is
// the honest shape of the thing: nothing in the browser waits for this
// either.
const settle = async () => {
  for (let i = 0; i < 5; i += 1) await new Promise((r) => setImmediate(r));
};

const status = (h) => send(h, { type: "KRIKO_SITE_STATUS" });
const sync = (h) => send(h, { type: "KRIKO_SYNC_SITES" });

// ── detection ───────────────────────────────────────────────────────────

test("a site only the app knows about shows up as pending", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [adapter(NEW_SITE)] } });
  const reply = await sync(h);
  assert.equal(reply.ok, true);
  const row = reply.status.sites.find((s) => s.site === NEW_SITE);
  assert.ok(row, "the adapter's site was not detected at all");
  assert.equal(row.state, "pending");
  assert.equal(row.pattern, NEW_ORIGIN);
  // Pending means *not* injected: a site the reader has not allowed must not
  // have a registration sitting behind it.
  assert.deepEqual(h.state.registered, []);
});

test("a granted site is registered, with the panel's scripts in order",
  async () => {
    const h = loadBackground({
      routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
      grantedOrigins: [NEW_ORIGIN],
    });
    const reply = await sync(h);
    assert.equal(
      reply.status.sites.find((s) => s.site === NEW_SITE).state, "active");
    assert.equal(h.state.registered.length, 1);
    const script = h.state.registered[0];
    assert.equal(script.id, NEW_ID);
    assert.deepEqual(script.matches, [NEW_ORIGIN]);
    // `hover_lite.js` calls into `icons.js` and `risk_card.js`, so the order
    // is load-bearing, not cosmetic.
    assert.deepEqual(script.js, [
      "content.js",
      "hover_lite/icons.js",
      "hover_lite/risk_card.js",
      "hover_lite/hover_lite.js",
    ]);
    assert.equal(script.runAt, "document_idle");
    // Without this the registration dies with the worker, and the panel
    // works until Chrome next decides to stop it.
    assert.equal(script.persistAcrossSessions, true);
  });

test("a site the package already injects on is never registered again",
  async () => {
    const host = aStaticHost();
    const h = loadBackground({
      routes: { [ADAPTERS]: [adapter(host)] },
      grantedOrigins: [`https://*.${host}/*`],
    });
    const reply = await sync(h);
    // Not an error and not a warning — it is already covered. Registering it
    // would inject every content script twice on the one site that works.
    assert.deepEqual(h.state.registered, []);
    assert.equal(reply.status.sites.length, 0);
  });

test("a pack cannot turn its `site` into a permission for the whole web",
  async () => {
    // The one pack-supplied string in the worker with teeth. `*` would be a
    // host permission for every page the reader ever opens.
    const h = loadBackground({
      routes: {
        [ADAPTERS]: [
          adapter(NEW_SITE),
          { id: "greedy", site: "*", match: ["*"] },
          { id: "pathy", site: "example.com/../evil", match: ["*"] },
          { id: "schemey", site: "http://evil.example", match: ["*"] },
          { id: "porty", site: "evil.example:8080", match: ["*"] },
        ],
      },
      grantedOrigins: [NEW_ORIGIN],
    });
    const reply = await sync(h);
    const refused = reply.status.sites.filter((s) => s.state === "refused");
    assert.equal(refused.length, 4);
    for (const row of refused) assert.ok(!row.pattern);
    // And the legitimate one in the same list still went through: a bad
    // adapter must not be able to take the good ones down with it.
    assert.equal(h.state.registered.length, 1);
    assert.equal(h.state.registered[0].id, NEW_ID);
  });

// ── synchronisation and conflicts ───────────────────────────────────────

test("syncing twice changes nothing the second time", async () => {
  const h = loadBackground({
    routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
    grantedOrigins: [NEW_ORIGIN],
  });
  await sync(h);
  const first = JSON.stringify(h.state.registered);
  await sync(h);
  // Convergent, not incremental — which is what lets four unrelated triggers
  // all call it. A second registration under the same id would throw.
  assert.equal(JSON.stringify(h.state.registered), first);
  assert.equal(h.state.registered.length, 1);
});

test("a registration whose site is gone is dropped", async () => {
  const h = loadBackground({
    routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
    grantedOrigins: [NEW_ORIGIN],
  });
  await sync(h);
  assert.equal(h.state.registered.length, 1);
  // The pack was uninstalled: the app stops listing the site.
  h.sandbox.fetch = async (url, init) => {
    h.state.requests.push({ url, method: (init && init.method) || "GET" });
    return { ok: true, status: 200, async json() { return []; },
             async text() { return "[]"; } };
  };
  await sync(h);
  assert.deepEqual(h.state.registered, [],
    "an uninstalled pack left the extension injecting on its site");
});

test("revoking the permission takes the injection with it", async () => {
  const h = loadBackground({
    routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
    grantedOrigins: [NEW_ORIGIN],
  });
  await sync(h);
  assert.equal(h.state.registered.length, 1);
  h.state.granted.delete(NEW_ORIGIN);
  const reply = await sync(h);
  // The worst failure available here is an extension still reading a site the
  // reader took back.
  assert.deepEqual(h.state.registered, []);
  assert.equal(
    reply.status.sites.find((s) => s.site === NEW_SITE).state, "pending");
});

test("a stale registration Chrome is already holding is reconciled, not doubled",
  async () => {
    const h = loadBackground({
      routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
      grantedOrigins: [NEW_ORIGIN],
    });
    // A previous session's registration, surviving as `persistAcrossSessions`
    // asks it to — plus one for a site nobody wants any more.
    h.state.registered.push({ id: NEW_ID, matches: [NEW_ORIGIN], js: [] });
    h.state.registered.push({ id: "kriko-site-gone.example", matches: [], js: [] });
    await sync(h);
    assert.deepEqual(h.state.registered.map((s) => s.id), [NEW_ID]);
  });

test("registrations that are not ours are left alone", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [] } });
  h.state.registered.push({ id: "someone-elses-script", matches: [], js: [] });
  await sync(h);
  // The id prefix is the whole ownership claim, so it has to be honoured in
  // both directions.
  assert.deepEqual(h.state.registered.map((s) => s.id), ["someone-elses-script"]);
});

// ── failure recovery ────────────────────────────────────────────────────

test("the app being closed keeps the registrations and says why", async () => {
  const h = loadBackground({
    routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
    grantedOrigins: [NEW_ORIGIN],
  });
  await sync(h);
  assert.equal(h.state.registered.length, 1);

  h.sandbox.fetch = async () => { throw new TypeError("Failed to fetch"); };
  const reply = await sync(h);

  // A browser whose Kriko is closed is the ordinary state of the world, not
  // an error state. The reader keeps the panel on sites they already allowed.
  assert.equal(h.state.registered.length, 1);
  assert.equal(reply.status.code, "APP_NOT_RUNNING");
  // And the last known list survives, so the options page shows what it knows
  // rather than an empty one.
  assert.equal(reply.status.sites.length, 1);
});

test("the alarm is what retries after a failed sync", async () => {
  const h = loadBackground({
    routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
    grantedOrigins: [NEW_ORIGIN],
    offline: true,
  });
  // The first sync at install time fails: the app is almost never running
  // when an extension is installed.
  await sync(h);
  assert.deepEqual(h.state.registered, []);

  // Something has to try again without the reader doing anything.
  assert.ok(h.state.alarms["kriko-site-sync"],
    "nothing would ever retry the sync");
  assert.ok(h.state.alarms["kriko-site-sync"].periodInMinutes > 0);
  assert.ok(h.alarmListeners.length, "the alarm has no listener");

  h.sandbox.fetch = async (url) => {
    h.state.requests.push({ url, method: "GET" });
    return { ok: true, status: 200,
             async json() { return [adapter(NEW_SITE)]; },
             async text() { return "[]"; } };
  };
  await h.alarmListeners[0]({ name: "kriko-site-sync" });
  await settle();
  assert.equal(h.state.registered.length, 1);
});

test("an alarm that is not ours does nothing", async () => {
  const h = loadBackground({
    routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
    grantedOrigins: [NEW_ORIGIN],
  });
  await h.alarmListeners[0]({ name: "some-other-alarm" });
  await settle();
  assert.deepEqual(h.state.registered, []);
});

test("granting the permission registers the site without a second ask",
  async () => {
    const h = loadBackground({ routes: { [ADAPTERS]: [adapter(NEW_SITE)] } });
    await sync(h);
    assert.deepEqual(h.state.registered, []);

    // What the options page's button does. The grant itself must come from a
    // user gesture, which does not survive `sendMessage` — so the page asks
    // and the worker reacts, rather than the worker asking.
    await h.sandbox.chrome.permissions.request({ origins: [NEW_ORIGIN] });
    await settle();
    assert.equal(h.state.registered.length, 1);
    assert.equal(h.state.registered[0].id, NEW_ID);
  });

// ── what the options page is told ───────────────────────────────────────

test("the status is readable without touching the network", async () => {
  const h = loadBackground({
    routes: { [ADAPTERS]: [adapter(NEW_SITE)] },
    grantedOrigins: [NEW_ORIGIN],
  });
  await sync(h);
  const before = h.state.requests.length;
  const reply = await status(h);
  assert.equal(reply.ok, true);
  assert.equal(reply.status.sites[0].site, NEW_SITE);
  // Opening the options page must not require the app to be running.
  assert.equal(h.state.requests.length, before);
});

test("a status asked for before any sync is empty rather than an error",
  async () => {
    const h = loadBackground({ routes: { [ADAPTERS]: [] } });
    const reply = await status(h);
    assert.equal(reply.ok, true);
    assert.equal(reply.status, null);
  });

test("a manual re-check ignores the adapter cache", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [] } });
  await sync(h);
  const first = h.state.requests.filter((r) => r.url.endsWith(ADAPTERS)).length;
  await sync(h);
  const second = h.state.requests.filter((r) => r.url.endsWith(ADAPTERS)).length;
  // The five-minute cache is right for an analysis run and wrong for a reader
  // who just installed a pack and pressed the button.
  assert.equal(second, first + 1);
});

// ── the manifest still holds up its half ────────────────────────────────

test("the manifest can ask for a site at runtime", () => {
  assert.ok((MANIFEST.permissions || []).includes("alarms"),
    "without `alarms` a failed sync is never retried");
  assert.ok((MANIFEST.optional_host_permissions || []).length,
    "without optional host permissions there is nothing to grant");
});

test("the panel's stylesheet can reach a site added at runtime", () => {
  // A dynamically registered script gets the panel's JS from Chrome, but the
  // stylesheet is fetched by URL from inside the page — so a narrow
  // `web_accessible_resources` list would render the panel as an unstyled
  // pile of text over the listing, which looks like a broken app rather than
  // an absent one.
  const blocks = MANIFEST.web_accessible_resources || [];
  const css = blocks.find((b) => (b.resources || [])
    .some((r) => r.endsWith("hover_lite.css")));
  assert.ok(css, "the panel's stylesheet is exposed to nothing");
  assert.ok((css.matches || []).includes("https://*/*"));
  // Reachable from anywhere is only acceptable because the URL is rotated per
  // session: without this, any page could probe for the extension's id.
  assert.equal(css.use_dynamic_url, true);
});
