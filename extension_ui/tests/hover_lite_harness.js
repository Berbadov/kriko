// Loads hover_lite/hover_lite.js into a jsdom document so the panel can be
// tested without a browser. hover_lite.js is an IIFE (no exports) driven by
// chrome.* events, so the harness captures the listeners it registers and
// hands them back for the test to fire.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const PANEL_JS = path.join(__dirname, "..", "hover_lite", "hover_lite.js");

function loadPanel() {
  const dom = new JSDOM("<!DOCTYPE html><html><head></head><body></body></html>", {
    url: "https://www.sahibinden.com/ilan/vasita-otomobil-volkswagen-golf-123456/detay",
  });

  const runtimeListeners = [];
  const storageListeners = [];
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
        sendMessage() {},
        getURL: (p) => p,
      },
      storage: {
        onChanged: { addListener: (fn) => storageListeners.push(fn) },
      },
    },
  };
  // The panel pulls its icon/card renderers off window at load time.
  dom.window.__KrikoPanelIcons = { iconSvg: () => "", domainIconSvg: () => "" };
  dom.window.__KrikoPanelRiskCard = {
    renderRiskCard: () => dom.window.document.createElement("div"),
    updateRiskCard() {},
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(PANEL_JS, "utf8"), sandbox, { filename: "hover_lite.js" });

  function openPanel() {
    for (const fn of runtimeListeners) fn({ type: "TOGGLE_HOVER_LITE" });
  }

  // Mirror of background.js writing the result to chrome.storage.session.
  function deliverEntry(entry) {
    const key = "kriko_result_" + dom.window.location.href;
    for (const fn of storageListeners) fn({ [key]: { newValue: entry } }, "session");
  }

  function footer() {
    const host = dom.window.document.querySelector("kriko-panel-host");
    return host && host.shadowRoot ? host.shadowRoot.querySelector(".lite-footer") : null;
  }

  return { dom, openPanel, deliverEntry, footer };
}

module.exports = { loadPanel };
