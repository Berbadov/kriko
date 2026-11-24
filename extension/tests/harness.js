// Loads content.js into a jsdom document so the scraper can be tested without a
// browser. content.js is a plain content script (global function declarations,
// no exports), so it is evaluated in a vm context whose globals we then read.
//
// The registrations it makes are captured rather than stubbed away: which
// listeners exist, and how many copies of them, is what the injection guard
// (D14) is about — `background.js` injects this file imperatively, so a page
// can see it twice. `__injectAgain()` is that second injection, and the timers
// are queued rather than run, so loading the file still fires no request while
// a test that wants the auto-trigger can flush it.
//
// Storage is a bag per area, like the extension's own: the passive pill reads
// this page's session result and the reader's local option, and a test has to
// be able to write either and fire the change event the browser would. A
// `get` with a callback answers synchronously; one without answers a Promise,
// which is the shape MV3 gives `chrome.storage.session.get`.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const CONTENT_JS = path.join(__dirname, "..", "content.js");

function loadContentScript(html, url = "https://www.listing.example/ilan/vasita-otomobil-volkswagen-golf-123456/detay",
                            { local = {}, session = {} } = {}) {
  const dom = new JSDOM(html, { url });
  const source = fs.readFileSync(CONTENT_JS, "utf8");
  const messageListeners = [];
  const sent = [];
  const timers = [];
  const changeListeners = [];
  const localBag = { ...local };
  const sessionBag = { ...session };

  const area = (bag, name) => ({
    get(keys, done) {
      const out = {};
      for (const key of Array.isArray(keys) ? keys : [keys]) {
        if (key in bag) out[key] = bag[key];
      }
      if (typeof done === "function") { done(out); return undefined; }
      return Promise.resolve(out);
    },
    set(items, done) {
      const changes = {};
      for (const [key, value] of Object.entries(items || {})) {
        changes[key] = { oldValue: bag[key], newValue: value };
      }
      Object.assign(bag, items || {});
      for (const fn of changeListeners) fn(changes, name);
      if (typeof done === "function") done();
    },
    remove(keys, done) {
      const changes = {};
      for (const key of [].concat(keys)) {
        changes[key] = { oldValue: bag[key], newValue: undefined };
        delete bag[key];
      }
      for (const fn of changeListeners) fn(changes, name);
      if (typeof done === "function") done();
    },
  });

  const sandbox = {
    document: dom.window.document,
    window: dom.window,
    location: dom.window.location,
    console,
    // The script auto-triggers an analysis on load; keep the timer queued so
    // loading it in a test does not fire a request, but record the delay it
    // was asked for so a test can hold extension-13's fix in place (the
    // auto-trigger must not go back to adding seconds of its own).
    setTimeout: (fn, delay) => { sandbox.__lastTimeoutDelay = delay; timers.push(fn); return timers.length; },
    clearTimeout: (id) => { if (id) timers[id - 1] = null; },
    fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }),
    MutationObserver: dom.window.MutationObserver,
    // The script registers a message listener at load; stub the extension API
    // and keep what it registered.
    chrome: {
      runtime: {
        onMessage: { addListener: (fn) => messageListeners.push(fn) },
        sendMessage: (message, callback) => {
          sent.push(message);
          if (typeof callback === "function") callback({ ok: true });
        },
      },
      storage: {
        onChanged: { addListener: (fn) => changeListeners.push(fn) },
        local: area(localBag, "local"),
        session: area(sessionBag, "session"),
      },
    },
  };
  const evaluate = () =>
    vm.runInContext(source, sandbox, { filename: "content.js" });
  sandbox.__messageListeners = messageListeners;
  sandbox.__sent = sent;
  sandbox.__injectAgain = evaluate;
  sandbox.__flushTimers = () => {
    const pending = timers.splice(0);
    for (const fn of pending) if (fn) fn();
  };
  // Fire the storage change a browser would deliver to this content script.
  sandbox.__deliverStorage = (changes, areaName) => {
    for (const fn of changeListeners) fn(changes, areaName);
  };
  sandbox.__local = localBag;
  sandbox.__session = sessionBag;
  vm.createContext(sandbox);
  evaluate();
  return sandbox;
}

module.exports = { loadContentScript };
