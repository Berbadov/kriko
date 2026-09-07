// Loads hover_lite/hover_lite.js into a jsdom document so the panel can be
// tested without a browser. hover_lite.js is an IIFE (no exports) driven by
// chrome.* events, so the harness captures the listeners it registers and
// hands them back for the test to fire.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const PANEL_JS = path.join(__dirname, "..", "hover_lite", "hover_lite.js");
const CARD_JS = path.join(__dirname, "..", "hover_lite", "risk_card.js");

function loadPanel({
  url = "https://www.sahibinden.com/ilan/vasita-otomobil-volkswagen-golf-123456/detay",
  analyzeResponse = { ok: false },
  // What the service worker says to the panel's *write* messages — marking a
  // claim, raising the app, starting research. Defaults to success because
  // that is the path nearly every test is about; a test that cares about
  // refusal sets it, and the panel must roll its optimistic paint back.
  workerResponse = { ok: true },
} = {}) {
  const dom = new JSDOM("<!DOCTYPE html><html><head></head><body></body></html>", { url });

  const runtimeListeners = [];
  const storageListeners = [];
  // Every message the panel sent to the service worker — the panel's half of
  // the messaging contract, which Phase 6c renamed.
  const sent = [];
  const sandbox = {
    document: dom.window.document,
    window: dom.window,
    location: dom.window.location,
    console,
    // Keep mount's animation timers no-ops so loading the panel in a test does
    // not schedule work after the test finishes.
    setTimeout: () => 0,
    clearTimeout: () => {},
    requestAnimationFrame: (fn) => { fn(); return 0; },
    chrome: {
      runtime: {
        onMessage: { addListener: (fn) => runtimeListeners.push(fn) },
        sendMessage(message, callback) {
          sent.push(message);
          if (typeof callback !== "function") return;
          callback(message.type === "ANALYZE" ? analyzeResponse : workerResponse);
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
  vm.runInContext(fs.readFileSync(CARD_JS, "utf8"), sandbox, { filename: "risk_card.js" });
  vm.runInContext(fs.readFileSync(PANEL_JS, "utf8"), sandbox, { filename: "hover_lite.js" });

  function openPanel() {
    for (const fn of runtimeListeners) fn({ type: "TOGGLE_HOVER_LITE" });
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

  function risks() {
    const root = shadow();
    return root ? root.querySelector(".lite-risks") : null;
  }

  /** Click something in the shadow tree, by selector. */
  function click(selector) {
    const el = shadow() && shadow().querySelector(selector);
    if (!el) throw new Error(`nothing matching ${selector} to click`);
    el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    return el;
  }

  return { dom, openPanel, deliverEntry, footer, listing, risks, click,
           shadow, sent, errorText, pipeline };
}

module.exports = { loadPanel };
