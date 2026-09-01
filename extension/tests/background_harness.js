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

function loadBackground({ routes = {}, tabResponses = {} } = {}) {
  const state = {
    session: {},
    local: {},
    badge: {},
    // Every request the worker made, in order — the wire contract under test.
    requests: [],
    // Every message it sent to a content script.
    tabMessages: [],
  };
  const messageListeners = [];

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
        onMessage: { addListener: (fn) => messageListeners.push(fn) },
        sendMessage() {},
      },
      storage: { session: area(state.session), local: area(state.local) },
      tabs: {
        onUpdated: { addListener() {} },
        async query() { return [{ id: 1 }]; },
        async sendMessage(tabId, message) {
          state.tabMessages.push({ tabId, message });
          const reply = tabResponses[message.type];
          if (reply === undefined) throw new Error("no receiver");
          return typeof reply === "function" ? reply(message) : reply;
        },
      },
      scripting: { async executeScript() {} },
      action: {
        onClicked: { addListener() {} },
        async setBadgeText({ text, tabId }) { state.badge[tabId] = text; },
        async setBadgeBackgroundColor() {},
      },
    },
    fetch: async (url, init) => {
      const body = init && init.body ? JSON.parse(init.body) : null;
      state.requests.push({ url, method: (init && init.method) || "GET", body });
      const route = Object.keys(routes).find((r) => url.endsWith(r));
      if (route === undefined) {
        return { ok: false, status: 502, async text() { return "unreachable"; } };
      }
      const value = routes[route];
      const payload = typeof value === "function" ? value(body) : value;
      return { ok: true, status: 200, async json() { return payload; },
               async text() { return JSON.stringify(payload); } };
    },
  };
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(BACKGROUND_JS, "utf8"), sandbox,
                  { filename: "background.js" });

  return { sandbox, state, messageListeners };
}

module.exports = { loadBackground };
