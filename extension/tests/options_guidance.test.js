// The options page opens by itself, once, at the step that is missing (#260).
//
// The reader's words: "automatically open kriko option in settings". Their
// limits, from the issue: a fresh install opens it once at the missing step,
// it never reopens once the step is done, a reader who closes it is not
// nagged in the same session, and it is not opened on every browser start.
// Each of those is a test below, against invented hosts, so passing cannot
// depend on which packs are in the tree.
const test = require("node:test");
const assert = require("node:assert");

const { loadBackground, send } = require("./background_harness.js");

const ADAPTERS = "/api/adapters";
const SITE = "otoparca.example";
const ORIGIN = `https://*.${SITE}/*`;
const OTHER = "yedekparca.example";
const OTHER_ORIGIN = `https://*.${OTHER}/*`;

const adapter = (site) => ({ id: site.split(".")[0], site, match: [`*${site}/*`], fields: {} });

const settle = async () => {
  for (let i = 0; i < 8; i += 1) await new Promise((r) => setImmediate(r));
};

const install = async (h, reason = "install") => {
  for (const fn of h.installedListeners) await fn({ reason });
  await settle();
};
const startup = async (h) => { for (const fn of h.startupListeners) await fn(); await settle(); };
const alarm = async (h) => {
  for (const fn of h.alarmListeners) await fn({ name: "kriko-site-sync" });
  await settle();
};
// A new browser session forgets session storage and keeps local storage.
const newSession = (h) => { for (const k of Object.keys(h.state.session)) delete h.state.session[k]; };
const focus = (h) => h.state.local.krikoOptionsFocus;

test("a fresh install opens the options at the site that waits for permission", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [adapter(SITE)] } });
  await install(h);
  assert.equal(h.state.optionsOpened, 1);
  assert.equal(focus(h), "sites", "the page is told which step to show");
});

test("a fresh install with nothing waiting opens nothing", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [] } });
  await install(h);
  assert.equal(h.state.optionsOpened, 0);
});

test("a fresh install before the app has ever run opens the address step", async () => {
  const h = loadBackground({ offline: true });
  await install(h);
  assert.equal(h.state.optionsOpened, 1);
  assert.equal(focus(h), "address");
});

test("a closed page is not opened again by the next start or the next alarm", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [adapter(SITE)] } });
  await install(h);
  assert.equal(h.state.optionsOpened, 1);

  // Not on every browser start: the same site still waits, in a new session,
  // and the reader has already been shown it.
  newSession(h);
  await startup(h);
  await alarm(h);
  assert.equal(h.state.optionsOpened, 1);
});

test("the app being closed on later starts never reopens the address step", async () => {
  const h = loadBackground({ offline: true });
  await install(h);
  newSession(h);
  await startup(h);
  await alarm(h);
  assert.equal(h.state.optionsOpened, 1);
});

test("an app that has answered once is never asked about again, even when it stops", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [] } });
  await install(h);
  h.sandbox.fetch = async () => { throw new TypeError("Failed to fetch"); };
  newSession(h);
  await startup(h);
  assert.equal(h.state.optionsOpened, 0, "the app is closed most of the time, and that is not a step");
});

test("a new site waiting later opens the page once, in its own right", async () => {
  const routes = { [ADAPTERS]: [adapter(SITE)] };
  const h = loadBackground({ routes, grantedOrigins: [ORIGIN] });
  await install(h);
  assert.equal(h.state.optionsOpened, 0, "the one site is already granted");

  routes[ADAPTERS] = [adapter(SITE), adapter(OTHER)];
  newSession(h);
  await alarm(h);
  assert.equal(h.state.optionsOpened, 1);
  assert.equal(focus(h), "sites");

  newSession(h);
  await alarm(h);
  await startup(h);
  assert.equal(h.state.optionsOpened, 1, "the same waiting site opens it only once");
});

test("two steps at once open one page in a session, and the second still gets its turn later", async () => {
  const routes = { [ADAPTERS]: [adapter(SITE)] };
  const h = loadBackground({ routes, grantedOrigins: [ORIGIN] });
  await install(h);

  routes[ADAPTERS] = [adapter(SITE), adapter(OTHER)];
  await alarm(h);
  assert.equal(h.state.optionsOpened, 1, "opened for the new site");

  routes[ADAPTERS] = [adapter(SITE), adapter(OTHER), adapter("ucuncu.example")];
  await alarm(h);
  assert.equal(h.state.optionsOpened, 1, "the same session is not opened a second time");

  newSession(h);
  await alarm(h);
  assert.equal(h.state.optionsOpened, 2, "the step that was held back is shown in the next session");
});

test("granting the permission ends the step, and the grant itself opens nothing", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [adapter(SITE)] } });
  await install(h);
  assert.equal(h.state.optionsOpened, 1);

  await h.sandbox.chrome.permissions.request({ origins: [ORIGIN] });
  await settle();
  assert.equal(h.state.optionsOpened, 1);
  assert.deepEqual(h.state.local.krikoOptionsMemory.sites, [], "a done step is forgotten");
  assert.equal(h.state.registered.length, 1, "and the site really is registered");
});

test("an upgrade learns what already waits and does not open for it", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [adapter(SITE)] } });
  await install(h, "update");
  assert.equal(h.state.optionsOpened, 0);

  // But the site it learnt is not forgotten into a fresh surprise later.
  newSession(h);
  await startup(h);
  assert.equal(h.state.optionsOpened, 0);
  assert.deepEqual(h.state.local.krikoOptionsMemory.sites, [ORIGIN]);
});

test("pressing Check again in the options page never opens another page", async () => {
  const h = loadBackground({ routes: { [ADAPTERS]: [adapter(SITE)] } });
  await send(h, { type: "KRIKO_SYNC_SITES" });
  await settle();
  assert.equal(h.state.optionsOpened, 0);
});

test("the plan is pure: the same record and memory give the same answer", () => {
  const h = loadBackground();
  const plan = h.sandbox.planOptionsOpen;
  const record = { reached: true, sites: [{ site: SITE, pattern: ORIGIN, state: "pending" }] };
  const first = plan(record, null, "install");
  const again = plan(record, null, "install");
  assert.deepEqual(first, again);
  assert.equal(first.step, "sites");
  assert.deepEqual(first.patterns, [ORIGIN]);
  // What it remembers is what makes the second answer different.
  assert.equal(plan(record, first.memory, "startup").step, null);
  // A site that stopped being pending is forgotten, so it can be shown again.
  const done = plan({ reached: true, sites: [] }, first.memory, "startup");
  assert.deepEqual(done.memory.sites, []);
  assert.equal(plan(record, done.memory, "startup").step, "sites");
});
