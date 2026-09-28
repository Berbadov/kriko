// Loads hover_lite/hover_lite.js into a jsdom document so the panel can be
// tested without a browser. hover_lite.js is an IIFE (no exports) driven by
// chrome.* events, so the harness captures the listeners it registers and
// hands them back for the test to fire.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const PANEL_JS = path.join(__dirname, "..", "hover_lite", "hover_lite.js");
const CARD_JS = path.join(__dirname, "..", "hover_lite", "claim_card.js");

function loadPanel({
  url = "https://www.sahibinden.com/ilan/vasita-otomobil-volkswagen-golf-123456/detay",
  analyzeResponse = { ok: false },
  // What the service worker says to the panel's *write* messages — marking a
  // claim, raising the app, starting research. Defaults to success because
  // that is the path nearly every test is about; a test that cares about
  // refusal sets it, and the panel must roll its optimistic paint back.
  workerResponse = { ok: true },
  // What the worker answers a SEARCH with. Separate from `workerResponse`
  // because a search reply has its own shape and nearly every test that cares
  // about one does not care about the rest.
  searchResponse = { ok: true, items: [] },
  // What the worker answers the live-feed poll with. Its own option because
  // the feed is an aside: nearly every test wants it empty, and the two that
  // do not want it to be the only thing they are about.
  operationsResponse = { ok: true, feed: { items: [] } },
} = {}) {
  const dom = new JSDOM("<!DOCTYPE html><html><head></head><body></body></html>", { url, pretendToBeVisual: true });

  const runtimeListeners = [];
  const storageListeners = [];
  // Every message the panel sent to the service worker — the panel's half of
  // the messaging contract, which Phase 6c renamed.
  const sent = [];
  const timers = [];
  const sandbox = {
    document: dom.window.document,
    window: dom.window,
    location: dom.window.location,
    console,
    /* Timers are queued, not run, and not dropped either.
     *
     * They used to be a no-op, which kept mount's animation timers from
     * firing after a test finished — right, and it also meant anything the
     * panel *debounces* could never be tested at all. Queueing lets a test
     * that wants a debounce to land call `flushTimers()` and leaves every
     * other test exactly as it was: nothing runs unless something asks.
     */
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout: (id) => { if (id) timers[id - 1] = null; },
    requestAnimationFrame: (fn) => { fn(); return 0; },
    chrome: {
      runtime: {
        onMessage: { addListener: (fn) => runtimeListeners.push(fn) },
        sendMessage(message, callback) {
          sent.push(message);
          if (typeof callback !== "function") return;
          if (message.type === "ANALYZE") return callback(analyzeResponse);
          if (message.type === "SEARCH") return callback(searchResponse);
          if (message.type === "OPERATIONS") return callback(operationsResponse);
          callback(typeof workerResponse === "function" ? workerResponse(message) : workerResponse);
        },
        getURL: (p) => p,
      },
      storage: {
        onChanged: { addListener: (fn) => storageListeners.push(fn) },
      },
    },
  };
  // The panel pulls its icon/card renderers off window at load time.
  dom.window.__KrikoPanelIcons = { iconSvg: () => "", domainIconSvg: () => "" };
  vm.createContext(sandbox);
  // The *real* card renderer, not a stub. The controls a test cares about —
  // the verdict buttons — are in this markup, so a stub returning a bare
  // <div> would let the panel's wiring pass while shipping nothing clickable.
  vm.runInContext(fs.readFileSync(CARD_JS, "utf8"), sandbox, { filename: "claim_card.js" });
  vm.runInContext(fs.readFileSync(PANEL_JS, "utf8"), sandbox, { filename: "hover_lite.js" });

  function openPanel() {
    for (const fn of runtimeListeners) fn({ type: "TOGGLE_HOVER_LITE" });
  }

  // Mirror of background.js writing a worker stage to chrome.storage.session
  // as it begins one. The panel's status line is built from these, so a test
  // here is a test that the reader is told what is actually happening rather
  // than a sentence someone wrote once.
  function deliverStage(name, detail = "") {
    const key = "kriko_stage_" + dom.window.location.href;
    const value = { name, detail, at: Date.now() };
    for (const fn of storageListeners) fn({ [key]: { newValue: value } }, "session");
  }

  // Mirror of background.js writing the result to chrome.storage.session.
  function deliverEntry(entry) {
    const key = "kriko_result_" + dom.window.location.href;
    for (const fn of storageListeners) fn({ [key]: { newValue: entry } }, "session");
  }

  function shadow() {
    const host = dom.window.document.querySelector("kriko-panel-host");
    return host && host.shadowRoot ? host.shadowRoot : null;
  }

  function listing() {
    const root = shadow();
    return root ? root.querySelector(".lite-listing") : null;
  }

  function errorText() {
    const root = shadow();
    const el = root && root.querySelector(".lite-error");
    return el ? el.textContent.trim() : null;
  }

  function statusText() {
    const root = shadow();
    const el = root && root.querySelector(".lite-status");
    return el ? el.textContent.trim() : null;
  }

  function liveRows() {
    const root = shadow();
    if (!root) return [];
    return [...root.querySelectorAll(".lite-live-list li")]
      .map((one) => one.textContent.trim());
  }

  function footer() {
    const host = dom.window.document.querySelector("kriko-panel-host");
    return host && host.shadowRoot ? host.shadowRoot.querySelector(".lite-footer") : null;
  }

  // The panel keeps its pipeline stage on the host element so a test can read
  // it without reaching into the closure.
  function pipeline() {
    const host = dom.window.document.querySelector("kriko-panel-host");
    return host ? host.dataset.pipeline : null;
  }

  function claims() {
    const root = shadow();
    return root ? root.querySelector(".lite-claims") : null;
  }

  /** Click something in the shadow tree, by selector. */
  function click(selector) {
    const el = shadow() && shadow().querySelector(selector);
    if (!el) throw new Error(`nothing matching ${selector} to click`);
    el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    return el;
  }

  /* Runs what is queued *now*, not what running it queues.
   *
   * The distinction is the difference between a helper and a hang: a timer
   * that reschedules itself -- the live-feed poll does, once every two
   * seconds in a browser -- grew the array faster than the loop walked it,
   * and the whole file stopped for as long as anything would wait. Snapshot
   * first, so one flush is one tick of wall clock. */
  function flushTimers() {
    const pending = timers.slice();
    for (let i = 0; i < pending.length; i += 1) {
      const fn = pending[i];
      timers[i] = null;
      if (fn) fn();
    }
  }

  /** Type into a field in the shadow tree, the way a reader does. */
  function type(selector, value) {
    const el = shadow() && shadow().querySelector(selector);
    if (!el) throw new Error(`nothing matching ${selector} to type into`);
    el.value = value;
    el.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    return el;
  }

  return { dom, openPanel, deliverEntry, deliverStage, footer, listing, claims,
           click, type, shadow, sent, errorText, pipeline, flushTimers,
           statusText, liveRows };
}

module.exports = { loadPanel };
