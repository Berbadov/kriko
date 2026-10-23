// Loads the real options page (options.html and options.js) into jsdom with a
// stub of the extension API, the way the page meets it when the browser opens
// it. The page is mostly a renderer of answers the service worker gives, so
// the stub answers the messages the page sends and keeps the storage the page
// reads and writes in two bags a test can look at.
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const DIR = path.join(__dirname, "..", "options");

// `answer` is asked first about each message the page sends the worker; when it
// returns nothing the stock answers below stand.
function loadOptions({ local = {}, hash = "", sites = [], light = false, answer = null } = {}) {
  const html = fs.readFileSync(path.join(DIR, "options.html"), "utf8")
    .replace(/<script src="options.js"><\/script>/, "");
  const dom = new JSDOM(html, {
    url: "chrome-extension://kriko/options/options.html" + hash,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.matchMedia = (query) => ({
    matches: light && /light/.test(query), media: query,
    addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {},
  });
  window.HTMLElement.prototype.scrollIntoView = function scrollIntoView() { this.dataset.scrolled = "1"; };

  const bag = { ...local };
  const sent = [];
  const changeListeners = [];
  const set = (items, done) => {
    const changes = {};
    for (const [k, v] of Object.entries(items || {})) changes[k] = { oldValue: bag[k], newValue: v };
    Object.assign(bag, items || {});
    for (const fn of changeListeners) fn(changes, "local");
    if (done) done();
  };
  window.chrome = {
    runtime: {
      lastError: null,
      getManifest: () => ({ version: "0.0.0" }),
      sendMessage(message, callback) {
        sent.push(message);
        const custom = answer ? answer(message) : undefined;
        const reply = custom !== undefined ? custom : ({
          GET_API_BASE: { ok: true, default: "http://127.0.0.1:8787", stored: null },
          KRIKO_SITE_STATUS: { ok: true, status: { sites } },
          KRIKO_SYNC_SITES: { ok: true, status: { sites } },
          KRIKO_COMPAT: { ok: true, compat: null },
          KRIKO_KEPT: { ok: true, kept: { answers: 0, pages: 0, intents: 0, sites: 0, muted: [] } },
          KRIKO_CLEAR: { ok: true, kept: { answers: 0, pages: 0, intents: 0, sites: 0, muted: [] } },
          KRIKO_SET_MUTED: { ok: true, muted: [], status: { sites } },
        }[message.type] || { ok: true });
        if (callback) callback(reply);
      },
    },
    storage: {
      onChanged: { addListener: (fn) => changeListeners.push(fn) },
      local: {
        get(keys, done) {
          const out = {};
          for (const k of Array.isArray(keys) ? keys : [keys]) if (k in bag) out[k] = bag[k];
          if (done) done(out);
        },
        set,
        remove(keys, done) {
          for (const k of [].concat(keys)) delete bag[k];
          if (done) done();
        },
      },
    },
    permissions: { request() {}, contains(_, done) { if (done) done(false); } },
  };
  window.eval(fs.readFileSync(path.join(DIR, "options.js"), "utf8"));
  return { window, document: window.document, bag, set, sent };
}

const settle = async () => {
  for (let i = 0; i < 6; i += 1) await new Promise((r) => setImmediate(r));
};

module.exports = { loadOptions, settle };
