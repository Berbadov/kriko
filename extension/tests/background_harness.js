// Loads background.js (an MV3 service worker) into a vm context with a fake
// `chrome` and a fake `fetch`, and hands the test the listeners it registered.
//
// The worker registers everything at top level, so simply evaluating the file
// is enough to capture its handlers; the test then calls them directly rather
// than pretending to be Chrome's event loop.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const BACKGROUND_JS = path.join(__dirname, "..", "background.js");

// `offline` is the case a status-code stub cannot express: nothing is
// listening, so `fetch` rejects before there is a response to inspect. That is
// the ordinary state of the world for a reader who has not started the app.
// `statuses` is for the case the routes table cannot express: a server that
// is up and *refuses*. "The app said no" and "there is no app" are different
// answers, and the worker is now required to tell them apart.
// `grantedOrigins` is the third axis the routes table cannot express: a
// worker that knows about a site and has not been allowed to read it. Chrome
// answers `permissions.contains` from its own table, and the difference
// between "pending" and "reading" is the whole of B69's consent story — so the
// test has to be able to set it.
function loadBackground({
  routes = {}, tabResponses = {}, offline = false, statuses = {},
  grantedOrigins = [],
} = {}) {
  const state = {
    session: {},
    local: {},
    badge: {},
    // Every request the worker made, in order — the wire contract under test.
    requests: [],
    // Every message it sent to a content script.
    tabMessages: [],
    optionsOpened: 0,
    // Origins the reader has allowed, and the content-script registrations
    // the worker holds — both live here rather than in the worker, which is
    // the point: an MV3 worker is stopped constantly and Chrome is the one
    // remembering.
    granted: new Set(grantedOrigins),
    registered: [],
    alarms: {},
    permissionRequests: [],
    // Tabs the worker opened as a fallback, in order. A tab opened when the
    // app was raised is the original bug; a tab *not* opened when it was not
    // is the same bug wearing the other hat.
    tabsCreated: [],
  };
  const messageListeners = [];
  // Keyboard commands fire at the browser, not at a tab, so the worker
  // registers a listener the same way it registers the message one — captured
  // here and called directly, since there is no Chrome to press a key.
  const commandListeners = [];
  const clickListeners = [];
  // Both fire at the browser rather than at a tab, and both are how the site
  // sync recovers from a failed one: captured so a test can be the alarm.
  const alarmListeners = [];
  const permissionListeners = [];

  const area = (bucket) => ({
    async get(keys) {
      if (keys === undefined || keys === null) return { ...bucket };
      const wanted = Array.isArray(keys) ? keys : [keys];
      const out = {};
      for (const k of wanted) if (k in bucket) out[k] = bucket[k];
      return out;
    },
    async set(obj) { Object.assign(bucket, obj); },
    async remove(key) { delete bucket[key]; },
    setAccessLevel: async () => {},
    onChanged: { addListener() {} },
  });

  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    setTimeout: (fn) => { fn(); return 0; },
    performance: { now: () => 0 },
    URL,
    chrome: {
      runtime: {
        onInstalled: { addListener() {} },
        onStartup: { addListener() {} },
        // The worker reads the packaged manifest to find out which sites it
        // does *not* need to register — so the harness hands it the real
        // file, not a summary of it. A manifest edit that drops a static
        // block then changes what these tests see, which is correct.
        getManifest: () => JSON.parse(fs.readFileSync(
          path.join(__dirname, "..", "manifest.json"), "utf8")),
        onMessage: { addListener: (fn) => messageListeners.push(fn) },
        sendMessage() {},
        openOptionsPage() { state.optionsOpened += 1; },
      },
      commands: {
        onCommand: { addListener: (fn) => commandListeners.push(fn) },
      },
      storage: { session: area(state.session), local: area(state.local) },
      tabs: {
        onUpdated: { addListener() {} },
        async query() { return [{ id: 1 }]; },
        async create({ url }) { state.tabsCreated.push(url); return { id: 99 }; },
        async sendMessage(tabId, message) {
          state.tabMessages.push({ tabId, message });
          const reply = tabResponses[message.type];
          if (reply === undefined) throw new Error("no receiver");
          return typeof reply === "function" ? reply(message) : reply;
        },
      },
      scripting: {
        async executeScript() {},
        async getRegisteredContentScripts() { return [...state.registered]; },
        async registerContentScripts(scripts) {
          for (const script of scripts) {
            // Chrome rejects the whole call on a duplicate id, and the worker
            // is written around that — so the fake has to do it too, or the
            // drop-then-add ordering would be untested.
            if (state.registered.some((s) => s.id === script.id)) {
              throw new Error(`Duplicate script ID '${script.id}'`);
            }
          }
          state.registered.push(...scripts);
        },
        async unregisterContentScripts({ ids } = {}) {
          const drop = new Set(ids || state.registered.map((s) => s.id));
          state.registered = state.registered.filter((s) => !drop.has(s.id));
        },
      },
      permissions: {
        async contains({ origins = [] }) {
          return origins.every((o) => state.granted.has(o));
        },
        request({ origins = [] }, callback) {
          state.permissionRequests.push(origins);
          for (const o of origins) state.granted.add(o);
          const fired = permissionListeners.map((fn) => fn({ origins }));
          if (callback) callback(true);
          return Promise.all(fired).then(() => true);
        },
        onAdded: { addListener: (fn) => permissionListeners.push(fn) },
        onRemoved: { addListener() {} },
      },
      alarms: {
        create(name, info) { state.alarms[name] = info; },
        onAlarm: { addListener: (fn) => alarmListeners.push(fn) },
      },
      action: {
        onClicked: { addListener: (fn) => clickListeners.push(fn) },
        async setBadgeText({ text, tabId }) { state.badge[tabId] = text; },
        async setBadgeBackgroundColor() {},
      },
    },
    fetch: async (url, init) => {
      if (offline) throw new TypeError("Failed to fetch");
      const body = init && init.body ? JSON.parse(init.body) : null;
      state.requests.push({ url, method: (init && init.method) || "GET", body });
      const route = Object.keys(routes).find((r) => url.endsWith(r));
      if (route === undefined) {
        return { ok: false, status: 502, async text() { return "unreachable"; } };
      }
      const value = routes[route];
      const payload = typeof value === "function" ? value(body) : value;
      const status = statuses[route] || 200;
      return { ok: status < 400, status,
               async json() { return payload; },
               async text() { return JSON.stringify(payload); } };
    },
  };
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(BACKGROUND_JS, "utf8"), sandbox,
                  { filename: "background.js" });

  return { sandbox, state, messageListeners, commandListeners, clickListeners,
           alarmListeners, permissionListeners };
}

// Calling a message listener the way Chrome does: one shot at
// `sendResponse`, whether the handler answers synchronously or returns true
// and answers later. A handler that never responds hangs the test, which is
// the right failure — a message the worker silently drops leaves the panel
// waiting exactly this long.
const send = (h, message) =>
  new Promise((resolve, reject) => {
    let answered = false;
    for (const listener of h.messageListeners) {
      const handled = listener(message, {}, (response) => {
        answered = true;
        resolve(response);
      });
      if (handled === true || answered) return;
    }
    reject(new Error(`no handler answered ${message.type}`));
  });

module.exports = { loadBackground, send };
