const test = require("node:test");
const assert = require("node:assert/strict");
const { loadPanel } = require("./hover_lite_harness.js");

const claim = (id, extra = {}) => ({
  pack_id: "p", claim_id: id, title: id, body: `Details of ${id}`,
  severity: "high", domain: "components", ...extra,
});
const answer = (claims, lookup_id = "answer-1") => ({
  ok: true, listing: {},
  result: { lookup_id, claims, identity: {}, context: {}, coverage: "RISKS_FOUND" },
});

test("live knowledge keeps existing cards, expansion, group state and focus", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  const card = p.shadow().querySelector(".lite-rc");
  const wrap = card.parentElement;
  const group = card.closest(".lite-domain-group");
  p.click(".lite-rc-toggle");
  p.click(".lite-domain-head");
  const button = card.querySelector(".lite-rc-toggle");
  button.focus();
  p.deliverEntry(answer([claim("new"), claim("old")]));
  assert.ok(card.isConnected, "an existing card was removed during a live update");
  assert.equal(card.parentElement, wrap);
  assert.equal(card.dataset.open, "1");
  assert.equal(group.dataset.open, "0");
  assert.equal(p.shadow().activeElement, button);
  button.click();
  assert.equal(card.dataset.open, "0", "a reordered card toggled the wrong claim");
  p.click(".lite-chip-expand");
  assert.ok([...p.shadow().querySelectorAll(".lite-rc")].every(c => c.dataset.open === "1"));
});

test("unchanged refreshes keep New cards and their controls in the DOM", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  p.deliverEntry(answer([claim("old"), claim("new")]));
  const card = p.shadow().querySelector('[data-fresh="1"]');
  p.deliverEntry(answer([claim("old"), claim("new")]));
  assert.ok(card.isConnected, "the New card blinked out on the next update");
  assert.equal(p.shadow().querySelectorAll(".lite-rc-new").length, 1);
});

test("changed and removed claims update without keeping stale text or expansion", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(answer([claim("old"), claim("removed")]));
  p.click(".lite-rc-toggle");
  p.deliverEntry(answer([claim("old", { body: "Updated evidence", domain: "other" })]));
  assert.equal(p.shadow().querySelectorAll(".lite-rc").length, 1);
  assert.match(p.claims().textContent, /Updated evidence/);
  assert.doesNotMatch(p.claims().textContent, /Details of old|removed/);
  assert.equal(p.shadow().querySelector(".lite-rc").dataset.open, "1");
  p.deliverEntry(answer([claim("old")], "answer-2"));
  assert.equal(p.shadow().querySelector(".lite-rc").dataset.open, "0");
  assert.equal(p.shadow().querySelector(".lite-rc-new"), null);
});

test("a new answer leaves an open shortlist as it was", async () => {
  const p = loadPanel({ workerResponse: (m) => (m.type === "COMPARE_LIST"
    ? { ok: true, max: 8, items: [{ queue_id: "q1", url: "https://x.example/a", name: "A", severities: [] }] }
    : { ok: true }) });
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  await new Promise((resolve) => setImmediate(resolve));
  p.click(".lite-compare-toggle");
  assert.equal(p.shadow().querySelector(".lite-compare-tray").hidden, false);
  p.deliverEntry(answer([claim("old"), claim("new")]));
  assert.equal(p.shadow().querySelector(".lite-compare-tray").hidden, false,
    "a live update does not close what the reader opened");
  assert.equal(p.sent.filter((m) => m.type === "QUEUE_ADD").length, 0, "and adds nothing");
});

test("the panel offers no box for asking an agent about a saved answer", () => {
  // An agent asked from here read the same pages the research had, so the box
  // repeated a button. Nothing in the panel sends a question to an agent.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry(answer([claim("old")]));
  assert.equal(p.shadow().querySelector(".lite-followup"), null);
  assert.equal(p.shadow().querySelector("textarea, input"), null);
  assert.equal(p.sent.filter(m => /ASK|QUESTIONS/.test(m.type)).length, 0);
});

test("an agent question without options accepts a typed answer in the panel", () => {
  const p = loadPanel({ workerResponse: () => ({ ok: true, plane: { backend: "agent" }, delivered: true,
    job: { job_id: "research", kind: "research", state: "running", attention: {
      questions: [{ id: "version", ask: "Which version is listed?", options: [] }],
    } },
  }) });
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result,
    subjects: [{ subject_id: "product", label: "Product", claims: 0 }],
  } });
  p.click(".lite-gap-btn");
  p.click(".lite-research-start");
  p.type(".lite-question-input", "The revised version");
  p.flushTimers();
  assert.equal(p.shadow().querySelector(".lite-question-input").value, "The revised version");
  p.shadow().querySelector(".lite-question-form").dispatchEvent(new p.dom.window.Event("submit", { bubbles: true, cancelable: true }));
  const told = p.sent.find(m => m.type === "JOB_SAY");
  assert.ok(told);
  assert.match(told.payload.text, /The revised version/);
});

test("deeper research progress keeps quick-look cards expanded without blinking", () => {
  let progress = 0.2;
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "quick", kind: "quick_look" } };
    if (m.type === "JOB_STATUS") return m.payload.job_id === "quick"
      ? { ok: true, job: { kind: "quick_look", state: "succeeded", done: true,
          result: { risks: [claim("Quick risk")] } } }
      : { ok: true, job: { state: "running", progress, message: "Reading sources" } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "An uncovered product" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "An uncovered product");
  p.click(".lite-research-start");
  const card = p.shadow().querySelector(".lite-quick .lite-rc");
  assert.ok(card);
  card.querySelector(".lite-rc-toggle").click();
  // #114: no deep run is followed on its own any more, so nothing re-renders
  // the quick-look cards at all — the expanded state simply stays.
  p.flushTimers();
  assert.ok(card.isConnected, "a progress poll replaced the quick-look card");
  assert.equal(card.dataset.open, "1");
  const status = p.shadow().querySelector(".lite-research-status").textContent;
  assert.match(status, /1 thing to know/);
  assert.doesNotMatch(status, /%/);
  assert.equal(p.sent.filter(m => m.type === "JOB_STATUS" && m.payload.job_id !== "quick").length, 0);
});

test("a research run that kept nothing says no data showed an issue", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "research", kind: "research",
      state: "succeeded", done: true,
      result: { documents: 4, outcome: "read 4 source(s), none of them said anything keepable",
        accepted: [], rejected: [], brief: "" } } };
    return { ok: true, delivered: true, job: { job_id: "research", kind: "research", state: "running" } };
  } });
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result,
    subjects: [{ subject_id: "product", label: "Product", claims: 0 }] } });
  p.click(".lite-gap-btn");
  p.click(".lite-research-start");
  p.flushTimers();
  const card = p.shadow().querySelector(".lite-noissue");
  assert.ok(card);
  assert.match(card.querySelector(".lite-noissue-note").textContent, /No data found that shows an issue/);
  assert.match(card.querySelector(".lite-noissue-note").textContent,
    /read 4 source\(s\), none of them said anything keepable/);
  assert.equal(p.shadow().querySelector(".lite-research-status").textContent, "",
    "the completed result is not repeated in the status line");
});

test("a research run with a kept claim or a brief is not called empty", () => {
  for (const result of [
    { documents: 2, accepted: [{ title: "Kept" }], rejected: [], outcome: "1 claim(s) kept", brief: "" },
    { documents: 3, accepted: [], rejected: [], outcome: "read 3 source(s), none of them said anything keepable", brief: "A brief to open." },
  ]) {
    const p = loadPanel({ workerResponse: m => {
      if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
      if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "research", kind: "research",
        state: "succeeded", done: true, result } };
      return { ok: true, delivered: true, job: { job_id: "research", kind: "research", state: "running" } };
    } });
    p.openPanel();
    p.deliverEntry({ ...answer([]), result: { ...answer([]).result,
      subjects: [{ subject_id: "product", label: "Product", claims: 0 }] } });
    p.click(".lite-gap-btn");
    p.click(".lite-research-start");
    p.flushTimers();
    const status = p.shadow().querySelector(".lite-research-status").textContent;
    assert.match(status, /Open the research job for findings/);
    assert.doesNotMatch(status, /No data found/);
  }
});

test("a quick look is one saved job, and joins a pack only when asked", () => {
  // The reader: "Quick looks shouldn't be a pack but quick looks can be a
  // part of a pack. Quick looks are saved."
  const sent = [];
  const p = loadPanel({ workerResponse: m => {
    sent.push(m);
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "quick", kind: "quick_look" } };
    if (m.type === "QUICK_TO_PACK") return { ok: true, job: { job_id: "deep", kind: "pack_author" } };
    if (m.type === "JOB_STATUS") return m.payload.job_id === "quick"
      ? { ok: true, job: { kind: "quick_look", state: "succeeded", done: true,
          result: { risks: [claim("Quick risk")] } } }
      : { ok: true, job: { state: "running", progress: 0.1, message: "Filing it" } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "An uncovered product" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "An uncovered product");
  p.click(".lite-research-start");
  assert.match(p.shadow().querySelector(".lite-research-status").textContent, /1 thing to know/);
  assert.ok(!sent.some(m => m.type === "QUICK_TO_PACK"), "a pack run started by itself");
  p.click(".lite-research-pack");
  const asked = sent.find(m => m.type === "QUICK_TO_PACK");
  assert.equal(asked.payload.job_id, "quick");
  assert.match(p.shadow().querySelector(".lite-research-status").textContent, /Filing it/);
});

test("a zero-issue quick look retains listing facts and evidence", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "oil-look", kind: "quick_look" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: {
      job_id: "oil-look", kind: "quick_look", state: "succeeded", done: true,
      result: { product: "Example oil", assumed: "Example Oil", risks: [], specs: [],
        diagnostic: { code: "no_issues_found", message: "No supported issues found in the pages checked." },
        coverage: { pages_read: 2, pages_relevant: 2, pages_extracted: 2, status: "no_supported_findings" },
        listing: { url: "https://example.test/oil", facts: { Volume: "4 L", Grade: "5W-30" } },
        evidence_pages: [{ url: "https://example.test/datasheet", domain: "example.test", excerpt: "Oil product data" }],
      },
    } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example oil" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example oil");
  p.click(".lite-research-start");
  assert.match(p.shadow().querySelector(".lite-research-status").textContent,
    /^$/, "the empty card is the single completed-state message");
  assert.ok(p.shadow().querySelector(".lite-noissue"), "specs do not hide the no-issue result");
  assert.equal(p.shadow().querySelector(".lite-quick-details").open, false,
    "listing facts stay collapsed until requested");
  assert.equal(p.shadow().querySelector(".lite-quick-assumed"), null,
    "the same product name is not echoed as an agent match");
  assert.match(p.shadow().querySelector(".lite-quick-specs").textContent, /Volume: 4 L/);
  assert.equal(p.shadow().querySelector(".lite-quick-source-list a").href, "https://example.test/datasheet");
  assert.equal(p.shadow().querySelector(".lite-noissue input"), null, "no agent question box in the card");
});

// ── the no-issue card ───────────────────────────────────────────────────
//
// A quick look that keeps nothing used to leave a sentence and a hole in the
// research slot. The hole is the finding: it now gets a card with what was
// read, what that warrants, and the pages themselves.

const EMPTY_QUICK = {
  job_id: "oil-look", kind: "quick_look", state: "succeeded", done: true,
  result: {
    risks: [], specs: [], dropped: 1,
    diagnostic: { code: "evidence_rejected",
      message: "Relevant pages were checked, but candidate findings did not pass the evidence checks." },
    coverage: { pages_read: 3, pages_relevant: 2, pages_extracted: 2,
      publishers_read: 2, sources_cited: 1, status: "no_supported_findings" },
    evidence_pages: [
      { url: "https://example.test/datasheet", domain: "example.test", excerpt: "Oil product data" },
    ],
  },
};

/* A quick look that keeps nothing. */
const emptyQuickWorker = () => (m) => {
  if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
  if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "oil-look", kind: "quick_look" } };
  if (m.type === "JOB_STATUS" && m.payload.job_id === "oil-look") return { ok: true, job: EMPTY_QUICK };
  return { ok: true, items: [] };
};

test("a quick look that kept nothing is a card with the pages and no agent box", () => {
  const p = loadPanel({ workerResponse: emptyQuickWorker() });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example oil" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example oil");
  p.click(".lite-research-start");

  const card = p.shadow().querySelector(".lite-noissue");
  assert.ok(card, "the empty quick look rendered a card");
  assert.equal(card.dataset.empty, "quick");
  assert.match(card.querySelector(".lite-noissue-title").textContent, /No sourced issues kept/);
  assert.match(card.querySelector(".lite-noissue-note").textContent,
    /candidate findings did not pass the evidence checks/);
  assert.equal(p.shadow().querySelector(".lite-research-status").textContent, "",
    "the diagnostic is not repeated beside the empty card");
  assert.match(card.querySelector(".lite-noissue-stats").textContent, /3\s*pages read/);
  assert.match(card.querySelector(".lite-noissue-stats").textContent, /1\s*cited/);
  assert.equal(card.querySelector(".lite-quick-source-list a").href,
    "https://example.test/datasheet");
  assert.equal(p.shadow().querySelector(".lite-quick"), null);
  assert.equal(card.querySelector("input, textarea"), null);
  assert.equal(p.sent.filter((m) => /ASK/.test(m.type)).length, 0);
});

test("a deep run that kept nothing shows the same no-issue card", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "agent" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "research", kind: "research",
      state: "succeeded", done: true,
      result: { documents: 4, outcome: "read 4 source(s), none of them said anything keepable",
        accepted: [], rejected: [], brief: "",
        coverage: { pages_read: 4, pages_relevant: 1, pages_extracted: 1,
          publishers_read: 1, sources_cited: 0 },
        evidence_pages: [{ url: "https://example.test/thread", domain: "example.test" }] } } };
    return { ok: true, delivered: true, job: { job_id: "research", kind: "research", state: "running" } };
  } });
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result,
    subjects: [{ subject_id: "product", label: "Product", claims: 0 }] } });
  p.click(".lite-gap-btn");
  p.click(".lite-research-start");
  p.flushTimers();

  const card = p.shadow().querySelector(".lite-noissue");
  assert.ok(card, "the empty deep run rendered the same card");
  assert.equal(card.dataset.empty, "deep");
  assert.match(card.textContent, /not proof that there is no issue/);
  assert.equal(card.querySelector(".lite-quick-source-list a").href,
    "https://example.test/thread");
  assert.equal(p.shadow().querySelector(".lite-research-status").textContent, "",
    "the completed deep-run finding appears only once");
});

test("a quick look with no pages says it could not check findings", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "empty", kind: "quick_look" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "empty", kind: "quick_look",
      state: "succeeded", done: true,
      result: { risks: [], specs: [], diagnostic: { code: "no_pages", message: "No source pages were read." },
        coverage: { pages_read: 0, pages_tried: 0, status: "no_sources" }, evidence_pages: [] } } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example");
  p.click(".lite-research-start");
  const card = p.shadow().querySelector(".lite-noissue");
  assert.match(card.querySelector(".lite-noissue-note").textContent, /No source pages were read/);
  assert.match(card.querySelector(".lite-noissue-stats").textContent, /0\s*pages read/);
  assert.equal(p.shadow().querySelector(".lite-research-status").textContent, "");
});

test("an unreadable answer with missing coverage does not claim zero pages", () => {
  const p = loadPanel({ workerResponse: m => {
    if (m.type === "RESEARCH_PLANE") return { ok: true, plane: { backend: "local" } };
    if (m.type === "RESEARCH_PRODUCT") return { ok: true, job: { job_id: "bad-answer", kind: "quick_look" } };
    if (m.type === "JOB_STATUS") return { ok: true, job: { job_id: "bad-answer", kind: "quick_look",
      state: "succeeded", done: true,
      result: { risks: [], specs: [], diagnostic: { code: "unreadable_answer" }, coverage: {},
        listing: { url: "https://example.test/product", facts: {} }, evidence_pages: [] } } };
    return { ok: true, items: [] };
  } });
  p.openPanel();
  p.deliverEntry({ ok: false, code: "UNKNOWN_PRODUCT", productName: "Example" });
  p.click(".lite-research-product");
  p.type(".lite-research-name", "Example");
  p.click(".lite-research-start");
  const card = p.shadow().querySelector(".lite-noissue");
  assert.match(card.querySelector(".lite-noissue-note").textContent, /unreadable answer.*Retry research/i);
  assert.equal(card.querySelector(".lite-noissue-stats"), null);
  assert.equal(card.querySelector(".lite-quick-source-list a"), null,
    "a listing URL is not presented as a page read or citation");
});

// ── light and dark ──────────────────────────────────────────────────────

const hostAttr = (p) => p.dom.window.document.querySelector("kriko-panel-host").dataset.theme;

test("the header toggle sets the theme attribute and remembers it", () => {
  const p = loadPanel();
  p.openPanel();
  assert.equal(hostAttr(p), "light", "fresh panels open in the warm paper theme");
  p.click(".lite-btn-theme");
  assert.equal(hostAttr(p), "dark");
  assert.equal(p.local["kriko.theme"], "dark");
  const button = p.shadow().querySelector(".lite-btn-theme");
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.match(button.getAttribute("aria-label"), /light/);
  p.click(".lite-btn-theme");
  assert.equal(hostAttr(p), "light");
  assert.equal(p.local["kriko.theme"], "light");
});

test("stored themes are respected and a fresh install opens warm paper", () => {
  const stored = loadPanel();
  stored.local["kriko.theme"] = "dark";
  stored.openPanel();
  assert.equal(hostAttr(stored), "dark");

  const system = loadPanel();
  system.dom.window.matchMedia = (q) => ({ matches: /prefers-color-scheme: dark/.test(q), media: q,
    addEventListener() {}, removeEventListener() {} });
  system.openPanel();
  assert.equal(hostAttr(system), "light");
});

test("reduced motion draws no ripple, and motion on draws one that removes itself", () => {
  const still = loadPanel();
  still.dom.window.matchMedia = (q) => ({ matches: /reduce/.test(q), media: q,
    addEventListener() {}, removeEventListener() {} });
  still.openPanel();
  const stillPanel = still.shadow().querySelector(".lite-panel");
  stillPanel.dispatchEvent(new still.dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 20, clientY: 20 }));
  assert.equal(still.shadow().querySelector(".lite-ripple"), null);

  const moving = loadPanel();
  moving.openPanel();
  const movingPanel = moving.shadow().querySelector(".lite-panel");
  movingPanel.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 600, right: 400, bottom: 600 });
  movingPanel.dispatchEvent(new moving.dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 30, clientY: 40 }));
  const dot = moving.shadow().querySelector(".lite-ripple");
  assert.ok(dot, "a press inside the panel drew a ripple");
  dot.dispatchEvent(new moving.dom.window.Event("animationend"));
  assert.equal(moving.shadow().querySelector(".lite-ripple"), null);
});

// ── dismissing the panel ────────────────────────────────────────────────
//
// The panel arrives on somebody else's page unasked, so it needs a way out
// that costs the reader nothing. The close button is one, and it is reachable
// only by pointer or by tabbing into a panel nobody tabbed into on purpose;
// Escape is the other, and it is the one every reader already knows.

test("Escape from inside the panel closes it, and the page's own Escape is left alone", () => {
  const p = loadPanel();
  p.openPanel();
  assert.ok(p.shadow().querySelector(".lite-panel"), "the panel is open");

  // A key raised on the page must not close a panel the reader is not in:
  // the site's own modal, its inline edit and its search box all answer
  // Escape, and the reader may not even know Kriko is on the page.
  p.dom.window.document.dispatchEvent(
    new p.dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.ok(p.shadow().querySelector(".lite-panel"), "the page's Escape closed the panel");

  p.press(".lite-btn-close", "Escape");
  assert.ok(p.shadow().querySelector(".lite-panel[data-closing='1']"),
    "Escape from a focused control did not start the close");
  p.flushTimers();
  assert.equal(p.shadow(), null, "the panel stayed in the page after its exit animation");
});

test("Escape closes the search field before it closes the panel", () => {
  const p = loadPanel();
  p.openPanel();
  p.click(".lite-btn-search");
  const field = p.shadow().querySelector(".lite-search-field");
  assert.ok(field, "the search field did not open");

  // The field's own handler stops the event on the way up, so the press that
  // dismisses the search does not also dismiss the panel under it.
  p.press(".lite-search-field", "Escape");
  assert.equal(p.shadow().querySelector(".lite-search-field"), null, "the search stayed open");
  assert.ok(p.shadow().querySelector(".lite-panel:not([data-closing='1'])"),
    "one Escape closed both the search and the panel");

  p.press(".lite-btn-close", "Escape");
  assert.ok(p.shadow().querySelector(".lite-panel[data-closing='1']"),
    "a second Escape did not close the panel");
});

test("the panel names itself as a region and keeps one live status line", () => {
  const p = loadPanel();
  p.openPanel();
  const panel = p.shadow().querySelector(".lite-panel");
  // A screen reader reading somebody's listing needs to be told where the
  // listing stopped and Kriko started; an unnamed region reads as loose text.
  assert.equal(panel.getAttribute("role"), "complementary");
  assert.equal(panel.getAttribute("aria-label"), "Kriko product knowledge");
  // The stage sentence is the one thing in the panel that changes on its own
  // while a run is in flight, so it is the one live region.
  assert.equal(p.shadow().querySelector(".lite-status").getAttribute("role"), "status");
});

// ── the motion profile ──────────────────────────────────────────────────
//
// Calm / Standard / Vivid, the same three the desktop app offers, stored
// under `kriko.motion` and worn as a single `data-motion` attribute on the
// host. The stylesheet scales every distance and tempo from it, so the panel
// only has to put the attribute where the sheet can see it — and follow a
// switch made on the options page while it is open.

const hostMotion = (p) =>
  p.dom.window.document.querySelector("kriko-panel-host").dataset.motion;

test("the motion profile paints the host, follows a switch, and reduced motion still wins", () => {
  // A stored profile opens the panel in it, read from chrome.storage.local.
  const p = loadPanel();
  p.local["kriko.motion"] = "vivid";
  p.openPanel();
  assert.equal(hostMotion(p), "vivid");

  // The options page switching the profile reaches the open panel through
  // chrome.storage.onChanged, and the choice is the one durable value the two
  // surfaces share.
  p.setLocal("kriko.motion", "calm");
  assert.equal(hostMotion(p), "calm");
  assert.equal(p.local["kriko.motion"], "calm");

  // Reduced motion outranks the profile: even on Vivid, a reader who asked for
  // stillness gets no ripple.
  const still = loadPanel();
  still.dom.window.matchMedia = (q) => ({ matches: /reduce/.test(q), media: q,
    addEventListener() {}, removeEventListener() {} });
  still.local["kriko.motion"] = "vivid";
  still.openPanel();
  assert.equal(hostMotion(still), "vivid");
  still.shadow().querySelector(".lite-panel").dispatchEvent(
    new still.dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 20, clientY: 20 }));
  assert.equal(still.shadow().querySelector(".lite-ripple"), null);
});

// ── minimal by default ──────────────────────────────────────────────────

test("a recognised gap is a phrase, with the engine's sentence as the title", () => {
  const say = "This one is recognised, but the installed packs hold nothing "
    + "about it yet. That is a gap, not a clean bill of health.";
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result, verdict: "recognised",
    next_step: { action: "research", say } } });

  const box = p.shadow().querySelector(".lite-verdict");
  assert.equal(box.dataset.verdict, "recognised");
  assert.equal(box.querySelector(".lite-verdict-say").textContent,
    "Recognised. Nothing installed covers it yet.");
  assert.equal(box.title, say, "the engine's sentence survived as the tooltip");
  const button = box.querySelector(".lite-verdict-btn");
  assert.equal(button.textContent, "Research");
  assert.equal(button.title, say);
});

test("no claims means no count row and no expand/collapse controls", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ...answer([]), result: { ...answer([]).result, verdict: "recognised",
    next_step: { action: "research", say: "gap" } } });
  assert.equal(p.shadow().querySelector(".lite-counts"), null);
  assert.equal(p.shadow().querySelector(".lite-claims-head"), null);

  p.deliverEntry(answer([claim("a")]));
  assert.ok(p.shadow().querySelector(".lite-counts"), "counts return with a claim");
  assert.ok(p.shadow().querySelector(".lite-claims-head"), "expand/collapse return too");
  assert.equal(p.shadow().querySelector(".lite-claims-label").textContent, "Risks · 1");
});
