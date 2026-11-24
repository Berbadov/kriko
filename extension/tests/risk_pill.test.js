// The passive risk pill: the answer Kriko already has, shown beside the
// product's own heading without asking the reader to open anything.
//
// The state under test is the one the automatic run already writes to
// `chrome.storage.session` under this page's address. No message is sent and
// nothing is fetched to draw the pill; these tests apply that entry directly
// (and once through the storage path) and then read the shadow root.
const test = require("node:test");
const assert = require("node:assert");

const { loadContentScript } = require("./harness.js");

const URL = "https://shop.example/p/kettle-x200";
const PAGE = `<html><body><main><h1>Kettle X200</h1><p class="price">49,90 €</p></main></body></html>`;

const entry = (result) => ({ ok: true, result });

const claim = (title, severity = "high") => ({ title, severity });

function pillOf(script) {
  const host = script.document.querySelector("kriko-risk-pill");
  if (!host) return null;
  const button = host.shadowRoot && host.shadowRoot.querySelector("button.pill");
  return { host, button };
}

const settle = async () => {
  for (let i = 0; i < 3; i += 1) await new Promise((resolve) => setImmediate(resolve));
};

test("two findings read as two known flaws, with an amber dot", () => {
  const s = loadContentScript(PAGE, URL);
  s.applyRiskPillEntry(entry({ coverage: "RISKS_FOUND",
    claims: [claim("Water pump leaks"), claim("Timing chain stretches", "medium")] }));

  const { host, button } = pillOf(s);
  assert.ok(button, "the pill was not drawn beside the title");
  assert.equal(host.parentElement.tagName, "H1", "the pill belongs to the heading");
  assert.equal(button.textContent, "Kriko · 2 known flaws");
  assert.equal(button.dataset.tone, "findings");
  assert.match(button.title, /Water pump leaks/);
});

test("one finding is singular, and no findings is a green answer only when the product was recognised", () => {
  const one = loadContentScript(PAGE, URL);
  one.applyRiskPillEntry(entry({ coverage: "RISKS_FOUND", claims: [claim("Water pump leaks")] }));
  assert.equal(pillOf(one).button.textContent, "Kriko · 1 known flaw");
  assert.equal(pillOf(one).button.dataset.tone, "findings");

  const clean = loadContentScript(PAGE, URL);
  clean.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  assert.equal(pillOf(clean).button.textContent, "Kriko · no known flaws");
  assert.equal(pillOf(clean).button.dataset.tone, "positive");
});

test("a doubtful or unknown match is neutral, never a clean bill of health", () => {
  for (const coverage of ["PROBABLE_MATCH", "NOT_MATCHED", "RISKS_FOUND"]) {
    const s = loadContentScript(PAGE, URL);
    s.applyRiskPillEntry(entry({ coverage, claims: [] }));
    const { button } = pillOf(s);
    assert.equal(button.textContent, "Kriko · checked", coverage);
    assert.equal(button.dataset.tone, "neutral", coverage);
  }
  const unknown = loadContentScript(PAGE, URL);
  unknown.applyRiskPillEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Kettle X200" });
  assert.equal(pillOf(unknown).button.textContent, "Kriko · checked");
});

test("a non-listing page never gets a pill", () => {
  const s = loadContentScript(PAGE, URL);
  s.applyRiskPillEntry({ ok: false, code: "NO_ADAPTER", hostKnown: false });
  assert.equal(pillOf(s), null);
  s.applyRiskPillEntry(null);
  assert.equal(pillOf(s), null);

  // A recognised answer with no heading to sit beside is also silent: the
  // pill decorates a title, it does not invent one.
  const untitled = loadContentScript(`<html><body><main><p>No title</p></main></body></html>`, URL);
  untitled.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  assert.equal(pillOf(untitled), null);
});

test("re-render and repeated results never stack a second pill", () => {
  const s = loadContentScript(PAGE, URL);
  const value = entry({ coverage: "RISKS_FOUND", claims: [claim("Water pump leaks")] });
  s.applyRiskPillEntry(value);
  s.applyRiskPillEntry(value);
  assert.equal(s.document.querySelectorAll("kriko-risk-pill").length, 1);

  // The site's own router replaces the heading. The pill is re-hung on the
  // heading that is there now, and the detached one is gone.
  const old = s.document.querySelector("h1");
  const next = s.document.createElement("h1");
  next.textContent = "Kettle X200 — renewed";
  old.replaceWith(next);
  s.paintRiskPill();
  assert.equal(s.document.querySelectorAll("kriko-risk-pill").length, 1);
  assert.equal(pillOf(s).host.parentElement, next);
});

test("the option is on by default and an explicit off removes the pill immediately", async () => {
  const off = loadContentScript(PAGE, URL, { local: { krikoRiskPill: false } });
  await settle();
  off.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  assert.equal(pillOf(off), null, "the stored off was ignored");

  const s = loadContentScript(PAGE, URL);
  s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  assert.ok(pillOf(s), "the default is on");
  s.__local.krikoRiskPill = false;
  s.__deliverStorage({ krikoRiskPill: { newValue: false } }, "local");
  assert.equal(pillOf(s), null, "turning it off left the pill on the page");
});

test("a title that changes in place keeps one pill beside the new words", async () => {
  const s = loadContentScript(`<html><body><main><h1>Kettle X200</h1></main></body></html>`, URL);
  s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  const heading = s.document.querySelector("h1");

  // Same element, new text: no node was added, so the observer has to notice
  // the character change or the pill would sit beside a stale title.
  heading.firstChild.data = "Kettle X200 Pro";
  await settle();
  s.__flushTimers();

  assert.equal(s.document.querySelectorAll("kriko-risk-pill").length, 1);
  assert.equal(pillOf(s).host.parentElement, heading);
  assert.equal(heading.textContent, "Kettle X200 Pro",
    "the pill must not become part of the page's own title text");
});

test("an SPA navigation takes the old pill away until the new page has an answer", () => {
  const s = loadContentScript(PAGE, URL);
  s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  assert.ok(pillOf(s));

  // The shop's router changes the address without a load. The old answer is
  // about the old product, so nothing of it stays on screen.
  s.setTimeout = (fn) => { fn(); return 1; };
  s.window.history.pushState({}, "", "/p/toaster-t1");
  s.window.dispatchEvent(new s.window.Event("popstate"));
  assert.equal(pillOf(s), null);
  assert.equal(s.__sent.filter((m) => m.type === "PAGE_LOADED").length, 1);
});

test("a pill already in session storage is read without asking for an analysis", async () => {
  const key = "kriko_result_" + URL;
  const s = loadContentScript(PAGE, URL, {
    session: { [key]: entry({ coverage: "MATCHED_NO_DATA", claims: [] }) },
  });
  s.refreshRiskPill();
  await settle();
  assert.equal(pillOf(s).button.textContent, "Kriko · no known flaws");
  assert.equal(s.__sent.filter((m) => m.type === "PAGE_LOADED").length, 0,
    "nothing was analysed just to draw the pill");
});

test("the worker's forwarded result fills the pill where session storage is private", () => {
  const s = loadContentScript(PAGE, URL);
  s.__messageListeners[0]({
    type: "KRIKO_SESSION_UPDATE", url: URL,
    result: entry({ coverage: "RISKS_FOUND", claims: [claim("Water pump leaks")] }),
  }, {}, () => {});
  assert.equal(pillOf(s).button.textContent, "Kriko · 1 known flaw");
});

test("a real button opens the panel, with Enter and Space as well as a click", () => {
  const s = loadContentScript(PAGE, URL);
  s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  const { button } = pillOf(s);
  assert.equal(button.tagName, "BUTTON");
  assert.equal(button.type, "button");

  button.click();
  assert.equal(s.__sent.at(-1).type, "OPEN_PANEL");

  const press = (key) => button.dispatchEvent(new s.window.KeyboardEvent("keydown",
    { key, bubbles: true, cancelable: true }));
  const before = s.__sent.filter((m) => m.type === "OPEN_PANEL").length;
  press("Enter");
  press(" ");
  assert.equal(s.__sent.filter((m) => m.type === "OPEN_PANEL").length, before + 2);
});

test("a product title inside an article or main header still gets the pill", () => {
  // The bug this covers: `closest("header")` refused every header, so a shop
  // that puts its product <h1> in <article><header> (or <main><header>) never
  // saw a pill at all. Only the page masthead is off limits.
  for (const html of [
    `<html><body><main><article><header><h1>Kettle X200</h1></header></article></main></body></html>`,
    `<html><body><main><header><h1>Kettle X200</h1></header></main></body></html>`,
    `<html><body><section><header><h1>Kettle X200</h1></header></section></body></html>`,
  ]) {
    const s = loadContentScript(html, URL);
    s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
    const pill = pillOf(s);
    assert.ok(pill, `no pill for a content header: ${html}`);
    assert.equal(pill.host.parentElement.tagName, "H1");
  }
});

test("the masthead, nav, footer and aside are never read as the product title", () => {
  const mastheadOnly = loadContentScript(
    `<html><body><div class="page"><header><h1>Shop name</h1></header><main><p>Choose</p></main></div></body></html>`, URL);
  mastheadOnly.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  assert.equal(pillOf(mastheadOnly), null, "the site's own banner got a pill");

  const banner = loadContentScript(
    `<html><body><div role="banner"><h1>Shop name</h1></div><main><p>Choose</p></main></body></html>`, URL);
  banner.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  assert.equal(pillOf(banner), null, "a role=banner heading got a pill");

  for (const html of [
    `<html><body><nav><h1>Kettle X200</h1></nav></body></html>`,
    `<html><body><footer><h1>Kettle X200</h1></footer></body></html>`,
    `<html><body><aside><h1>Kettle X200</h1></aside></body></html>`,
    `<html><body><div role="navigation"><h1>Kettle X200</h1></div></body></html>`,
  ]) {
    const s = loadContentScript(html, URL);
    s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
    assert.equal(pillOf(s), null, `a pill was hung on ${html}`);
  }

  // With both on the page, the product title wins.
  const both = loadContentScript(
    `<html><body><header><h1>Shop name</h1></header><main><h1>Kettle X200</h1></main></body></html>`, URL);
  both.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  assert.equal(pillOf(both).host.parentElement.textContent, "Kettle X200");
});

test("a new answer with the same count repaints the detail it carries", () => {
  const s = loadContentScript(PAGE, URL);
  s.applyRiskPillEntry(entry({ coverage: "RISKS_FOUND", claims: [claim("Water pump leaks")] }));
  const first = pillOf(s).button;
  assert.equal(first.textContent, "Kriko · 1 known flaw");
  assert.match(first.title, /Water pump leaks/);

  // A re-run names a different flaw; the count, and so the visible words, are
  // unchanged. `dataset.text` alone would skip this and leave the old title.
  s.applyRiskPillEntry(entry({ coverage: "RISKS_FOUND", claims: [claim("Timing chain stretches")] }));
  const next = pillOf(s).button;
  assert.equal(next, first, "the pill was rebuilt instead of updated in place");
  assert.equal(next.textContent, "Kriko · 1 known flaw");
  assert.match(next.title, /Timing chain stretches/);
  assert.doesNotMatch(next.title, /Water pump leaks/);
  assert.equal(s.document.querySelectorAll("kriko-risk-pill").length, 1);
});

test("a press on the pill does not follow a title wrapped in a link", () => {
  const s = loadContentScript(
    `<html><body><main><a href="/p/kettle-x200"><h1>Kettle X200</h1></a></main></body></html>`, URL);
  s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  const { button } = pillOf(s);
  const event = new s.window.MouseEvent("click", { bubbles: true, cancelable: true });
  button.dispatchEvent(event);
  assert.equal(event.defaultPrevented, true, "the wrapping link would have navigated");
  assert.equal(s.__sent.at(-1).type, "OPEN_PANEL");
});

test("the pill takes no space in the heading's line box, and dark mode has its own ink", () => {
  const s = loadContentScript(PAGE, URL);
  s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  const { host } = pillOf(s);
  const css = host.shadowRoot.querySelector("style").textContent;
  // Zero-size inline wrapper: neither width nor height can grow a line box,
  // whatever the heading's font size.
  assert.match(css, /:host\s*\{[^}]*display:\s*inline-block/);
  assert.match(css, /:host\s*\{[^}]*width:\s*0/);
  assert.match(css, /:host\s*\{[^}]*height:\s*0/);
  assert.match(css, /:host\s*\{[^}]*position:\s*relative/);
  // The visible pill is out of flow inside that wrapper, after the title.
  assert.match(css, /\.pill\s*\{[^}]*position:\s*absolute/);
  assert.match(css, /\.pill\s*\{[^}]*left:\s*8px/);
  assert.match(css, /\.pill\s*\{[^}]*z-index:\s*1/);
  assert.match(css, /prefers-color-scheme:\s*dark/);
});

test("the pill is isolated from the page's own styles and says what it is", () => {
  const s = loadContentScript(`<html><head><style>
    h1 button { display: none !important; background: red !important; }
  </style></head><body><main><h1>Kettle X200</h1></main></body></html>`, URL);
  s.applyRiskPillEntry(entry({ coverage: "MATCHED_NO_DATA", claims: [] }));
  const { host, button } = pillOf(s);
  assert.ok(host.shadowRoot, "the pill is not in a shadow root");
  const css = host.shadowRoot.querySelector("style").textContent;
  assert.ok(css.includes(":host"));
  assert.ok(css.includes(":focus-visible"));
  assert.ok(css.includes("prefers-reduced-motion"));
  assert.ok(!/position:\s*fixed/.test(css), "a fixed pill would stay over the page while scrolling");
  assert.match(button.getAttribute("aria-label"), /Open the Kriko panel/);
});
