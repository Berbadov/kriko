// Loads content.js into a jsdom document so the scraper can be tested without a
// browser. content.js is a plain content script (global function declarations,
// no exports), so it is evaluated in a vm context whose globals we then read.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const CONTENT_JS = path.join(__dirname, "..", "content.js");

function loadContentScript(html, url = "https://www.sahibinden.com/ilan/vasita-otomobil-volkswagen-golf-123456/detay") {
  const dom = new JSDOM(html, { url });
  const sandbox = {
    document: dom.window.document,
    window: dom.window,
    location: dom.window.location,
    console,
    // The script auto-triggers an analysis on load; keep the timer a no-op so
    // loading it in a test does not fire a request, but record the delay it
    // was asked for so a test can hold extension-13's fix in place (the
    // auto-trigger must not go back to adding seconds of its own).
    setTimeout: (fn, delay) => { sandbox.__lastTimeoutDelay = delay; return 0; },
    clearTimeout: () => {},
    fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }),
    MutationObserver: dom.window.MutationObserver,
    // The script registers a message listener at load; stub the extension API.
    chrome: {
      runtime: {
        onMessage: { addListener() {} },
        sendMessage() {},
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(CONTENT_JS, "utf8"), sandbox, { filename: "content.js" });
  return sandbox;
}

module.exports = { loadContentScript };
