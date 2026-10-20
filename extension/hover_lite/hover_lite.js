/* Hover Lite — floating analyzer card injected into listing pages an
   installed adapter matches, via Shadow DOM. The toolbar action toggles visibility.

   State machine:
     idle      → no analysis run yet (button: "Search this product")
     analyzing → request in flight (skeleton + spinner)
     result    → AnalyzeResponse rendered
     error     → backend error message

   Background already auto-analyzes on PAGE_LOADED; we listen for
   chrome.storage.session changes for live updates and additionally hit
   GET_CACHED_RESULT on mount so a result that arrived before the user opened
   the card shows up immediately. */

(function () {
  if (window.__krikoPanelInstalled) return;
  window.__krikoPanelInstalled = true;

  const { iconSvg, domainIconSvg } = window.__KrikoPanelIcons;
  const { renderClaimCard, updateClaimCard, markClaimCard, factClaimCard, renderRichText } =
    window.__KrikoPanelClaimCard;
  const { describeRun, coverageSummary } = window.__KrikoRunProgress;

  const HOST_TAG = "kriko-panel-host";

  /* What the panel says before anything has been analysed.
   *
   * It used to name one site — "Open a <site> listing, then analyze." —
   * which was the last of the site's own knowledge left in the client after
   * every other trace of it was pushed into the pack's adapter. The panel only
   * ever mounts on a page an adapter matched, so naming *which* site was never
   * information the reader needed; it was only a sentence that would be wrong
   * on the second site and unnoticed on the third. */
  const IDLE_HINT = "See what is known about this product.";
  // A product nothing installed knows: the button researches it, so the hint
  // says what it will do rather than promising a search that cannot find it.
  const UNKNOWN_HINT = "New product. Research it to see what is known.";

  /* The reader's light/dark choice, shared with the options page. Absent when
   * they have never chosen, in which case the system preference decides — the
   * stylesheet already paints that, so the first frame is right either way. */
  const THEME_KEY = "kriko.theme";
  /* The reader's motion profile, shared with the options page and with the
   * desktop app's own setting. Standard is the default. */
  const MOTION_KEY = "kriko.motion";
  const MOTION_PROFILES = ["calm", "standard", "vivid"];
  /* How see-through the panel is, shared with the options page: "glass"
   * (the default; the page shows through, blurred) or "solid" for a reader who
   * finds that hard to read. Anything else is the default. */
  const GLASS_KEY = "kriko.glass";

  /* The engine's verdict, as a word the panel shows. Three of the four are
   * worth a banner; `recognised` is the ordinary case and gets none. */
  const VERDICT_WORD = {
    recognised: "Recognised",
    probably: "Probably this one",
    several: "One of several",
    unrecognised: "Not recognised",
  };

  // ─── State ────────────────────────────────────────────────────────────
  const state = {
    mounted: false,            // panel currently in DOM
    closing: false,            // exit animation in flight
    visible: false,            // logical visibility (mounted && !closing)
    side: "right",             // initial dock side
    pos: null,                 // {left, top} once dragged
    dragging: false,
    compact: false,
    openIds: new Set(),        // expanded claim keys (stable across reordering)
    detailsOpen: false,        // Listing-details panel collapsed by default
    openDetailRows: new Set(), // expanded rows inside listing details
    pipeline: "idle",          // idle | analyzing | result | error
    result: null,              // AnalyzeResponse
    // B152.4: the knowledge clock last seen on the live poll, and the cards
    // that arrived since this answer was first shown (marked "New").
    knowledge: null,
    freshKeys: new Set(),
    errorMsg: null,
    errorCode: null,
    listingMeta: null,         // derived from background metadata response
    queue: null,               // {url, phase, text}: this page's Add to queue press
    // The reader as a buyer (`buyer_card.js`): what the app said about this page
    // as a purchase, the questions about earlier purchases that have come due,
    // the shortlist's pick, and which little forms are open.
    buyer: null,
    buyerDue: [],
    buyerUi: {},
    pick: null,
    queueHelpOpen: false,
    // Typing the name. Panel-local: a search is a question the reader is
    // asking right now, not something the next analysis should remember.
    searchOpen: false,
    searchQuery: "",
    searchResults: null,       // null = nothing asked yet, [] = asked and none
    searchBusy: false,
    searchError: null,
    // Set only by an explicit press. The automatic run at page load leaves it
    // alone, because nobody asked it anything.
    noAdapter: false,
    // Whether some installed pack reads this *site* at all, vs this specific
    // page just not being one it recognises (a category page, a search
    // results page). Same NO_ADAPTER code either way — the reader's next
    // step is completely different, so the panel needs to tell them apart.
    hostKnown: false,
    // The page is on a site nothing reads and is worth learning (the worker's say).
    learnable: false,
    // claim_id -> verdict, for cards the reader has judged. Panel-local and
    // deliberately not persisted here: the app owns the marks, this is only
    // what to paint until the next analysis re-reads them.
    marks: new Map(),
    // claim_id -> what the cited page said when it was last re-read, and the
    // set currently being read. Panel-local for the same reason `marks` is:
    // the app owns the row, this is what to paint until the next analysis.
    facts: new Map(),
    checkingFacts: new Set(),
    // subject_id currently being researched, so the button can say so rather
    // than looking unpressed while a job starts.
    researching: null,
    // Which research plane this installation is configured for, and what it
    // costs — fetched once, lazily, the first time a gap is rendered. `null`
    // means "not asked yet", not "free": the cost line stays hidden rather
    // than guessing until the app has actually answered.
    researchPlane: null,
    researchPlaneRequested: false,
    researchPlaneError: "",
    // The agents this panel can use (`AGENTS`), the app's own pick, the one
    // picked here ("" until the reader changes it), and "Learn this page":
    // whether it is running, what it said while it ran, and what it taught.
    agents: null,
    agentsRequested: false,
    agentChosen: "",
    agentPick: "",
    learning: false,
    learnMessage: "",
    lesson: null,
    researchOpen: false,
    researchTarget: null,
    researchName: "",
    // B149: a product page nothing installed knows — the name the page gave
    // it, which is what the reader would type into Research anyway.
    unknownProduct: "",
    researchContext: "",
    researchJob: null,
    researchMessage: "",
    // B147: what the reader picked for the run's own questions, and what
    // became of saying it — per question id, for the chips to show.
    researchAnswers: {},
    researchTold: {},
    researchDraftAnswers: {},
    // B148: the quick look's answer, kept while the deeper run goes on.
    // `{ assumed, risks, dropped }` or null.
    researchQuick: null,
    // What the followed run is doing, from its own log (`run_progress.js`):
    // the stage it has reached and the pages it has read, never a percentage.
    researchRun: null,
    // The saved quick look the "Add to a pack" button would file, or null.
    researchQuickJob: null,
    taskLogs: new Map(),
    quickSourcesOpen: false,
    // When the followed run started, for the elapsed time beside its stage.
    researchStartedAt: 0,
    researchState: "",
    cancelling: false,
    /* Which step the run in flight has reached.
     *
     * Written by the worker as each step begins. Until now this line was a
     * constant sentence that named two things the engine does not do, which
     * is worse than a spinner: a spinner admits it knows nothing. `null`
     * means no run is in flight or none has reported yet. */
    stage: null,
    /* What the rest of Kriko is doing, and whether anyone has asked.
     *
     * The panel is the one surface a reader is on *because* they are not in
     * the app, so a run their own agent started was invisible to them
     * exactly when it mattered. `null` means not asked yet, `[]` means asked
     * and nothing is running — a real answer, and a different one. */
    live: null,
    liveTimer: null,
    /* The reader's light/dark choice: "" until storage has answered, so an
     * unset value keeps following the system. */
    theme: "",
    /* The motion profile, `""` until storage has answered, in which case
     * Standard is what the stylesheet already holds. */
    motion: "",
    /* "glass" or "solid"; `""` until storage has answered, which is glass. */
    glass: "",
    /* A run that kept nothing has a card of its own. null means none; the
     * object is `{ title, note, coverage, evidence_pages, outcome }`. */
    researchEmpty: null,
  };

  // ─── Element refs (populated in mount) ────────────────────────────────
  let hostEl = null;
  let shadow = null;
  let panel = null;
  let countsEl = null;
  let bodyEl = null;
  let statusEl = null;
  let ctaBtn = null;
  let claimsHeadEl = null;
  let claimsListEl = null;
  let densityBtn = null;
  let closeBtn = null;
  let searchBtn = null;
  let footerEl = null;

  let closeTimer = null;

  // A memo ref so listing details only rebuild when the underlying
  // data changes — toggles flip data-attributes in place so the CSS
  // animations can play.
  let lastDetailsListingMeta = null;

  // The severity counts last painted, so a number that changed can bump once.
  let lastCountNumbers = null;

  // ─── No font is fetched, and that is the feature ──────────────────────
  //
  // This used to inject a `fonts.googleapis.com` stylesheet into the host
  // page. Three things wrong with that, and they compound:
  //
  //   * It told Google which car listings the reader was looking at. Kriko is
  //     local-first — the engine runs on the reader's machine precisely so
  //     that what they are shopping for is nobody else's business — and the
  //     one component running inside a third-party page was the one making an
  //     outbound request per listing.
  //   * It failed offline, which is the state the whole product is designed
  //     for. The panel rendered in a fallback face, differently from every
  //     screenshot and every test.
  //   * It mutated the host document's `<head>`, from a content script, on a
  //     page we do not own.
  //
  // The Kriko face is Geist, one variable file per script, and it ships
  // *inside* the extension (assets/fonts, SIL OFL, licence beside it). It is
  // registered from there: the URL is the extension's own, so nothing leaves
  // the machine and it loads offline. `@font-face` inside a shadow root is
  // ignored by the browser, so the faces go to `document.fonts` through the
  // FontFace API, which adds no element to the page's `<head>`. The family
  // name is Kriko's own, so a page that happens to load Geist is never
  // restyled by ours, nor ours by it. The Turkish letters sit in the second
  // file. Guarded by a test that fails on a remote URL anywhere in the
  // extension.
  const FACES = [
    ["Kriko Sans", "Geist-latin.woff2",
      "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"],
    ["Kriko Sans", "Geist-latin-ext.woff2",
      "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF"],
  ];
  let facesLoaded = false;
  function loadFaces() {
    if (facesLoaded) return;
    facesLoaded = true;
    if (typeof FontFace !== "function" || !document.fonts) return;
    for (const [family, file, unicodeRange] of FACES) {
      try {
        const face = new FontFace(
          family,
          `url(${chrome.runtime.getURL("assets/fonts/" + file)})`,
          { weight: "100 900", display: "swap", unicodeRange },
        );
        face.load().then((loaded) => document.fonts.add(loaded)).catch(() => {});
      } catch (_) {
        // A face that will not load leaves the fallback stack in place.
      }
    }
  }

  // ─── Helpers ──────────────────────────────────────────────────────────
  // renderRichText (claim_card.js) renders the light markdown agents and packs
  // write; the panel uses it wherever that prose lands.

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // What the panel puts above the claims. Two sources, and the split is the
  // point of Phase 6c:
  //
  //   `entry.result`  — what the ENGINE understood. Rendering this rather than
  //                     the page's own words makes the header double as the
  //                     answer to "did it understand this car?", which is the
  //                     question a reader actually has when the claims look
  //                     wrong. A header echoing the page can never say that.
  //   `entry.listing` — the damage and equipment panels, scraped locally and
  //                     never sent anywhere, because the engine has no rule
  //                     for them.
  //
  // Nothing below names a car attribute. The identity keys, the context keys
  // and the units are all whatever the answering pack declared, so a pack for
  // a category nobody has written yet renders here without an edit.

  function reduceMotion() {
    return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  /* ─── Light and dark ───────────────────────────────────────────────────
   *
   * The choice lives in chrome.storage.local under one key, shared with the
   * options page, so either surface opens the way the other was left. Until
   * storage answers — and when the reader has never chosen — the system
   * preference decides, which is also what the stylesheet paints before this
   * file runs. The host element carries `data-theme`, because the panel lives
   * in a shadow root and the attribute has to live on the element the sheet's
   * `:host([data-theme="light"])` can see. */
  function prefersLight() {
    return Boolean(window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches);
  }

  function currentTheme() {
    return state.theme || (prefersLight() ? "light" : "dark");
  }

  function paintTheme() {
    const theme = currentTheme();
    if (hostEl) hostEl.dataset.theme = theme;
    const button = panel?.querySelector(".lite-btn-theme");
    if (!button) return;
    // The icon is the way out of the theme the panel is in, so it names the
    // action rather than the state.
    const label = theme === "light" ? "Switch to dark theme" : "Switch to light theme";
    button.innerHTML = iconSvg(theme === "light" ? "moon" : "sun", { size: 16, strokeWidth: 2 });
    button.setAttribute("aria-label", label);
    button.title = label;
    button.setAttribute("aria-pressed", theme === "light" ? "true" : "false");
  }

  function readTheme() {
    try {
      chrome.storage?.local?.get?.([THEME_KEY], (bag) => {
        void chrome.runtime.lastError;
        const saved = bag?.[THEME_KEY];
        if (saved === "light" || saved === "dark") state.theme = saved;
        paintTheme();
      });
    } catch (_) {
      // A storage that will not answer leaves the system preference in place.
      paintTheme();
    }
  }

  function toggleTheme() {
    state.theme = currentTheme() === "light" ? "dark" : "light";
    paintTheme();
    try {
      chrome.storage?.local?.set?.({ [THEME_KEY]: state.theme }, () => {
        void chrome.runtime.lastError;
      });
    } catch (_) {
      // Kept for this panel only; the choice still holds while it is open.
    }
  }

  /* ─── Motion profile ───────────────────────────────────────────────────
   *
   * Calm / Standard / Vivid, the same three the desktop app offers, stored
   * under one key. The stylesheet does the work: the host's `data-motion`
   * selects a whole set of duration and distance tokens, so this file only
   * has to put the attribute in the right place. Reduced motion is separate
   * and still wins — the stylesheet's media block is unconditional. */
  function currentMotion() {
    return MOTION_PROFILES.includes(state.motion) ? state.motion : "standard";
  }

  function paintMotion() {
    if (hostEl) hostEl.dataset.motion = currentMotion();
  }

  function readMotion() {
    try {
      chrome.storage?.local?.get?.([MOTION_KEY], (bag) => {
        void chrome.runtime.lastError;
        const saved = bag?.[MOTION_KEY];
        if (MOTION_PROFILES.includes(saved)) state.motion = saved;
        paintMotion();
      });
    } catch (_) {
      // A storage that will not answer leaves Standard in place.
      paintMotion();
    }
  }

  /* ─── Glass or solid ───────────────────────────────────────────────────
   *
   * The stylesheet does the work, as with the motion profile: the host's
   * `data-glass` selects an opaque set of the two tokens the panel's
   * background reads. Absent, the panel is glass. */
  function paintGlass() {
    if (hostEl) hostEl.dataset.glass = state.glass === "solid" ? "solid" : "glass";
  }

  function readGlass() {
    try {
      chrome.storage?.local?.get?.([GLASS_KEY], (bag) => {
        void chrome.runtime.lastError;
        state.glass = bag?.[GLASS_KEY] === "solid" ? "solid" : "";
        paintGlass();
      });
    } catch (_) {
      // A storage that will not answer leaves the glass in place.
      paintGlass();
    }
  }

  /* A ripple under the pointer, drawn once and removed by its own animation.
   * Appended to the panel so it is clipped by the panel's rounded corners and
   * never lands on the host page. Off entirely for reduced motion. */
  function rippleAt(event) {
    if (reduceMotion() || !panel) return;
    if (typeof event.clientX !== "number") return;
    const rect = panel.getBoundingClientRect();
    const dot = document.createElement("span");
    dot.className = "lite-ripple";
    dot.style.left = (event.clientX - rect.left) + "px";
    dot.style.top = (event.clientY - rect.top) + "px";
    panel.appendChild(dot);
    dot.addEventListener("animationend", () => dot.remove());
  }

  function deriveListingMeta(entry) {
    if (!entry) return null;
    const result = entry.result || {};
    const listing = entry.listing || {};
    const identity = result.identity || {};
    const context = result.context || {};
    const units = result.context_units || {};

    // A cached entry from before the panel was declared holds a bare array
    // rather than named buckets. It used to be labelled with the site's own
    // Turkish heading, hardcoded here — the last word of anyone else's
    // language left in this file. The pack's own fallback bucket is the right
    // label and the only one this file is entitled to.
    let equipment = {};
    const buckets = (listing.panel && listing.panel.equipment) || {};
    if (Array.isArray(listing.equipment)) {
      if (listing.equipment.length) {
        equipment = { [buckets.fallback_category || "Other"]: listing.equipment };
      }
    } else if (listing.equipment && typeof listing.equipment === "object") {
      equipment = listing.equipment;
    }

    const identityLine = Object.values(identity)
      .filter((v) => v !== null && v !== undefined && v !== "")
      .join(" ");

    // extension-11 (B145 audit): every context entry printed as a "fact",
    // including the seller's own free-text sentence — a unit is the pack's
    // own signal that a value is a measured fact rather than prose, so only
    // entries the pack declared a unit for (even "" for a bare count) belong
    // in this line.
    //
    // A number with a unit is a magnitude and reads better grouped
    // ("190,000 km"); a number without one is as likely to be a year, where
    // grouping would render 2014 as "2,014".
    const facts = Object.entries(context)
      .filter(([key, v]) => v !== null && v !== undefined && v !== "" && key in units)
      .map(([key, value]) => {
        const unit = units[key];
        if (typeof value === "number" && unit) {
          return `${value.toLocaleString()} ${unit}`;
        }
        return unit ? `${value} ${unit}` : String(value);
      });

    return {
      title: listing.title || identityLine || "Untitled listing",
      identity_line: identityLine,
      facts,
      resolved: Boolean(identityLine),
      damage_info: listing.damage_info || null,
      equipment,
      // The answering pack's own rules for the two local blocks: what each
      // damage state is called, which tone it takes, and which combinations
      // are worth shouting about. Absent for a page no adapter matched, in
      // which case the panels below render nothing rather than guessing.
      panel: listing.panel || {},
    };
  }

  // ── Critical alerts, from rules the pack declared ─────────────────────
  //
  // These used to be Turkish part regexes and English advice strings written
  // out here, which meant the panel could only ever shout about a car sold on
  // one site: a second listing site, a second market, or a category that is
  // not cars all needed an edit to this file, and history in this repo says
  // that edit is the one that gets forgotten.
  //
  // What is left is an interpreter. It can match declared terms, count items,
  // count them per declared side, compare a measure against a threshold, and
  // stay quiet when a more specific rule already spoke. It cannot do anything
  // else, and that is the point — a pack ships data into this panel, never
  // code, because code here would run on every page the extension can see.

  // Both ends folded, so a pack author writes one spelling: case, accents and
  // the dotless i all collapse. Substring rather than word boundary, because
  // "Motor Kaputu" has to match "kaput" and a suffixing language is exactly
  // what a word boundary would refuse.
  function foldTerm(text) {
    if (text === null || text === undefined) return "";
    return String(text)
      .replace(/ı/g, "i")
      .replace(/İ/g, "i")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/\p{M}/gu, "")
      .normalize("NFC")
      .replace(/\s+/g, " ")
      .trim();
  }

  function matchesAnyTerm(haystack, terms) {
    const folded = foldTerm(haystack);
    if (!folded) return false;
    return (terms || []).some((term) => {
      const needle = foldTerm(term);
      return needle && folded.includes(needle);
    });
  }

  function sideCounts(items, sides) {
    const out = {};
    for (const side of sides || []) {
      out[side.key] = items.filter((item) => matchesAnyTerm(item, side.terms)).length;
    }
    return out;
  }

  // `{n}` is whatever the rule's own condition counted, which is why it means
  // the side total in a same-side rule and the list length in the others: the
  // number a reader wants is the one the rule fired on.
  function fillSay(template, values) {
    return String(template || "").replace(/\{(\w+)\}/g, (whole, key) =>
      Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : whole
    );
  }

  function evaluateAlert(rule, damage, panel, fired) {
    // `unless` is an else-branch written as data: the broad rule stays quiet
    // when the specific one already spoke. Depends on array order, which the
    // adapter format documents as precedence.
    if ((rule.unless || []).some((id) => fired.has(id))) return null;

    if (rule.measure) {
      const amount = Number(damage[rule.measure] || 0);
      if (!amount) return null;
      if (rule.at_least !== undefined && amount < rule.at_least) return null;
      const declared = (panel.measures || []).find((m) => m.key === rule.measure) || {};
      const currency =
        (declared.currency_key ? damage[declared.currency_key] : null) ||
        declared.default_currency ||
        "";
      return fillSay(rule.say, { n: amount, value: amount.toLocaleString(), currency });
    }

    const items = Array.isArray(damage[rule.state]) ? damage[rule.state] : [];
    if (!items.length) return null;

    if (rule.terms) {
      if (!items.some((item) => matchesAnyTerm(item, rule.terms))) return null;
      // A painted panel that was also replaced says nothing extra: the
      // replacement rule already fired and is the worse news.
      if (rule.absent_from) {
        const others = Array.isArray(damage[rule.absent_from]) ? damage[rule.absent_from] : [];
        if (others.some((item) => matchesAnyTerm(item, rule.terms))) return null;
      }
      return fillSay(rule.say, { n: items.length });
    }

    const perSide = sideCounts(items, panel.sides);
    if (rule.same_side_at_least !== undefined) {
      const worst = Math.max(0, ...Object.values(perSide));
      if (worst < rule.same_side_at_least) return null;
      return fillSay(rule.say, { n: worst, ...perSide });
    }
    if (rule.each_side_at_least !== undefined) {
      const values = Object.values(perSide);
      if (!values.length || values.some((v) => v < rule.each_side_at_least)) return null;
      return fillSay(rule.say, { n: items.length, ...perSide });
    }
    if (rule.at_least !== undefined) {
      if (items.length < rule.at_least) return null;
      return fillSay(rule.say, { n: items.length });
    }
    return null;
  }

  function buildCriticalAlerts(lm) {
    if (!lm) return [];
    const panel = lm.panel || {};
    const damage = lm.damage_info || {};
    const fired = new Set();
    const alerts = [];
    for (const rule of panel.alerts || []) {
      const said = evaluateAlert(rule, damage, panel, fired);
      if (!said) continue;
      if (rule.id) fired.add(rule.id);
      alerts.push(said);
    }
    return alerts;
  }

  function counts() {
    if (!state.result || !Array.isArray(state.result.claims)) {
      return { high: 0, medium: 0, low: 0, total: 0 };
    }
    const out = { high: 0, medium: 0, low: 0, total: state.result.claims.length };
    for (const r of state.result.claims) {
      if (r.severity === "high") out.high += 1;
      else if (r.severity === "medium") out.medium += 1;
      else if (r.severity === "low") out.low += 1;
    }
    return out;
  }

  // ─── Talking to the worker ────────────────────────────────────────────
  //
  // Whether this page is worth analysing is the installed packs' answer, and
  // the worker is the one holding it. The panel used to test for
  // one hardcoded host here, which meant installing a pack for a second listing
  // site changed nothing until someone edited this file. So it always asks,
  // and treats NO_ADAPTER as "quiet", not as a failure.

  // triggerIfMissing: when there is no cached result, fall back to kicking off
  // analysis (joins any in-flight background run via the background's
  // de-duplication) so the panel never gets stuck on the empty state.
  function requestCached({ triggerIfMissing = false } = {}) {
    chrome.runtime.sendMessage(
      { type: "GET_CACHED_RESULT", payload: { url: window.location.href } },
      (response) => {
        const missing =
          chrome.runtime.lastError || !response || !response.ok || !response.payload;
        if (missing) {
          if (triggerIfMissing && state.pipeline === "idle") {
            triggerAnalyze();
          }
          return;
        }
        applyEntry(response.payload);
      }
    );
  }

  function claimKeyOf(claim) {
    return `${claim.pack_id || ""}:${claim.claim_id || claim.title || ""}`;
  }

  // Apply entry helper
  function applyEntry(entry) {
    if (!entry) return;
    if (entry.listing || (entry.ok && entry.result)) {
      state.listingMeta = deriveListingMeta(entry);
    }
    if (entry.ok && entry.result) {
      // The same answer, re-answered (B152.4): what it did not have before is
      // new. A different answer starts with nothing marked.
      const before = state.result;
      if (before && before.lookup_id && before.lookup_id === entry.result.lookup_id) {
        const had = new Set((before.claims || []).map(claimKeyOf));
        const present = new Set((entry.result.claims || []).map(claimKeyOf));
        state.openIds = new Set([...state.openIds].filter(key => present.has(key)));
        for (const claim of entry.result.claims || []) {
          if (!had.has(claimKeyOf(claim))) state.freshKeys.add(claimKeyOf(claim));
        }
      } else {
        state.freshKeys = new Set();
        state.openIds = new Set();
        // A different saved answer gets its own card tree.
        if (claimsListEl) claimsListEl.replaceChildren();
      }
      // An answer means something read this page after all.
      state.noAdapter = false;
      state.unknownProduct = "";
      state.errorCode = null;
      state.result = entry.result;
      state.errorMsg = null;
      setPipeline("result");
    } else if (entry.ok === false) {
      // extension-5/extension-8 (B145 audit): the stored-result path (a page
      // reloaded onto a cached entry, or the panel reopened) used to ignore
      // `entry.code` entirely, so NO_ADAPTER rendered as a red error and
      // APP_NOT_RUNNING hid the settings button the live ANALYZE path already
      // knows to show. Both paths now read the same code.
      state.errorCode = entry.code || null;
      state.unknownProduct = "";
      state.learnable = Boolean(entry.learnable);
      if (entry.code === "UNKNOWN_PRODUCT") {
        state.noAdapter = false;
        state.unknownProduct = entry.productName || document.title || "";
        setPipeline("idle");
      } else if (entry.code === "NO_ADAPTER") {
        state.noAdapter = true;
        state.hostKnown = Boolean(entry.hostKnown);
        setPipeline("idle");
      } else {
        state.noAdapter = false;
        state.errorMsg = entry.error || "Analysis failed.";
        setPipeline("error");
      }
    }
    if (state.mounted) renderBody();
    if (state.mounted) renderCounts();
  }

  // The reader's verdict on one claim. Sent to the app, which owns it —
  // nothing about ranking changes, because one reader's car is not a
  // refutation. What it buys is a queue of claims worth re-researching in the
  // reader's own words, which is the best signal this project can receive and
  // was previously being dropped on the floor.
  function markClaim(claim, verdict, cardEl) {
    if (!claim.claim_id || !claim.pack_id) return;
    const previous = state.marks.get(claim.claim_id);
    // Pressing the pressed one takes it back. Painted immediately and
    // reverted if the app disagrees: a verdict button that waits for a round
    // trip feels broken on a local app that answers in 3ms.
    const next = previous === verdict ? null : verdict;
    if (next) state.marks.set(claim.claim_id, next);
    else state.marks.delete(claim.claim_id);
    if (cardEl) markClaimCard(cardEl, next);

    chrome.runtime.sendMessage(
      {
        type: "MARK_CLAIM",
        payload: {
          pack_id: claim.pack_id,
          claim_id: claim.claim_id,
          subject_id: claim.subject_id || "",
          title: claim.title || "",
          verdict: next,
        },
      },
      (response) => {
        if (chrome.runtime.lastError || (response && !response.ok)) {
          if (previous) state.marks.set(claim.claim_id, previous);
          else state.marks.delete(claim.claim_id);
          if (cardEl) markClaimCard(cardEl, previous);
        }
      }
    );
  }

  /* Does the page this claim cites still say it?
   *
   * One press, on the card being read. The app does the reading — this panel
   * sends an address and nothing else, because a check whose quote came from
   * a browser would prove nothing at all.
   *
   * A `missing` verdict changes no ranking and hides no card. Pages get
   * rewritten, and Kriko has no authority to retract a claim; what this buys
   * the reader is knowing which of these sentences they can still go and read
   * for themselves.
   */
  function checkFacts(claim, cardEl) {
    if (!claim.claim_id || !claim.pack_id) return;
    if (state.checkingFacts.has(claim.claim_id)) return;
    state.checkingFacts.add(claim.claim_id);
    if (cardEl) factClaimCard(cardEl, state.facts.get(claim.claim_id), true);

    chrome.runtime.sendMessage(
      {
        type: "CHECK_FACTS",
        payload: { pack_id: claim.pack_id, claim_id: claim.claim_id },
      },
      (response) => {
        state.checkingFacts.delete(claim.claim_id);
        if (!chrome.runtime.lastError && response && response.ok && response.check) {
          state.facts.set(claim.claim_id, response.check);
        }
        // A failure leaves the card as it was. The claim and its sources are
        // on screen and the reader can open the link themselves, which is
        // what they did before this button existed — a panel-wide error over
        // a supplementary badge would be the tail wagging the dog.
        if (cardEl) factClaimCard(cardEl, state.facts.get(claim.claim_id), false);
      }
    );
  }

  /* A browser URL for a route the result did not come with.
   *
   * The panel is never told the app's address — the worker owns it, and owns
   * it in one place on purpose. But every answer carries `app_url` built from
   * that address, so the base can be read back off one rather than asking for
   * it and having two copies. Empty when there is no answer yet, which is the
   * honest result: `openInApp` still records the route, and a window opened
   * within its TTL picks it up.
   */
  function appUrlFor(route) {
    const known = (state.result && (state.result.app_url || "")) || "";
    const at = known.indexOf("/#/");
    return at > 0 ? `${known.slice(0, at)}/#/${route}` : "";
  }

  // Raise the desktop app on a route. Not a link: a page cannot bring a
  // native window to the front, and the link this replaced opened the report
  // in a second browser tab beside the app the reader already had running.
  function openInApp(route, fallbackUrl) {
    chrome.runtime.sendMessage(
      { type: "OPEN_IN_APP", payload: { route, fallbackUrl } },
      (response) => {
        // The app raising itself is the feedback, and a tab opening is the
        // feedback when there is no app to raise — so success needs no toast
        // and this panel grows no notification system for it.
        //
        // Two kinds of failure reach here, and only one is for the reader.
        // APP_NOT_RUNNING is the engine simply not being up — that is not a
        // defect, it is the current state of the world, and the reader
        // should see it in place rather than get a silent no-op. Anything
        // else means this extension built a route the app refused, which is
        // a defect in *our* code and belongs where a developer will find it.
        if (chrome.runtime.lastError || (response && !response.ok)) {
          const message = chrome.runtime.lastError?.message || response?.error;
          if (["APP_NOT_RUNNING", "APP_NOT_RESPONDING", "DESKTOP_NOT_CONNECTED"].includes(response?.code)) {
            showFooterStatus(message);
          } else {
            console.warn("Kriko: could not open the app on", route, message);
          }
        }
      }
    );
  }

  // A one-line status shown next to the footer's app buttons, for a failure
  // the reader caused nothing wrong to see (the app just isn't running).
  // Cleared after a few seconds so it doesn't linger past the next action.
  let footerStatusTimer = null;
  function showFooterStatus(message) {
    if (!footerEl) return;
    let statusEl = footerEl.querySelector(".lite-footer-status");
    if (!statusEl) {
      statusEl = document.createElement("span");
      statusEl.className = "lite-footer-status";
      footerEl.append(statusEl);
    }
    statusEl.textContent = message;
    clearTimeout(footerStatusTimer);
    footerStatusTimer = setTimeout(() => {
      statusEl.remove();
    }, 4000);
  }

  // Which plane this installation is configured for, and what it costs.
  // Asked once, lazily — a gap that is never shown never needs an answer —
  // and cached, since the plane cannot change mid-session without a restart
  // this panel would also lose its mount on.
  function requestResearchPlane() {
    if (state.researchPlaneRequested) return;
    state.researchPlaneRequested = true;
    chrome.runtime.sendMessage({ type: "RESEARCH_PLANE" }, (response) => {
      if (chrome.runtime.lastError || !response || !response.ok) {
        state.researchPlaneError = response?.error || "Cannot read research costs. Open Kriko and retry.";
        renderResearch();
        return;
      }
      state.researchPlane = response.plane || null;
      state.researchPlaneError = "";
      renderResearch();
      // Skip the redraw while a run is in flight: renderGaps rebuilds the gap
      // card from scratch, and rebuilding out from under an active poll would
      // orphan the button pollResearchJob is updating by direct reference.
      // The cost line was already correct when that run started; there is
      // nothing here worth losing progress text for.
      if (!state.researching) renderGaps();
    });
  }

  /* The agents the reader may use from here. The list is the app's (ready and
   * runnable ones only); the pick is this panel's own and is remembered, so the
   * reader can use one agent for lookups in the browser and another in the app
   * without touching Settings. */
  const AGENT_KEY = "kriko.panelAgent";

  function requestAgents() {
    if (state.agentsRequested) return;
    state.agentsRequested = true;
    const ask = () => chrome.runtime.sendMessage({ type: "AGENTS" }, (response) => {
      if (chrome.runtime.lastError || !response || !response.ok) return;
      state.agents = Array.isArray(response.agents) ? response.agents : [];
      state.agentChosen = String(response.chosen || "");
      if (state.agentPick && !state.agents.some((one) => one.id === state.agentPick)) state.agentPick = "";
      renderResearch();
      renderVerdict();
    });
    try {
      chrome.storage?.local?.get?.([AGENT_KEY], (bag) => {
        void chrome.runtime.lastError;
        state.agentPick = typeof bag?.[AGENT_KEY] === "string" ? bag[AGENT_KEY] : "";
        ask();
      });
    } catch (_) {
      ask();
    }
  }

  /* The agent a press would use: the one picked here, else the app's own. */
  function currentAgent() {
    const list = state.agents || [];
    if (list.some((one) => one.id === state.agentPick)) return state.agentPick;
    return list.some((one) => one.id === state.agentChosen) ? state.agentChosen : "";
  }

  function pickedAgent() {
    return (state.agents || []).find((one) => one.id === currentAgent()) || null;
  }

  function agentRowMarkup(busy) {
    const list = state.agents || [];
    if (list.length < 2) return "";   // nothing to choose between
    const now = currentAgent();
    return `<label class="lite-agent-row"><span>Agent</span>
      <select class="lite-agent-select" aria-label="Agent for this panel" ${busy || state.learning ? "disabled" : ""}>
        ${list.map((one) => `<option value="${escapeHtml(one.id)}"${one.id === now ? " selected" : ""}>${escapeHtml(one.label)}</option>`).join("")}
      </select></label>`;
  }

  /* What the card's head does not already say: the cost is there, the wait is not. */
  function learnWaitWords() {
    return pickedAgent()?.kind === "cli" ? "Takes a few minutes." : "";
  }

  function lessonWords(lesson) {
    if (!lesson) return "";
    if (!lesson.learned) return lesson.reason || "Nothing was learned from this page.";
    const count = Array.isArray(lesson.grabs) ? lesson.grabs.length : 0;
    const site = lesson.host || "this site";
    return count
      ? `Learned ${site}. It takes ${count} thing${count === 1 ? "" : "s"} from this page:`
      : `Learned ${site}.`;
  }

  function learnMarkup() {
    const lesson = state.lesson;
    const grabs = lesson?.learned && Array.isArray(lesson.grabs) ? lesson.grabs : [];
    return `<div class="lite-learn">
      <div class="lite-learn-row">
        <button type="button" class="lite-learn-btn" ${state.learning ? "disabled" : ""}
          title="An agent goes through this page and learns what to take from it">${
          state.learning ? "Learning…" : lesson?.learned ? "Learn again" : "Learn this page"}</button>
        <small>${escapeHtml(learnWaitWords())}</small>
      </div>
      <p class="lite-learn-status" role="status"></p>
      ${grabs.length ? `<ul class="lite-learn-grabs">${grabs.map((one) =>
        `<li><span>${escapeHtml(one.as)}</span><strong>${escapeHtml(one.value)}</strong></li>`).join("")}</ul>` : ""}
    </div>`;
  }

  // Every learn card on screen: the research card has one and so does the
  // card a site nothing reads gets, and either may be the one being watched.
  function paintLearn(slot) {
    for (const line of slot.querySelectorAll(".lite-learn-status")) {
      line.textContent = state.learning ? state.learnMessage : lessonWords(state.lesson);
      line.dataset.ok = state.lesson?.learned && !state.learning ? "1" : "0";
    }
  }

  /* The learn button and the agent picker of one card. Wired where the card is
   * built, because both cards are rebuilt whenever the panel is painted. */
  function wireLearn(root) {
    root.querySelector(".lite-learn-btn")?.addEventListener("click", learnPage);
    root.querySelector(".lite-agent-select")?.addEventListener("change", (event) => {
      state.agentPick = event.target.value;
      try { chrome.storage?.local?.set?.({ [AGENT_KEY]: state.agentPick }, () => void chrome.runtime.lastError); } catch (_) {}
      renderLearnSurfaces();
    });
  }

  /* Every place a learn card can be on screen. The card of an unreadable page
   * lives in the claims list, with the error it answers. */
  function renderLearnSurfaces() {
    renderResearch();
    renderVerdict();
    if (state.pipeline === "error") renderClaimsList();
  }

  /* Learn this page. The app's local model answers at once; another agent is a
   * job, followed here like a research run. Either way the page itself is read
   * in this tab, because it is already rendered and past the site's bot check. */
  function learnPage() {
    if (state.learning) return;
    state.learning = true;
    state.lesson = null;
    state.learnMessage = "Reading this page…";
    state.learnStartedAt = Date.now();
    requestAgents();
    renderLearnSurfaces();
    chrome.runtime.sendMessage({ type: "LEARN_PAGE", payload: { agent: currentAgent() } }, (response) => {
      if (chrome.runtime.lastError || !response?.ok) {
        finishLearn({ learned: false, reason: response?.error || "Could not reach Kriko. Open the app and try again." });
        return;
      }
      const lesson = response.lesson || {};
      if (lesson.mode === "agent" && lesson.job_id) {
        state.learnMessage = "Your agent is reading the page…";
        renderLearnSurfaces();
        pollLearnJob(lesson);
        return;
      }
      finishLearn(lesson);
    });
  }

  function pollLearnJob(lesson) {
    chrome.runtime.sendMessage({ type: "JOB_STATUS", payload: { job_id: lesson.job_id } }, (response) => {
      if (!state.learning) return;
      if (chrome.runtime.lastError || !response?.ok || !response.job) {
        state.learnMessage = "Cannot check progress. Open the app to follow it.";
        renderLearnSurfaces();
        setTimeout(() => pollLearnJob(lesson), 3000);
        return;
      }
      const job = response.job;
      const done = job.done || ["succeeded", "cancelled", "failed", "interrupted"].includes(job.state);
      if (!done) {
        state.learnMessage = `${job.message || "Reading the page"} · ${elapsedWords(state.learnStartedAt)}`;
        paintLearn(bodyEl);
        setTimeout(() => pollLearnJob(lesson), 1500);
        return;
      }
      const learned = job.state === "succeeded";
      // What the agent's adapter reads off this page, as the app checked it.
      const reading = job.result?.reading || {};
      const grabs = ["identity", "context"].flatMap((kind) => Object.entries(reading[kind] || {})
        .map(([as, value]) => ({ as, value: String(value), kind })));
      finishLearn({
        ...lesson, learned, grabs,
        reason: learned ? "" : (job.error || job.message || `Learning ${job.state}.`),
      });
    });
  }

  function finishLearn(lesson) {
    state.learning = false;
    state.lesson = lesson;
    // The title the page gave is a search page's title; the name the lesson
    // found is the product. Swapped in only while the name box still holds the
    // title, never over something the reader typed.
    const name = String(lesson.name || "").trim();
    const held = String(state.researchName || "").trim().toLowerCase();
    if (name && !state.researching && !state.researchTarget
        && (!held || held === String(document.title || "").trim().toLowerCase()
          || held.startsWith(name.toLowerCase()))) {
      state.researchName = name;
    }
    renderLearnSurfaces();
    if (!lesson.learned) return;
    // A page that is readable now may have a product Kriko knows.
    const unread = state.errorCode === "SCRAPE_FAILED";
    if ((state.noAdapter || state.unknownProduct || unread) && state.pipeline !== "result") {
      // The page was one nothing read, and now something does. The worker
      // takes the new reading in before the page is asked about again, or it
      // would be told "no adapter" from the list it already holds.
      chrome.runtime.sendMessage({ type: "KRIKO_SYNC_SITES" }, () => {
        void chrome.runtime.lastError;
        state.noAdapter = false;
        state.errorCode = null;
        state.learnable = false;
        triggerAnalyze(true);
      });
      return;
    }
    knowledgeMoved();
  }

  // The sentence a reader sees before the button does anything at all. Named
  // *before* the click, not after: the whole point of asking the plane first
  // is that "this spends money" cannot be information the reader gets from
  // the bill.
  function costLine() {
    const plane = state.researchPlane;
    if (!plane) return "";
    const picked = pickedAgent();
    if (picked?.kind === "local") return "Free · on this computer";
    if (picked?.kind === "cli") return "Free · your coding agent";
    if (picked?.kind === "api") {
      const cap = Number(plane.budget_usd || 0);
      return cap > 0 ? `Capped at $${cap.toFixed(2)} of your API keys.` : "Billed to your API keys.";
    }
    if (plane.backend === "api" || plane.cost_basis === "per_token") {
      const cap = Number(plane.budget_usd || 0);
      return cap > 0
        ? `Capped at $${cap.toFixed(2)} of your API keys.`
        : "Billed to your API keys.";
    }
    if (plane.backend === "local") {
      return "Free · on this computer";
    }
    return "Free · your coding agent";
  }

  // Nothing known about a subject the packs *do* recognise. That is the one
  // emptiness worth a button: the gap is identified, so filling it is a job
  // the app can start rather than a shrug.
  function researchSubject(subject) {
    if (state.researching) {
      state.researchOpen = true;
      renderResearch();
      return;
    }
    state.researchTarget = subject?.subject_id ? subject : null;
    // A page's `<title>` is a search results page's: the shop rides along. The
    // part before the first bar is the product; the engine takes off the rest.
    const nextName = subject?.label || state.searchQuery || state.listingMeta?.identity_line
      || state.listingMeta?.title || String(document.title || "").split(" | ")[0] || "";
    if (nextName !== state.researchName) {
      state.researchQuick = null;
      state.researchQuickJob = null;
    }
    state.researchName = nextName;
    state.researchContext = "";
    state.researchOpen = true;
    state.researchJob = null;
    state.researchEmpty = null;
    state.researchState = "";
    state.researchMessage = "";
    requestResearchPlane();
    requestAgents();
    renderResearch();
  }

  /* One button (B148). A name the packs know is researched into them; one
   * they do not gets a quick look answered here in a minute or two, saved on
   * its own; "Add to a pack" files it into one later. The reader used to choose between two
   * buttons whose difference they had no way to know. */
  function startResearch() {
    if (state.researching || !state.researchPlane) return;
    const subject_id = state.researchTarget?.subject_id;
    const q = [state.researchName.trim(), state.researchContext.trim()].filter(Boolean).join(" · ");
    if (!subject_id && !q) return;
    if (state.researchQuick && String(state.researchQuick.product || "").trim() !== q) {
      state.researchQuick = null;
      state.researchQuickJob = null;
    }
    const cap = Number(state.researchPlane.budget_usd);
    state.researching = subject_id || q;
    state.researchState = "starting";
    state.researchEmpty = null;
    state.researchMessage = "Looking it up…";
    state.researchAnswers = {};
    state.researchTold = {};
    state.researchDraftAnswers = {};
    // Retain the last successful cards while refreshing, including failure.
    state.researchStartedAt = Date.now();
    state.researchRun = null;
    renderResearch();
    chrome.runtime.sendMessage({ type: "RESEARCH_PRODUCT", payload: {
      ...(subject_id ? { subject_id } : { q, allow_draft: true, url: location.href }),
      ...(state.agentPick && currentAgent() === state.agentPick ? { harness: state.agentPick } : {}),
      ...(cap > 0 ? { cap } : {}),
    } }, (response) => {
      if (chrome.runtime.lastError || !response?.ok || !response.job?.job_id) {
        state.researching = null;
        state.researchState = "failed";
        state.researchMessage = response?.error || "Could not start. Open Kriko and retry.";
        renderResearch();
        return;
      }
      state.researchJob = response.job;
      state.researchState = "queued";
      // A quick look is a run with stages from its first moment; anything
      // else says its own word until its log gives it some.
      state.researchRun = describeRun(response.job);
      state.researchMessage = response.job.kind === "quick_look"
        ? `${state.researchRun.headline}\u2026` : "Queued";
      renderResearch();
      pollResearchJob(response.job.job_id);
    });
  }

  /* The quick look finished — well or not. Keep what it found, then follow
   * the deeper run it started beside, so the panel keeps saying what is
   * happening rather than ending on "done" while the real work goes on. */
  function quickLookDone(job) {
    const result = job.result || {};
    if (job.state !== "succeeded") {
      state.researching = null;
      state.researchMessage = job.error || job.message || "The quick look did not finish. Retry below.";
      renderResearch();
      return;
    }
    state.researchEmpty = null;
    state.researchQuick = {
      job_id: job.job_id || state.researchJob?.job_id || "",
      product: result.product || state.researchName,
      assumed: result.assumed || "",
      specs: Array.isArray(result.specs) ? result.specs : [],
      risks: Array.isArray(result.risks) ? result.risks : [],
      dropped: Number(result.dropped) || 0,
      coverage: result.coverage || result.telemetry?.coverage || null,
      diagnostic: result.diagnostic || {},
      listing: result.listing || {},
      evidence_pages: Array.isArray(result.evidence_pages) ? result.evidence_pages : [],
    };
    const deepen = result.deepen_job_id || state.researchJob?.deepen_job_id;
    const found = state.researchQuick.risks.length;
    const said = found
      ? `${found} thing${found === 1 ? "" : "s"} to know.`
      : "Nothing sourced found.";
    if (!deepen) {
      // A quick look is not a pack: it is saved as it is, and joins a pack
      // only when the reader presses "Add to a pack".
      state.researching = null;
      state.researchQuickJob = job.job_id || state.researchJob?.job_id || null;
      state.researchMessage = said;
      renderResearch();
      return;
    }
    state.researchJob = { job_id: deepen, kind: "pack_author" };
    state.researchState = "queued";
    state.researchMessage = `${said} Digging deeper…`;
    renderResearch();
    pollResearchJob(deepen);
  }

  /* The run's question, answered with one click (B147).
   *
   * It used to reach the reader as a JSON dump in the app's log. A live run
   * hears the answer now, through the same reply pipe as the app's box; a run
   * that already ended is started again with the answer applied, and the
   * panel follows the new run the way it followed the first. */
  function answerQuestion(question, option) {
    const job = state.researchJob;
    if (!job?.job_id) return;
    state.researchAnswers = { ...state.researchAnswers, [question.id]: option };
    if (state.researching) {
      state.researchTold = { ...state.researchTold, [question.id]: "Telling it..." };
      renderResearch();
      chrome.runtime.sendMessage({ type: "JOB_SAY", payload: {
        job_id: job.job_id, text: `Answer to "${question.ask}": ${option}`,
      } }, (response) => {
        const heard = !chrome.runtime.lastError && response?.ok && response.delivered;
        state.researchTold = { ...state.researchTold,
          [question.id]: heard ? "It heard you." : "Not delivered. The run may have ended." };
        renderResearch();
      });
      return;
    }
    const answers = state.researchAnswers;
    state.researching = job.job_id;
    state.researchState = "starting";
    state.researchMessage = "Running again with your answer...";
    state.researchStartedAt = Date.now();
    state.researchRun = null;
    renderResearch();
    chrome.runtime.sendMessage({ type: "JOB_RETRY", payload: { job_id: job.job_id, answers } },
      (response) => {
        if (chrome.runtime.lastError || !response?.ok || !response.job_id) {
          state.researching = null;
          state.researchState = "failed";
          state.researchMessage = response?.error || "Could not run it again. Open Kriko and retry.";
          renderResearch();
          return;
        }
        state.researchJob = { job_id: response.job_id, kind: response.kind || job.kind };
        state.researchAnswers = {};
        state.researchTold = {};
        state.researchState = "queued";
        state.researchMessage = "Queued";
        renderResearch();
        pollResearchJob(response.job_id);
      });
  }

  function cancelResearch() {
    const jobId = state.researchJob?.job_id;
    if (!jobId || !state.researching || state.cancelling) return;
    state.cancelling = true;
    renderResearch();
    chrome.runtime.sendMessage({ type: "CANCEL_JOB", payload: { job_id: jobId } }, (response) => {
      if (state.researchJob?.job_id !== jobId || !state.researching) return;
      if (chrome.runtime.lastError || !response?.ok) {
        state.cancelling = false;
        state.researchMessage = response?.error || "Could not cancel. Try again.";
      } else if (response.job?.state === "cancelled") {
        state.researching = null;
        state.cancelling = false;
        state.researchState = "cancelled";
        state.researchMessage = "Research cancelled.";
      } else {
        state.researchMessage = "Cancellation requested…";
      }
      renderResearch();
    });
  }

  /* ─── The no-issue card ────────────────────────────────────────────────
   *
   * Both a quick look that kept nothing and a deep run that kept nothing show
   * the same card. It states the coverage figures the run reported, links the
   * pages it actually read (the panel's own source list, filled after the slot
   * is painted), and — when a saved quick look exists — offers the quick
   * look's follow-up input right there, so the reader can ask the agent about
   * the product instead of leaving for the app. */
  function coverageWords(coverage) {
    if (!coverage) return "";
    // The run's own tally, as `run_progress.js` words it: pages read out of
    // pages tried first, then what came of them.
    const { pages, rest } = coverageSummary(coverage);
    return [pages, ...rest].join(" \u00b7 ");
  }

  function noIssueCardMarkup(empty) {
    const stats = coverageWords(empty.coverage);
    const statChips = stats
      ? `<ul class="lite-noissue-stats">${stats.split(" · ").map((part) => {
        const [n, ...rest] = part.split(" ");
        return `<li><b>${escapeHtml(n)}</b> ${escapeHtml(rest.join(" "))}</li>`;
      }).join("")}</ul>`
      : "";
    return `<section class="lite-noissue" data-empty="${escapeHtml(empty.kind || "quick")}">
      <div class="lite-noissue-head">
        <span class="lite-noissue-icon">${iconSvg("searchOff", { size: 18 })}</span>
        <div>
          <h3 class="lite-noissue-title">${escapeHtml(empty.title || "No sourced issues found")}</h3>
          <p class="lite-noissue-note">${escapeHtml(empty.note
            || "Nothing found in the pages read. Not proof there is no issue.")}</p>
        </div>
      </div>
      ${statChips}
      <div class="lite-quick-specs"></div>
      <details class="lite-quick-sources" ${state.quickSourcesOpen ? "open" : ""}>
        <summary>Pages read</summary>
        <div class="lite-quick-source-list"></div>
      </details>
    </section>`;
  }

  function renderResearch() {
    const slot = bodyEl?.querySelector(".lite-research-slot");
    if (!slot) return;
    if (!state.researchOpen) { slot.innerHTML = ""; slot._researchMarkup = null; slot._shown = false; return; }
    const busy = Boolean(state.researching);
    const target = state.researchTarget;
    const cost = costLine();
    const asked = (state.researchJob?.attention?.questions
      || state.researchJob?.result?.questions || []).filter((q) => q && q.id);
    const editing = slot.querySelector(".lite-question-input:focus");
    const editingId = editing?.dataset.id;
    const selection = editing ? [editing.selectionStart, editing.selectionEnd] : null;
    const quickCoverage = state.researchQuick?.coverage;
    const quickIsEmpty = Boolean(state.researchQuick
      && !state.researchQuick.risks?.length && !state.researchQuick.specs?.length);
    const rejectionReasons = quickCoverage?.rejection_reasons;
    const rejectionSummary = rejectionReasons && typeof rejectionReasons === "object"
      ? Object.entries(rejectionReasons)
        .filter(([, count]) => Number(count) > 0)
        .sort((a, b) => Number(b[1]) - Number(a[1]))
        .slice(0, 3)
        .map(([reason, count]) => `${reason.replaceAll("_", " ")} (${count})`)
        .join(", ")
      : "";
    // A quick look that kept nothing and a deep run that kept nothing show the
    // same card.
    const emptyCard = quickIsEmpty
      ? {
        kind: "quick",
        title: "No sourced issues kept",
        note: "Nothing found in the pages read. Not proof there is no issue.",
        coverage: quickCoverage,
        outcome: state.researchQuick?.diagnostic?.message || "",
      }
      : state.researchEmpty;
    const markup = `
      <section class="lite-research">
        <div class="lite-research-head">
          <strong>Research</strong>
          <span class="lite-gap-cost">${escapeHtml(cost || state.researchPlaneError || "Checking costs…")}</span>
        </div>
        ${agentRowMarkup(busy)}
        ${target ? `<p class="lite-research-target">${escapeHtml(target.label || target.subject_id)}</p>` : `
          <input class="lite-research-name" maxlength="350" placeholder="Product name" aria-label="Product name" ${busy ? "disabled" : ""} />
          <div class="lite-fold"><div class="lite-fold-in">
            <textarea class="lite-research-context" maxlength="140" placeholder="Context (optional)" aria-label="Context" ${busy ? "disabled" : ""}></textarea>
          </div></div>
          <button type="button" class="lite-more lite-context-toggle" aria-expanded="false">Add context</button>`}
        <p class="lite-research-status" role="status"></p>
        ${quickCoverage && !quickIsEmpty ? `<p class="lite-quick-coverage" role="status">${escapeHtml(
          coverageWords(quickCoverage)
          + (rejectionSummary ? ` · reasons: ${rejectionSummary}` : ""))}</p>` : ""}
        <div class="lite-run" hidden>
          <div class="lite-run-bar" role="progressbar" aria-label="Research progress" aria-valuemin="1" aria-valuemax="4">
            <span class="lite-run-seg"></span><span class="lite-run-seg"></span><span class="lite-run-seg"></span><span class="lite-run-seg"></span>
          </div>
          <p class="lite-run-facts"></p>
        </div>
        ${emptyCard ? noIssueCardMarkup(emptyCard) : ""}
        ${state.researchQuick && !quickIsEmpty ? `<div class="lite-quick">
          ${state.researchQuick.assumed ? `<p class="lite-quick-assumed">Taken as: ${renderRichText(state.researchQuick.assumed)}</p>` : ""}
          <div class="lite-quick-cards"></div>
          <div class="lite-quick-specs"></div>
          <details class="lite-quick-sources" ${state.quickSourcesOpen ? "open" : ""}>
            <summary>Sources</summary><div class="lite-quick-source-list"></div>
          </details>
        </div>` : ""}
        ${asked.length ? `<div class="lite-asked" aria-live="polite">
          <p class="lite-asked-lede"><span class="lite-asked-mark" aria-hidden="true">?</span>${busy
            ? "Your agent has a question. Pick an answer."
            : "Pick an answer to run it again."}</p>
          ${asked.map((q, qi) => `<fieldset class="lite-asked-q"><legend>${renderRichText(q.ask)}</legend>
            ${(q.options || []).length ? `<div class="lite-chips">${q.options.map((o, oi) => `
              <button type="button" class="lite-chip" data-q="${qi}" data-o="${oi}"
                aria-pressed="${state.researchAnswers[q.id] === o}">${renderRichText(o)}${
                o === q.default && !state.researchAnswers[q.id] ? ` <span class="lite-chip-note">its guess</span>` : ""}</button>`).join("")}</div>`
              : ""}
            <form class="lite-question-form" data-q="${qi}">
              <label>Your answer<input class="lite-question-input" data-id="${escapeHtml(q.id)}" maxlength="2000" /></label>
              <button type="submit" class="lite-chip">Send answer</button>
            </form>
            ${state.researchTold[q.id] ? `<p class="lite-told">${escapeHtml(state.researchTold[q.id])}</p>` : ""}
          </fieldset>`).join("")}
        </div>` : ""}
        ${learnMarkup()}
        <div class="lite-research-actions">
          ${!busy ? `<button type="button" class="lite-research-start" ${!state.researchPlane ? "disabled" : ""}>${state.researchJob ? "Run again" : "Research this product"}</button>` : ""}
          ${!busy && state.researchQuickJob ? `<button type="button" class="lite-research-pack">Add to a pack</button>` : ""}
          ${busy && state.researchJob ? `<button type="button" class="lite-research-cancel" ${state.cancelling ? "disabled" : ""}>${state.cancelling ? "Cancelling…" : "Cancel"}</button>` : ""}
          ${state.researchJob ? `<button type="button" class="lite-research-output">Open in Kriko</button>` : ""}
          ${state.researchPlaneError ? `<button type="button" class="lite-research-cost-retry">Retry cost check</button>` : ""}
        </div>
        <div class="lite-task-log-slot"></div>
      </section>`;
    // Progress-only polls should update the sentence, never re-create the
    // quick-look cards or the question the reader is typing an answer to.
    const signature = markup + JSON.stringify(state.researchQuick)
      + JSON.stringify(state.researchEmpty);
    if (slot._researchMarkup === signature) {
      paintLearn(slot);
      renderTaskLog(slot.querySelector(".lite-task-log-slot"), state.researchJob);
      slot.querySelector(".lite-research").dataset.state = state.researchState;
      slot.querySelector(".lite-research-status").textContent = state.researchMessage;
      paintRun(slot);
      const name = slot.querySelector(".lite-research-name");
      if (name && name.value !== state.researchName) name.value = state.researchName;
      const context = slot.querySelector(".lite-research-context");
      if (context && context.value !== state.researchContext) context.value = state.researchContext;
      slot.querySelectorAll(".lite-question-input").forEach(input => {
        const value = state.researchDraftAnswers[input.dataset.id] || "";
        if (input.value !== value) input.value = value;
      });
      return;
    }
    slot._researchMarkup = signature;
    slot.innerHTML = markup;
    // The card drops in once, when it is opened, and not again each time a
    // poll rebuilds it. Context stays folded until it is asked for (or has
    // words in it already); the fold eases open rather than snapping.
    const card = slot.querySelector(".lite-research");
    if (!slot._shown) { slot._shown = true; card.dataset.enter = "1"; }
    const fold = slot.querySelector(".lite-fold");
    const foldToggle = slot.querySelector(".lite-context-toggle");
    if (fold && foldToggle) {
      const setFold = (open, focus) => {
        state.researchContextOpen = open;
        fold.dataset.open = open ? "1" : "0";
        foldToggle.setAttribute("aria-expanded", String(open));
        foldToggle.textContent = open ? "Hide context" : "Add context";
        if (open && focus) setTimeout(() => fold.querySelector("textarea")?.focus({ preventScroll: true }), 120);
      };
      setFold(Boolean(state.researchContext) || Boolean(state.researchContextOpen), false);
      foldToggle.addEventListener("click", () => setFold(fold.dataset.open !== "1", true));
    }
    paintLearn(slot);
    wireLearn(slot);
    renderTaskLog(slot.querySelector(".lite-task-log-slot"), state.researchJob);
    slot.querySelector(".lite-research").dataset.state = state.researchState;
    slot.querySelector(".lite-research-status").textContent = state.researchMessage;
    paintRun(slot);
    const name = slot.querySelector(".lite-research-name");
    if (name) {
      name.value = state.researchName;
      name.addEventListener("input", () => { state.researchName = name.value; });
    }
    const context = slot.querySelector(".lite-research-context");
    if (context) {
      context.value = state.researchContext;
      context.addEventListener("input", () => { state.researchContext = context.value; });
    }
    slot.querySelector(".lite-research-start")?.addEventListener("click", () => startResearch());
    slot.querySelector(".lite-research-pack")?.addEventListener("click", addQuickToPack);
    const quickCards = slot.querySelector(".lite-quick-cards");
    const sourceList = slot.querySelector(".lite-quick-source-list");
    const sources = new Map();
    const specsSlot = slot.querySelector(".lite-quick-specs");
    for (const spec of state.researchQuick?.specs || []) {
      const item = document.createElement("p");
      item.innerHTML = `${renderRichText(spec.name)}: ${renderRichText(spec.value)}`;
      specsSlot?.appendChild(item);
    }
    const listing = state.researchQuick?.listing || {};
    for (const [name, value] of Object.entries(listing.facts || {}).slice(0, 20)) {
      const item = document.createElement("p");
      item.textContent = `${name}: ${typeof value === "object" ? JSON.stringify(value) : value}`;
      specsSlot?.appendChild(item);
    }
    if (listing.description) {
      const item = document.createElement("p");
      item.textContent = String(listing.description).slice(0, 1200);
      specsSlot?.appendChild(item);
    }
    for (const page of state.researchQuick?.evidence_pages || []) {
      if (/^https?:\/\//i.test(page.url || "")) sources.set(page.url, page);
    }
    // A deep run that kept nothing carries its pages on the empty state, not
    // on a quick look.
    for (const page of state.researchEmpty?.evidence_pages || []) {
      if (/^https?:\/\//i.test(page.url || "")) sources.set(page.url, page);
    }
    if (/^https?:\/\//i.test(listing.url || "") && !sources.has(listing.url)) {
      sources.set(listing.url, { url: listing.url, domain: "Product listing" });
    }
    for (const risk of state.researchQuick?.risks || []) {
      for (const src of risk.sources || []) if (/^https?:\/\//i.test(src.url || "")) sources.set(src.url, src);
    }
    for (const spec of state.researchQuick?.specs || []) {
      if (/^https?:\/\//i.test(spec.url || "") && !sources.has(spec.url)) sources.set(spec.url, spec);
    }
    for (const src of sources.values()) {
      const item = document.createElement("p");
      const link = document.createElement("a");
      link.href = src.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.textContent = src.domain || src.url;
      const passage = src.quote || src.excerpt || "";
      item.append(link, document.createTextNode(passage ? ` · ${passage}` : ""));
      sourceList?.appendChild(item);
    }
    // A run whose pages produced no citable address says nothing about
    // sources rather than opening an empty drawer.
    if (sourceList && !sourceList.children.length) {
      sourceList.closest(".lite-quick-sources")?.remove();
    }
    slot.querySelector(".lite-quick-sources")?.addEventListener("toggle", event => {
      state.quickSourcesOpen = event.target.open;
    });
    (quickCards ? state.researchQuick.risks : []).forEach((risk, i) => {
      const wrap = document.createElement("div");
      wrap.className = "lite-claim-anim";
      wrap.style.animationDelay = (i * 70) + "ms";
      const card = renderClaimCard(risk, { open: false, compact: state.compact });
      card.querySelector(".lite-rc-toggle")?.addEventListener("click", () =>
        updateClaimCard(card, { open: card.dataset.open !== "1" }));
      // The page and quote a quick look stands on are drawn by the card itself:
      // a quick look is not a stored claim, so they are the only warrant it has.
      wrap.appendChild(card);
      quickCards.appendChild(wrap);
    });
    slot.querySelector(".lite-research-cancel")?.addEventListener("click", cancelResearch);
    slot.querySelectorAll(".lite-chip").forEach((chip) => chip.addEventListener("click", () => {
      if (!chip.hasAttribute("data-q")) return;
      const question = asked[Number(chip.dataset.q)];
      const option = question?.options?.[Number(chip.dataset.o)];
      if (question && option !== undefined) answerQuestion(question, option);
    }));
    slot.querySelectorAll(".lite-question-form").forEach(form => {
      const question = asked[Number(form.dataset.q)];
      const input = form.querySelector("input");
      input.value = state.researchDraftAnswers[question.id] || "";
      input.addEventListener("input", () => { state.researchDraftAnswers[question.id] = input.value; });
      form.addEventListener("submit", event => {
        event.preventDefault();
        if (input.value.trim()) answerQuestion(question, input.value.trim());
      });
      if (input.dataset.id === editingId) {
        input.focus({ preventScroll: true });
        input.setSelectionRange(...selection);
      }
    });
    slot.querySelector(".lite-research-output")?.addEventListener("click", () => {
      const route = `jobs/${encodeURIComponent(state.researchJob.job_id)}`;
      openInApp(route, appUrlFor(route));
    });
    slot.querySelector(".lite-research-cost-retry")?.addEventListener("click", () => {
      state.researchPlaneRequested = false;
      state.researchPlaneError = "";
      requestResearchPlane();
    });
  }

  /* The run in flight, as steps and counts (`run_progress.js`).
   *
   * Four segments, one per real stage, filled as the run's own log shows it
   * got there; the sentence beneath says what is happening now and, once a
   * page has been tried, how many were read out of how many. Nothing here is
   * a share of anything: a bar that fills smoothly while an agent sits on one
   * stage is the invention this replaces. */
  function paintRun(slot) {
    const box = slot?.querySelector(".lite-run");
    if (!box) return;
    const run = state.researching ? state.researchRun : null;
    if (!run || !run.staged || run.finished) { box.hidden = true; return; }
    box.hidden = false;
    const bar = box.querySelector(".lite-run-bar");
    bar.setAttribute("aria-valuenow", String(run.step));
    bar.setAttribute("aria-valuetext", run.spoken);
    const segs = bar.querySelectorAll(".lite-run-seg");
    run.stages.forEach((stage, i) => {
      if (!segs[i]) return;
      segs[i].dataset.state = stage.state;
      segs[i].title = stage.label;
    });
    box.querySelector(".lite-run-facts").textContent =
      [`Step ${run.step} of ${run.total}`, run.detail, run.pages].filter(Boolean).join(" \u00b7 ");
  }

  // Progress shown in the gap card itself — the panel stays put, and the
  // reader watches the run land without ever leaving the listing they were
  // reading. Polled rather than pushed: the panel has no open connection to
  // the app, and a job id is cheap to ask about again.
  /* An animated bar for a run in flight: filled to the job's own share, with
   * a moving sheen so a run that sits on one stage still reads as alive.
   * `null` hides it. The reader asked for bars, never a percentage figure. */
  function showProgress(bar, share) {
    if (!bar) return;
    if (share === null || share === undefined) { bar.hidden = true; return; }
    const value = Math.max(0, Math.min(1, Number(share) || 0));
    bar.hidden = false;
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    bar.setAttribute("aria-valuenow", String(Math.round(value * 100)));
    bar.style.setProperty("--p", `${Math.max(6, value * 100)}%`);
  }

  function renderTaskLog(slot, job) {
    if (!slot || !job?.job_id) return;
    if (!state.taskLogs.has(job.job_id)) state.taskLogs.set(job.job_id, { open: false, filter: "" });
    const view = state.taskLogs.get(job.job_id);
    if (slot.dataset.jobId !== job.job_id) {
      slot.dataset.jobId = job.job_id;
      // A bar that says how the run is (a light, a state, how long), opening
      // onto who ran it, what it said, and the log itself.
      slot.innerHTML = `<details class="lite-task-log">
        <summary><span class="lite-tl-led" aria-hidden="true"></span><span class="lite-tl-title">Task log</span>
          <span class="lite-tl-state"></span><span class="lite-tl-chev" aria-hidden="true"></span></summary>
        <div class="lite-tl-body">
          <p class="lite-tl-meta lite-task-log-meta"></p>
          <p class="lite-tl-msg"></p>
          <div class="lite-task-log-controls">
            <select aria-label="Log filter"><option value="">All lines</option><option value="search">Search</option>
              <option value="read">Sources</option><option value="fail">Problems</option></select>
            <button type="button">Copy log</button></div>
          <pre class="lite-task-log-text"></pre>
        </div></details>`;
      const details = slot.querySelector("details");
      details.open = view.open;
      details.addEventListener("toggle", () => { view.open = details.open; });
      const filter = slot.querySelector("select");
      filter.value = view.filter;
      filter.addEventListener("change", () => { view.filter = filter.value; renderTaskLog(slot, state.researchJob); });
      slot.querySelector("button").addEventListener("click", () => {
        const text = slot.querySelector("pre").textContent;
        window.navigator.clipboard?.writeText(text).catch(() => {});
      });
    }
    const agent = job.result?.agent;
    const started = Date.parse(job.created_at || "");
    const end = Date.parse(job.finished_at || "") || Date.now();
    const meta = slot.querySelector(".lite-task-log-meta");
    meta.replaceChildren(...[
      agent?.label || job.result?.harness || job.params?.harness || job.params?.backend || "Agent",
      agent?.model || job.result?.model || job.params?.model || "Model not reported",
      job.kind || "Task",
    ].map((text) => {
      const chip = document.createElement("span");
      chip.className = "lite-tl-chip";
      chip.textContent = text;
      return chip;
    }));
    slot.querySelector(".lite-tl-state").textContent = [
      job.state || "queued",
      Number.isFinite(started) ? `${Math.max(0, Math.round((end - started) / 1000))} s` : "",
    ].filter(Boolean).join(" · ");
    const message = slot.querySelector(".lite-tl-msg");
    message.textContent = job.message || "";
    message.title = job.message || "";
    slot.querySelector("details").dataset.state = job.state || "queued";
    slot.querySelector("details").dataset.active = String(!job.done && job.state === "running");
    const log = String(job.log || "").split("\n").filter(line => !view.filter || line.toLowerCase().includes(view.filter)).join("\n");
    const body = slot.querySelector("pre");
    const bottom = body.scrollHeight - body.scrollTop - body.clientHeight < 16;
    if (body.textContent !== log) {
      const position = body.scrollTop;
      body.textContent = log || (job.done ? "No log entries for this filter." : "Waiting for log entries.");
      body.scrollTop = bottom ? body.scrollHeight : position;
    }
  }

  /* "1m 12s" since the run started, from this panel's own clock. */
  function elapsedWords(since) {
    const seconds = Math.max(0, Math.round((Date.now() - (since || Date.now())) / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    return minutes < 60 ? `${minutes}m ${seconds % 60}s` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }

  /* The saved quick look, made part of a pack: one press, one more job, and
   * the panel follows it the way it followed the look. */
  function addQuickToPack() {
    const jobId = state.researchQuickJob;
    if (!jobId || state.researching) return;
    state.researching = "pack";
    state.researchStartedAt = Date.now();
    state.researchRun = null;
    state.researchState = "queued";
    state.researchMessage = "Adding the quick look to a pack…";
    renderResearch();
    chrome.runtime.sendMessage({ type: "QUICK_TO_PACK", payload: { job_id: jobId } }, (response) => {
      if (chrome.runtime.lastError || !response?.ok || !response.job?.job_id) {
        state.researching = null;
        state.researchState = "failed";
        state.researchMessage = response?.error || "Could not start. Open Kriko and retry.";
        renderResearch();
        return;
      }
      state.researchQuickJob = null;
      state.researchJob = { job_id: response.job.job_id, kind: "pack_author" };
      renderResearch();
      pollResearchJob(response.job.job_id);
    });
  }

  /* A finished research run that kept nothing. The panel used to say "Research
   * completed. Open the research job for findings." and stop there, so a run
   * that read sources and found nothing looked like one that produced cards.
   * The app's own outcome line already says what happened ("read 4 source(s),
   * none of them said anything keepable"); this states the one claim that
   * evidence supports. No data showing an issue is not the same as no issue,
   * so the sentence says that too. A brief the reader can open is never
   * called "no data": it may hold the findings. */
  /* True for a finished run that kept nothing and has no brief to open. */
  function keptNothing(result) {
    return Boolean(result) && Array.isArray(result.accepted)
      && !result.accepted.length && !result.brief;
  }

  function noKeptData(result) {
    const plain = "Research completed. Open the research job for findings.";
    if (!keptNothing(result)) return plain;
    const what = result.outcome || "nothing kept";
    return `No data found that shows an issue (${what}); not proof that there is no issue.`;
  }

  function pollResearchJob(jobId) {
    if (state.researchJob?.job_id !== jobId || !state.researching) return;
    chrome.runtime.sendMessage({ type: "JOB_STATUS", payload: { job_id: jobId } }, (response) => {
      if (state.researchJob?.job_id !== jobId || !state.researching) return;
      if (chrome.runtime.lastError || !response?.ok || !response.job) {
        state.researchMessage = "Cannot check progress. Open its output below or cancel.";
        renderResearch();
        setTimeout(() => pollResearchJob(jobId), 3000);
        return;
      }
      const job = response.job;
      state.researchJob = { ...state.researchJob, ...job, job_id: jobId };
      state.researchState = job.state;
      const done = job.done || ["succeeded", "cancelled", "failed", "interrupted"].includes(job.state);
      if (!done) {
        // The stage in words and how long it has run, never a percentage: an
        // agent job jumps from a tenth to done, so a number read as a stall.
        // The stage is the furthest one the run's own log has reached.
        state.researchRun = describeRun(job);
        state.researchMessage = `${state.researchRun.headline} \u00b7 ${elapsedWords(state.researchStartedAt)}`;
        renderResearch();
        setTimeout(() => pollResearchJob(jobId), 1000);
        return;
      }
      if (state.researchJob.kind === "quick_look" && job.state !== "cancelled") {
        quickLookDone(job);
        return;
      }
      state.researching = null;
      state.researchRun = null;
      state.cancelling = false;
      // The same card the quick look shows when it kept nothing: the run read
      // sources and kept no finding, and that absence is the finding.
      const emptied = job.state === "succeeded"
        && state.researchJob.kind !== "pack_author"
        && keptNothing(job.result);
      state.researchEmpty = emptied ? {
        kind: "deep",
        title: "No sourced issues kept",
        note: "Nothing found in the pages read. Not proof there is no issue.",
        coverage: job.result?.coverage || job.result?.telemetry?.coverage || null,
        evidence_pages: Array.isArray(job.result?.evidence_pages)
          ? job.result.evidence_pages
          : (Array.isArray(job.result?.sources) ? job.result.sources : []),
        outcome: job.result?.outcome || "",
      } : null;
      state.researchMessage = job.state === "cancelled" ? "Research cancelled."
        : job.state === "succeeded" ? (state.researchJob.kind === "pack_author"
          ? (job.result?.installed
            ? "Deeper research installed. Refreshing…"
            : `${state.researchQuick ? "Deeper research done. " : ""}Draft pack ready in Kriko; it could not install itself. Open it there.`)
          : job.result?.brief && !job.result?.documents
            ? "Brief ready. Open the research job."
            : noKeptData(job.result))
        : job.state === "interrupted" ? "Research interrupted by an app restart."
        : `Research failed. ${job.error || job.message || "Open the job for details."}`;
      const installed = job.state === "succeeded" && Boolean(job.result?.installed);
      if (installed) state.researchOpen = false;
      renderResearch();
      // B148: the pack the deep run installed is knowledge now, so the
      // listing is asked again and its cards arrive without a press.
      if (installed) triggerAnalyze(true);
    });
  }

  function triggerAnalyze(fresh) {
    setPipeline("analyzing");
    state.errorMsg = null;
    state.errorCode = null;
    // Cleared, not kept: the previous run's last stage was "Done", and a
    // fresh run that opens by saying it has finished is the old problem
    // wearing the new words.
    state.stage = null;
    renderBody();
    renderCounts();

    // background.js asks content.js for a fresh scrape, POSTs it to
    // /api/analyze, writes the full entry (result + the local-only listing
    // extras) to chrome.storage.session, and returns the result here.
    //
    // `fresh` (extension-3, B145 audit) is set only when the reader pressed
    // a "Refresh analysis" control themselves — not on the automatic run at
    // page load — and tells background.js to skip its own result cache
    // rather than hand back the same answer for up to 6 hours.
    chrome.runtime.sendMessage(
      { type: "ANALYZE", payload: { url: window.location.href, fresh: Boolean(fresh) } },
      (response) => {
        if (chrome.runtime.lastError) {
          setPipeline("error");
          state.errorCode = null;
          state.errorMsg = chrome.runtime.lastError.message || "Background unreachable.";
          renderBody();
          return;
        }
        if (response && !response.ok) {
          state.unknownProduct = "";
          state.learnable = Boolean(response.learnable);
          if (response.code === "UNKNOWN_PRODUCT") {
            // A product, read — just not one any installed pack knows. The
            // answer is the research button with its name already in it.
            setPipeline("idle");
            state.errorMsg = null;
            state.noAdapter = false;
            state.unknownProduct = response.productName || document.title || "";
            renderBody();
            return;
          }
          if (response.code === "NO_ADAPTER") {
            /* Nothing installed reads this site.
             *
             * Still not a red banner — a page Kriko cannot read is not an
             * error the reader made, and painting one over an ordinary web
             * page is how an extension teaches people to close it.
             *
             * But it is no longer *silence*, and that distinction is the whole
             * of §1.4. Silence is right for the automatic run at page load,
             * where the reader asked for nothing. It is wrong here: they
             * pressed a button called Analyze current page and nothing
             * happened, which is the dead end this release exists to remove.
             */
            setPipeline("idle");
            state.errorMsg = null;
            state.noAdapter = true;
            state.hostKnown = Boolean(response.hostKnown);
            renderBody();
            return;
          }
          setPipeline("error");
          // The code, not only the sentence. "Kriko is not running" has a
          // fix the reader can act on from here — every other failure is the
          // app's to report, and offering its settings would be a guess.
          state.errorCode = response.code || null;
          state.errorMsg = response.error || "Analysis failed.";
          renderBody();
          return;
        }
        // Apply the result the response already carries so the panel can never
        // get stuck on "analyzing" if the follow-up cache read races or the
        // service worker recycled the message port before onChanged fired.
        // requestCached() then enriches with the listing extras (damage,
        // equipment), which the response omits.
        if (response && response.ok && response.result) {
          applyEntry({ ok: true, result: response.result });
        }
        requestCached();
      }
    );
  }

  // Toolbar action sends TOGGLE_HOVER_LITE via chrome.tabs.sendMessage.
  chrome.runtime.onMessage.addListener((request) => {
    if (request?.type === "KRIKO_SESSION_UPDATE" && request.url === location.href) {
      if (request.stage) { state.stage = request.stage; renderStatus(); }
      if (request.result) applyEntry(request.result);
    }
    if (request && request.type === "TOGGLE_HOVER_LITE") {
      togglePanel();
    }
    if (request && request.type === "SHOW_GUARD") showGuard(request.result);
    if (request && request.type === "KRIKO_DUE_NUDGE") showDueNudge(request.purchase);
    // The worker opens the panel by itself only on a site Kriko already reads,
    // once per site per session, when it has an answer or a product to offer
    // to research. An unknown site is opened from the toolbar instead: a
    // panel over every shop the reader visits is what this replaced.
    if (request && request.type === "KRIKO_SHOW_PANEL" && !state.mounted) {
      openPanel();
    }
  });

  // runtime.sendMessage broadcasts only reach extension UI surfaces, not
  // content scripts, so we rely on chrome.storage.session instead: background
  // writes the result under STORAGE_KEY_PREFIX + url, and onChanged fires here
  // even when the panel is closed (state stays warm for the next open). This
  // requires background to grant content scripts session access via
  // setAccessLevel(TRUSTED_AND_UNTRUSTED_CONTEXTS) — without it this listener
  // never fires (issue #28).
  const storageKey = () => "kriko_result_" + window.location.href;
  const stageKey = () => "kriko_stage_" + window.location.href;
  chrome.storage.onChanged.addListener((changes, area) => {
    // The motion profile is a `local` setting shared with the options page:
    // changing it there while this panel is open has to reach the panel too,
    // or the two surfaces drift until the next reload.
    if (area === "local") {
      if (MOTION_KEY in changes) {
        const saved = changes[MOTION_KEY].newValue;
        state.motion = MOTION_PROFILES.includes(saved) ? saved : "";
        paintMotion();
      }
      if (GLASS_KEY in changes) {
        state.glass = changes[GLASS_KEY].newValue === "solid" ? "solid" : "";
        paintGlass();
      }
      return;
    }
    if (area !== "session") return;
    if (buyerKey() in changes) {
      const entry = changes[buyerKey()].newValue;
      if (entry && entry.ok) { state.buyer = entry.buyer; renderBuyer(); }
    }
    // The stage first: it is written before the result it narrates, and a
    // change event carrying both should not paint the answer and then the
    // sentence that says the answer is still coming.
    if (stageKey() in changes && changes[stageKey()].newValue) {
      state.stage = changes[stageKey()].newValue;
      renderStatus();
    }
    if (!(storageKey() in changes)) return;
    const next = changes[storageKey()].newValue;
    if (!next) return;
    applyEntry(next);
  });

  // ─── Mount / unmount with animation ───────────────────────────────────
  function mount() {
    if (state.mounted) return;
    state.mounted = true;
    state.closing = false;
    state.visible = true;

    loadFaces();
    hostEl = document.createElement(HOST_TAG);
    hostEl.style.cssText = "all:initial;";
    hostEl.dataset.pipeline = state.pipeline;
    document.documentElement.appendChild(hostEl);
    shadow = hostEl.attachShadow({ mode: "open" });

    const styleLink = document.createElement("link");
    styleLink.rel = "stylesheet";
    styleLink.href = chrome.runtime.getURL("hover_lite/hover_lite.css");
    shadow.appendChild(styleLink);

    panel = document.createElement("div");
    panel.className = "lite-panel";
    panel.dataset.side = state.side;
    panel.dataset.mounting = "1";
    // The panel is a region inside a page Kriko does not own, so it says what
    // it is. Without a name a screen reader reads the panel's contents as
    // loose text in the middle of somebody's listing, with nothing to say
    // where the listing stopped.
    panel.setAttribute("role", "complementary");
    panel.setAttribute("aria-label", "Kriko product knowledge");
    // The theme on the host before the first paint, so a stored light choice
    // never shows a dark frame. `state.theme` is empty until storage answers;
    // until then the system preference is what the stylesheet is already using.
    hostEl.dataset.theme = currentTheme();
    hostEl.dataset.motion = currentMotion();

    // Default position: dock to chosen side, full viewport height.
    const initialPos = state.pos || initialPosition();
    Object.assign(panel.style, {
      left: initialPos.left + "px",
      top: initialPos.top + "px",
      height: panelHeight() + "px",
    });

    panel.innerHTML = renderShell();
    shadow.appendChild(panel);

    // Cache element handles
    countsEl    = panel.querySelector(".lite-counts-slot");
    bodyEl      = panel.querySelector(".lite-body");
    statusEl    = panel.querySelector(".lite-status");
    ctaBtn      = panel.querySelector(".lite-cta");
    claimsHeadEl = panel.querySelector(".lite-claims-head-slot");
    claimsListEl = panel.querySelector(".lite-claims");
    densityBtn  = panel.querySelector(".lite-btn-density");
    searchBtn   = panel.querySelector(".lite-btn-search");
    closeBtn    = panel.querySelector(".lite-btn-close");
    footerEl    = panel.querySelector(".lite-footer");
    // The reader as a buyer: one listener each for every button and form in the
    // two slots, and the questions about earlier purchases asked once per mount.
    bodyEl.addEventListener("click", onBuyerClick);
    bodyEl.addEventListener("submit", onBuyerSubmit);
    loadBuyer();

    // Wire panel-level handlers. The ripple rides the same pointerdown the
    // drag does, and adds nothing when reduced motion is on.
    panel.addEventListener("pointerdown", rippleAt);
    panel.addEventListener("pointerdown", onPointerDown);
    panel.addEventListener("pointermove", onPointerMove);
    panel.addEventListener("pointerup", onPointerUp);
    panel.addEventListener("pointercancel", onPointerUp);

    /* Escape closes the panel, and the listener is on the panel rather than on
     * the document.
     *
     * A key handler on the document would take Escape away from the page: the
     * site's own modal, its inline edit, its search box all answer Escape, and
     * a panel the reader may not even be looking at has no business claiming
     * the key first. Every key event raised inside a shadow root reaches the
     * shadow's own tree, so this catches Escape whenever the reader's focus is
     * in the panel — which is the only moment the key is unambiguous. The
     * search field stops its own Escape on the way up, so the field closes
     * first and the panel closes on the next press. */
    panel.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.stopPropagation();
      if (state.searchOpen) closeSearch();
      else closePanel();
    });

    // A press of either control is the reader asking again on purpose, so
    // both bypass the cache; the automatic run at page load calls
    // triggerAnalyze() directly with no argument and gets the cache. The
    // exception is the primary button on a product nothing installed knows:
    // asking again cannot answer differently, so it researches instead.
    ctaBtn.addEventListener("click", () => (ctaIsResearch()
      ? researchSubject({ label: state.unknownProduct })
      : triggerAnalyze(true)));
    densityBtn.addEventListener("click", () => triggerAnalyze(true));
    searchBtn.addEventListener("click", () =>
      (state.searchOpen ? closeSearch() : openSearch()));
    closeBtn.addEventListener("click", closePanel);
    panel.querySelector(".lite-btn-theme").addEventListener("click", toggleTheme);
    paintTheme();
    readTheme();
    readMotion();
    readGlass();
    scheduleTour();
    panel.querySelector(".lite-find-product").addEventListener("click", () => {
      const product = (state.result?.subjects || []).find((one) => one.kind === "product");
      openSearch(product?.label || "");
    });
    panel.querySelector(".lite-research-product").addEventListener("click", () => {
      const subjects = (state.result?.subjects || []).filter((one) => one.kind === "product");
      researchSubject(subjects.length === 1 ? subjects[0] : null);
    });

    // Initial render
    renderBody();
    renderCounts();

    // Pull any cached result so a backgrounded auto-analysis shows instantly.
    // If nothing is cached yet on a listing page, kick off (or join) the run so
    // the panel shows progress instead of an empty state.
    requestCached({ triggerIfMissing: true });
    chrome.runtime.sendMessage({ type: "SAVED_QUICK_LOOK", payload: { url: location.href } }, response => {
      if (chrome.runtime.lastError || !response?.ok || !response.job || state.researching || state.researchJob) return;
      const job = response.job;
      state.researchName = job.params?.product || "";
      state.researchJob = { ...job, kind: "quick_look" };
      state.researchOpen = true;
      state.researchState = job.state;
      requestResearchPlane();
      quickLookDone(job);
    });

    // Only while the panel is on screen. A closed panel that kept asking
    // would be a request a second, forever, on every tab left open.
    stopLive();
    pollLive();

    // Strip the mount flag so future state changes don't re-trigger the entry
    // animation.
    setTimeout(() => { if (panel) delete panel.dataset.mounting; }, 280);
  }

  /* A short walk through the panel, once. The key is shared by every page the
   * panel mounts on, so a reader sees it on the first product page and never
   * again. The options page clears the key to show it again. Skip, Done and
   * Escape all count as seen; closing the panel half way does not, so the
   * walk comes back until the reader has made a choice about it. */
  const TOUR_KEY = "kriko.panelTour";
  const TOUR_STEPS = [
    { target: ".lite-header", title: "Kriko is on this page",
      text: "This panel shows what is known about the product here. Drag the top bar to move it." },
    // The big button is gone once there is a result, and the two small ones
    // take its place, so the step points at whichever the panel is showing.
    { target: ".lite-cta, .lite-product-actions", title: "Look the product up",
      text: "Search finds the product in your catalogs. If none knows it, research it with your agent." },
    { target: ".lite-btn-search", title: "Search",
      text: "Look up any product in your catalogs. You do not need to be on its page." },
    { target: ".lite-btn-theme", title: "Light or dark",
      text: "Pick the look you want. The app and this panel share it." },
    { target: ".lite-btn-close", title: "Close and open",
      text: "Close the panel here. Open it again from the Kriko button in the toolbar." },
  ];
  let tourEl = null;

  /** The first thing in `selectors` (a comma list) that the panel is showing. */
  function tourTarget(selectors) {
    for (const selector of selectors.split(",")) {
      const el = panel.querySelector(selector.trim());
      // The panel hides a control by `hidden` or by an inline `display: none`
      // on it or on the block around it.
      let shown = Boolean(el);
      for (let node = el; shown && node && node !== panel; node = node.parentElement) {
        if (node.hidden || node.style.display === "none") shown = false;
      }
      if (shown) return el;
    }
    return null;
  }

  function scheduleTour() {
    try {
      chrome.storage?.local?.get?.([TOUR_KEY], (bag) => {
        void chrome.runtime.lastError;
        if (bag?.[TOUR_KEY] === "done") return;
        setTimeout(() => { if (state.mounted && panel && !tourEl) openTour(); }, 1400);
      });
    } catch (_) {
      // A storage that will not answer means no tour. It is a nicety.
    }
  }

  function endTour(seen) {
    if (tourEl) { tourEl.remove(); tourEl = null; }
    if (!seen) return;
    try { chrome.storage?.local?.set?.({ [TOUR_KEY]: "done" }, () => void chrome.runtime.lastError); } catch (_) {}
  }

  function openTour() {
    let at = 0;
    tourEl = document.createElement("div");
    tourEl.className = "lite-tour";
    tourEl.setAttribute("role", "dialog");
    tourEl.setAttribute("aria-label", "Tour of the Kriko panel");
    panel.appendChild(tourEl);
    // The panel is a drag handle and the page behind it is not the reader's
    // business during the tour, so the overlay keeps both events to itself.
    tourEl.addEventListener("pointerdown", (event) => event.stopPropagation());
    tourEl.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { event.stopPropagation(); endTour(true); }
      else if (event.key === "ArrowRight") { event.stopPropagation(); show(Math.min(at + 1, TOUR_STEPS.length - 1)); }
      else if (event.key === "ArrowLeft") { event.stopPropagation(); show(Math.max(at - 1, 0)); }
    });

    function show(index) {
      at = index;
      const step = TOUR_STEPS[at];
      const last = at === TOUR_STEPS.length - 1;
      const target = tourTarget(step.target);
      const frame = panel.getBoundingClientRect();
      const box = target ? target.getBoundingClientRect() : null;
      const pad = 6;
      const spot = box
        ? { top: box.top - frame.top - pad, left: box.left - frame.left - pad, width: box.width + pad * 2, height: box.height + pad * 2 }
        : null;
      // Below the thing when it sits in the top half, above it otherwise.
      const below = !spot || spot.top + spot.height / 2 < frame.height / 2;
      tourEl.innerHTML = `
        <div class="lite-tour-spot"${spot ? ` style="top:${spot.top}px;left:${spot.left}px;width:${spot.width}px;height:${spot.height}px"` : " hidden"}></div>
        <div class="lite-tour-card" style="${below ? `top:${spot ? spot.top + spot.height + 12 : 80}px` : `bottom:${spot ? frame.height - spot.top + 12 : 80}px`}">
          <small class="lite-tour-count">${at + 1} of ${TOUR_STEPS.length}</small>
          <h2>${escapeHtml(step.title)}</h2>
          <p>${escapeHtml(step.text)}</p>
          <div class="lite-tour-actions">
            ${last ? "" : `<button type="button" class="lite-tour-skip">Skip</button>`}
            ${at > 0 ? `<button type="button" class="lite-tour-back">Back</button>` : ""}
            <button type="button" class="lite-tour-next">${last ? "Done" : "Next"}</button>
          </div>
        </div>`;
      tourEl.querySelector(".lite-tour-skip")?.addEventListener("click", () => endTour(true));
      tourEl.querySelector(".lite-tour-back")?.addEventListener("click", () => show(at - 1));
      const next = tourEl.querySelector(".lite-tour-next");
      next.addEventListener("click", () => (last ? endTour(true) : show(at + 1)));
      next.focus();
    }
    show(0);
  }

  function unmount() {
    tourEl = null;
    if (!hostEl) return;
    stopLive();
    try { hostEl.remove(); } catch (_) {}
    hostEl = shadow = panel = null;
    countsEl = bodyEl = statusEl = ctaBtn = null;
    claimsHeadEl = claimsListEl = densityBtn = closeBtn = searchBtn = null;
    footerEl = null;
  }

  function openPanel() {
    if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
    state.closing = false;
    if (!state.mounted) mount();
    state.visible = true;
  }
  function closePanel() {
    if (!state.mounted || state.closing) return;
    state.closing = true;
    state.visible = false;
    if (panel) panel.dataset.closing = "1";
    closeTimer = setTimeout(() => {
      state.mounted = false;
      state.closing = false;
      unmount();
      closeTimer = null;
    }, 200);
  }
  function togglePanel() {
    if (state.mounted && !state.closing) closePanel();
    else openPanel();
  }

  // ─── Layout helpers ───────────────────────────────────────────────────
  const PANEL_W = 400;
  const PAD_DOCK = 16;     // resting inset from viewport edges
  const PAD_DRAG = 10;     // minimum gap while dragging
  const EDGE_THRESHOLD = 200;
  const SNAP_PAD = 14;

  function panelHeight() {
    // extension-12 (B145 audit): a 520px floor made the panel taller than a
    // 620x520 window (the documented minimum), cutting the footer off — the
    // panel is meant to fit inside the viewport at a 16px inset, at any
    // height, and .lite-body already scrolls when there isn't room.
    return Math.max(240, window.innerHeight - PAD_DOCK * 2);
  }

  function initialPosition() {
    const width = Math.min(PANEL_W, Math.max(0, window.innerWidth - PAD_DOCK * 2));
    const left = state.side === "left" ? PAD_DOCK : (window.innerWidth - width - PAD_DOCK);
    return { left, top: PAD_DOCK };
  }

  function clampPos(left, top) {
    const rect = panel.getBoundingClientRect();
    const maxL = window.innerWidth  - rect.width  - PAD_DRAG;
    const maxT = window.innerHeight - rect.height - PAD_DRAG;
    return {
      left: Math.max(PAD_DRAG, Math.min(maxL, left)),
      top:  Math.max(PAD_DRAG, Math.min(maxT, top)),
    };
  }

  // ─── Drag ─────────────────────────────────────────────────────────────
  let dragStart = null;
  function onPointerDown(e) {
    if (!e.target.closest(".lite-header")) return;
    if (e.target.closest("button")) return;
    const rect = panel.getBoundingClientRect();
    dragStart = {
      x: e.clientX,
      y: e.clientY,
      left: rect.left,
      top: rect.top,
      cardW: rect.width,
      cardH: rect.height,
    };
    state.dragging = true;
    panel.dataset.dragging = "1";
    try { e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId); } catch (_) {}
    e.preventDefault();
  }
  function onPointerMove(e) {
    if (!state.dragging || !dragStart) return;
    const nl = dragStart.left + (e.clientX - dragStart.x);
    const nt = dragStart.top  + (e.clientY - dragStart.y);
    const c = clampPos(nl, nt);
    panel.style.left = c.left + "px";
    panel.style.top  = c.top  + "px";
    state.pos = c;
  }
  function onPointerUp() {
    if (!state.dragging) return;
    state.dragging = false;
    delete panel.dataset.dragging;

    // Magnetic edge snap on all four sides (200 px threshold).
    const rect = panel.getBoundingClientRect();
    const leftGap   = rect.left;
    const rightGap  = window.innerWidth  - (rect.left + rect.width);
    const topGap    = rect.top;
    const bottomGap = window.innerHeight - (rect.top  + rect.height);

    let targetLeft = null;
    let targetTop  = null;

    if (leftGap < EDGE_THRESHOLD && leftGap <= rightGap) {
      targetLeft = SNAP_PAD;
      state.side = "left";
    } else if (rightGap < EDGE_THRESHOLD) {
      targetLeft = window.innerWidth - rect.width - SNAP_PAD;
      state.side = "right";
    }

    if (topGap < EDGE_THRESHOLD && topGap <= bottomGap) {
      targetTop = SNAP_PAD;
    } else if (bottomGap < EDGE_THRESHOLD) {
      targetTop = window.innerHeight - rect.height - SNAP_PAD;
    }

    if (targetLeft !== null) {
      panel.style.left = targetLeft + "px";
      panel.dataset.side = state.side;
    }
    if (targetTop !== null) {
      panel.style.top = targetTop + "px";
    }
    state.pos = {
      left: targetLeft !== null ? targetLeft : rect.left,
      top:  targetTop  !== null ? targetTop  : rect.top,
    };
    dragStart = null;
  }

  // Keep panel inside viewport (and full-viewport height) on resize.
  window.addEventListener("resize", () => {
    if (!panel) return;
    panel.style.height = panelHeight() + "px";
    const rect = panel.getBoundingClientRect();
    const c = clampPos(rect.left, rect.top);
    panel.style.left = c.left + "px";
    panel.style.top  = c.top  + "px";
  });

  // ─── Rendering ────────────────────────────────────────────────────────
  function renderShell() {
    // The app's wordmark, inline: no file to fetch and no font to wait for.
    // The same drawing the desktop app's brand block carries.
    const wordmark = `<svg class="lite-wordmark" viewBox="0 0 302 100" role="img" aria-label="Kriko"><defs><clipPath id="kriko-cap"><rect x="-30" y="0" width="362" height="100"/></clipPath></defs><g transform="translate(18 0)"><g clip-path="url(#kriko-cap)" fill="none" stroke="currentColor" stroke-width="16" stroke-linejoin="miter" stroke-miterlimit="6"><path d="M8 17.0V83.0M8 50L54 -16M8 50L54 116"/></g><path d="M-12 50H44" stroke="currentColor" stroke-width="5" fill="none"/><rect x="-18" y="36" width="6" height="28" fill="currentColor"/><rect x="42" y="44" width="12" height="12" fill="currentColor"/></g><g transform="translate(84 0)" clip-path="url(#kriko-cap)" fill="none" stroke="currentColor" stroke-width="16" stroke-linejoin="miter" stroke-miterlimit="6"><path d="M8 102V8H36L48 20V38L36 50H8M28 50L52 108"/></g><g transform="translate(152 0)" fill="currentColor"><rect x="0" y="0" width="16" height="100"/></g><g transform="translate(180 0)" clip-path="url(#kriko-cap)" fill="none" stroke="currentColor" stroke-width="16" stroke-linejoin="miter" stroke-miterlimit="6"><path d="M8 -2V102M8 50L54 -16M8 50L54 116"/></g><g transform="translate(246 0)" fill="none" stroke="currentColor" stroke-width="16" stroke-linejoin="miter" stroke-miterlimit="6"><path d="M20 8H36L48 20V80L36 92H20L8 80V20Z"/></g></svg>`;

    // The header is the drag handle: the whole brand block moves the panel.
    //
    // `role="complementary"` with a name, so a screen reader announces that a
    // Kriko panel arrived on somebody else's page instead of reading its
    // contents as loose text. The status line is the one live region: the
    // stage sentence changes while a run is in flight, and nothing else in
    // the panel moves on its own.
    return `
      <header class="lite-header" title="Drag to move">
        <div class="lite-titlebox">
          ${wordmark}
          <div class="lite-subtitle">local product knowledge</div>
        </div>
        <button type="button" class="lite-iconbtn lite-btn-theme"
                title="Switch to light theme" aria-label="Switch to light theme"
                aria-pressed="false">
          ${iconSvg("sun", { size: 16, strokeWidth: 2 })}
        </button>
        <button type="button" class="lite-iconbtn lite-btn-density"
                title="Search again" aria-label="Search again">
          ${iconSvg("refresh", { size: 16, strokeWidth: 2 })}
        </button>
        <!-- Search sits in the header rather than behind a verdict, because
             wanting to look something up is not only what happens after a
             failed match: a reader comparing two of something is not standing
             on either page. -->
        <button type="button" class="lite-iconbtn lite-btn-search"
                title="Search the installed packs" aria-label="Search">
          ${iconSvg("search", { size: 16, strokeWidth: 2 })}
        </button>
        <button type="button" class="lite-iconbtn lite-btn-close"
                title="Close" aria-label="Close">
          ${iconSvg("x", { size: 16, strokeWidth: 2 })}
        </button>
      </header>

      <div class="lite-body">
        <div class="lite-counts-slot"></div>
        <div class="lite-listing-slot"></div>
        <div class="lite-buyer-slot"></div>
        <div class="lite-alerts-slot"></div>
        <div class="lite-cta-wrap">
          <button type="button" class="lite-cta">
            <span class="lite-cta-icon">${iconSvg("scan", { size: 15 })}</span>
            <span class="lite-cta-label">Search this product</span>
          </button>
          <p class="lite-status" role="status">${escapeHtml(IDLE_HINT)}</p>
        </div>
        <div class="lite-queue-slot"></div>
        <div class="lite-decide-slot"></div>
        <div class="lite-product-actions">
          <button type="button" class="lite-find-product">Search packs</button>
          <button type="button" class="lite-research-product" >Research</button>
        </div>
        <div class="lite-live-slot"></div>
        <div class="lite-search-slot"></div>
        <div class="lite-research-slot"></div>
        <div class="lite-verdict-slot"></div>
        <div class="lite-claims-head-slot"></div>
        <section class="lite-claims"></section>
        <div class="lite-details-slot"></div>
      </div>

      <footer class="lite-footer" hidden></footer>
    `;
  }

  function renderCounts() {
    if (!countsEl) return;
    if (state.pipeline !== "result" || !state.result) {
      countsEl.innerHTML = "";
      return;
    }
    const c = counts();
    // A zero count row is three zeroes saying nothing; the empty card below
    // already says what happened.
    if (!c.total) { countsEl.innerHTML = ""; lastCountNumbers = null; return; }
    countsEl.innerHTML = `
      <div class="lite-counts">
        <span class="lite-count" data-sev="high">
          <span class="dot"></span>
          <span class="num">${c.high}</span>
          <span class="lbl">serious</span>
        </span>
        <span class="lite-count" data-sev="medium">
          <span class="dot"></span>
          <span class="num">${c.medium}</span>
          <span class="lbl">worth checking</span>
        </span>
        <span class="lite-count" data-sev="low">
          <span class="dot"></span>
          <span class="num">${c.low}</span>
          <span class="lbl">minor</span>
        </span>
        <!-- "RISKS", not "CLAIMS", and that is not a leftover.
             The row is a claim everywhere it is *named* — the store, the
             wire, this file's variables — because one thing needs one
             identifier. What a buyer reads is another question, and the app
             answers it "8 known risks, 7 serious" on the same data. Jargon on
             screen would be a worse product and a harder bug report. What was
             wrong was the worker inventing a second field name, never the word
             on screen: docs/STYLE.md rule 9 allows those to differ, and this
             is the case it was written for.
             (And no backticks in here — this comment is inside a template
             literal, which is how it broke the first time.) -->
      </div>
    `;
    // A number that moved bumps once, so a live answer says what changed
    // without a second sentence doing it.
    const now = { high: c.high, medium: c.medium, low: c.low };
    countsEl.querySelectorAll(".lite-count").forEach((chip) => {
      const sev = chip.dataset.sev;
      if (lastCountNumbers && lastCountNumbers[sev] !== now[sev]) {
        chip.dataset.bump = "1";
        chip.addEventListener("animationend", () => { delete chip.dataset.bump; }, { once: true });
      }
    });
    lastCountNumbers = now;
  }

  function sameWords(a, b) {
    const norm = (x) => String(x || "").toLowerCase().split(/\s+/).filter(Boolean).sort().join(" ");
    return norm(a) === norm(b);
  }

  function renderListingHeader() {
    const slot = bodyEl.querySelector(".lite-listing-slot");
    if (!slot) return;
    const lm = state.listingMeta;
    if (!lm) { slot.innerHTML = ""; return; }

    const metaLine = lm.facts
      .map((fact) => `<span>${escapeHtml(fact)}</span>`)
      .join('<span class="sep" aria-hidden="true">·</span>');

    slot.innerHTML = `
      <div class="lite-listing">
        <div class="lite-listing-title">${escapeHtml(lm.title || "")}</div>
        ${lm.facts.length ? `<div class="lite-listing-meta">${metaLine}</div>` : ""}
        ${lm.identity_line
            // The title already says it when the engine read the page the way
            // the page reads; a second line repeating it is noise (B152.5).
            ? (sameWords(lm.identity_line, lm.title) ? "" : `<div class="lite-listing-engine">${escapeHtml(lm.identity_line)}</div>`)
            : `<div class="lite-listing-engine" data-unresolved="1">Not recognised by any installed pack</div>`}
      </div>
    `;
  }

  /* The queue row has a slot of its own. It used to sit inside the listing
   * header, which exists only once a pack has read the page, so on a product
   * nothing installed knew (the very one a reader wants to line up and
   * research) the button was simply gone. */
  function renderQueue() {
    const slot = bodyEl?.querySelector(".lite-queue-slot");
    if (!slot) return;
    slot.innerHTML = renderQueueRow();
    slot.querySelector(".lite-queue")?.addEventListener("click", addToQueue);
    slot.querySelector(".lite-queue-help")?.addEventListener("click", (event) => {
      state.queueHelpOpen = !state.queueHelpOpen;
      event.currentTarget.setAttribute("aria-expanded", String(state.queueHelpOpen));
      slot.querySelector(".lite-queue-guide").hidden = !state.queueHelpOpen;
    });
  }

  // Queue mode. The reader lines up the products they are weighing from the
  // listings themselves; an agent in the app researches them one after
  // another and Compare lines them up. The state is this page's only: a
  // queue press on another listing is another product.
  function queueHere() {
    return state.queue && state.queue.url === window.location.href ? state.queue : null;
  }

  function renderQueueRow() {
    const q = queueHere();
    const phase = q ? q.phase : "idle";
    const label = phase === "busy" ? "Queuing…"
      : phase === "queued" || phase === "already" ? "In the queue"
        : "Add to queue";
    const done = phase === "queued" || phase === "already";
    return `
      <div class="lite-queue-row" data-phase="${phase}">
        <button type="button" class="lite-queue" ${phase === "busy" || done ? "disabled" : ""}
          aria-pressed="${done ? "true" : "false"}">${label}</button>
        <button type="button" class="lite-queue-help" aria-label="How to use the research queue"
          aria-controls="lite-queue-guide" aria-expanded="${state.queueHelpOpen}"
          title="How to use the research queue">?</button>
        ${q && q.text ? `<span class="lite-queue-note" role="status">${escapeHtml(q.text)}</span>` : ""}
      </div>
      <div id="lite-queue-guide" class="lite-queue-guide" ${state.queueHelpOpen ? "" : "hidden"}>
        <strong>Research a shortlist</strong>
        <p>Add products from their listings, then open <b>Compare → Research queue</b>
          in Kriko, choose an agent and press <b>Start queue</b>.</p>
        <p>The agent researches each in turn. Adding does not start research;
          the queue stays on this computer.</p>
      </div>`;
  }

  function addToQueue() {
    const lm = state.listingMeta || {};
    const url = window.location.href;
    state.queue = { url, phase: "busy", text: "" };
    renderQueue();
    chrome.runtime.sendMessage({ type: "QUEUE_ADD", payload: {
      url,
      // the engine's reading of the product first: it is the name the
      // agent researches under, where the page title is the seller's
      name: lm.identity_line || lm.title || state.unknownProduct || document.title,
      lookup_id: (state.result && state.result.lookup_id) || "",
    } }, (response) => {
      if (state.queue.url !== url) return;
      if (chrome.runtime.lastError || !response || !response.ok) {
        const full = response && response.status === 409;
        state.queue = { url, phase: "error", text: full
          ? "The queue is full. Research or remove one in Kriko first."
          : (response && response.error) || "Kriko is not running. Open the Kriko app, then try again." };
      } else {
        state.queue = { url, phase: response.added ? "queued" : "already",
          text: `${response.added ? "Queued" : "Already queued"} · ${response.count} of ${response.max} in Compare` };
      }
      renderQueue();
    });
  }

  // ─── The reader as a buyer ────────────────────────────────────────────
  // What the app says about this page as a purchase, the questions about earlier
  // purchases, and the shortlist's pick. The words and the numbers come from the
  // app; `buyer_card.js` only draws them, and every press here is forwarded as
  // the reader's own request to the app's own API.
  const BUYER = window.__KrikoBuyer || null;
  const buyerKey = () => "kriko_buyer_" + window.location.href;

  function renderBuyer() {
    const slot = bodyEl?.querySelector(".lite-buyer-slot");
    if (!slot || !BUYER) return;
    slot.innerHTML = BUYER.renderDue(state.buyerDue, state.buyerUi)
      + BUYER.renderBuyerCard(state.buyer, state.buyerUi);
  }

  function renderDecide() {
    const slot = bodyEl?.querySelector(".lite-decide-slot");
    if (!slot || !BUYER) return;
    // Deciding is for a reader who has something to decide: a page that was
    // read, or a shortlist started from this page. Not for an error or a nudge.
    if (state.pipeline !== "result" && !state.pick && !queueHere()) { slot.innerHTML = ""; return; }
    const busy = state.buyerUi.deciding;
    slot.innerHTML = `<div class="lite-buy-actions"><button type="button" class="lite-buy-btn" data-act="decide"
      ${busy ? "disabled" : ""} title="Rank the products in your queue for what you told Kriko you need">
      ${busy ? "Deciding…" : "Decide between my shortlist"}</button></div>`
      + (state.buyerUi.decideError ? `<p class="lite-buy-note" data-tone="bad">${BUYER.esc(state.buyerUi.decideError)}</p>` : "")
      + BUYER.renderPick(state.pick, state.buyerUi);
  }

  // One request to the worker, resolved as a promise so the handlers read in order.
  function askWorker(type, payload) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type, payload }, (response) => {
        if (chrome.runtime.lastError || !response) {
          resolve({ ok: false, error: "Kriko is not running. Open the Kriko app, then try again." });
        } else {
          resolve(response);
        }
      });
    });
  }

  function loadBuyer() {
    try {
      chrome.storage.session.get(buyerKey(), (got) => {
        void chrome.runtime.lastError;
        const entry = got && got[buyerKey()];
        if (entry && entry.ok) { state.buyer = entry.buyer; renderBuyer(); }
      });
    } catch (_) {
      // No session storage here (an old browser): the card waits for a push.
    }
    askWorker("BUYER_DUE", {}).then((reply) => {
      if (reply.ok) { state.buyerDue = reply.due || []; renderBuyer(); }
    });
  }

  function pollAdvice(jobId) {
    askWorker("JOB_STATUS", { job_id: jobId }).then((reply) => {
      const advice = state.buyerUi.advice;
      if (!advice || advice.jobId !== jobId) return;
      const job = reply.job;
      if (!reply.ok || !job) {
        state.buyerUi.advice = { ...advice, state: "failed", error: "Cannot check the answer. Try again." };
      } else if (job.state === "succeeded") {
        state.buyerUi.advice = { ...advice, state: "done", answer: (job.result && job.result.answer) || "" };
      } else if (["failed", "cancelled", "interrupted"].includes(job.state)) {
        state.buyerUi.advice = { ...advice, state: "failed",
          error: job.error || job.message || "The agent did not finish. Try again." };
      } else {
        setTimeout(() => pollAdvice(jobId), 1200);
      }
      renderDecide();
    });
  }

  function onBuyerClick(event) {
    const target = event.target.closest && event.target.closest("[data-act]");
    if (!target || !bodyEl.contains(target) || !BUYER) return;
    const act = target.dataset.act;
    const ui = state.buyerUi;
    const buyer = state.buyer || {};
    if (act === "watch-open") { ui.watchForm = true; renderBuyer(); }
    else if (act === "watch-cancel") { ui.watchForm = false; renderBuyer(); }
    else if (act === "unwatch") {
      askWorker("BUYER_UNWATCH", { watch_id: target.dataset.id }).then((reply) => {
        if (reply.ok && state.buyer) state.buyer.watch = null;
        renderBuyer();
      });
    } else if (act === "bought") {
      const lm = state.listingMeta || {};
      askWorker("BUYER_BOUGHT", {
        name: buyer.name || lm.identity_line || lm.title || document.title, url: window.location.href,
        price: buyer.price ? buyer.price.price : null, currency: buyer.price ? buyer.price.currency : "",
      }).then((reply) => { ui.bought = reply.ok; ui.boughtError = reply.ok ? "" : reply.error; renderBuyer(); });
    } else if (act === "answer") {
      askWorker("BUYER_ANSWER", { purchase_id: target.dataset.id, verdict: target.dataset.verdict }).then((reply) => {
        if (reply.ok) state.buyerDue = state.buyerDue.filter((one) => one.purchase_id !== target.dataset.id);
        renderBuyer();
      });
    } else if (act === "regret") { ui.regretFor = target.dataset.id; renderBuyer(); }
    else if (act === "snooze") {
      askWorker("BUYER_SNOOZE", { purchase_id: target.dataset.id }).then((reply) => {
        if (reply.ok) state.buyerDue = state.buyerDue.filter((one) => one.purchase_id !== target.dataset.id);
        renderBuyer();
      });
    } else if (act === "decide") {
      ui.deciding = true; ui.decideError = ""; renderDecide();
      askWorker("BUYER_PICK", {}).then((reply) => {
        ui.deciding = false;
        if (reply.ok) { state.pick = reply; ui.advice = null; }
        else ui.decideError = reply.error || "Could not rank the shortlist.";
        renderDecide();
      });
    } else if (act === "advise") {
      ui.advice = { mode: target.dataset.mode, state: "running" };
      renderDecide();
      askWorker("BUYER_ADVICE", { mode: target.dataset.mode }).then((reply) => {
        if (reply.ok && reply.job_id) {
          ui.advice = { mode: target.dataset.mode, state: "running", jobId: reply.job_id };
          pollAdvice(reply.job_id);
        } else {
          ui.advice = { mode: target.dataset.mode, state: "failed",
            error: reply.error || "Could not start your agent. Check Agents in Kriko." };
        }
        renderDecide();
      });
    }
  }

  function onBuyerSubmit(event) {
    const form = event.target.closest && event.target.closest("form[data-act]");
    if (!form || !bodyEl.contains(form) || !BUYER) return;
    event.preventDefault();
    const field = (name) => (form.querySelector(`[name="${name}"]`) || {}).value || "";
    if (form.dataset.act === "watch-save") {
      const buyer = state.buyer || {};
      const lm = state.listingMeta || {};
      askWorker("BUYER_WATCH", {
        url: window.location.href, name: buyer.name || lm.identity_line || lm.title || document.title,
        target: field("target").trim() || null,
        cloud: Boolean((form.querySelector('[name="cloud"]') || {}).checked),
        price: buyer.price ? buyer.price.price : null, currency: buyer.price ? buyer.price.currency : "",
      }).then((reply) => {
        if (reply.ok && state.buyer) { state.buyer.watch = reply; state.buyerUi.watchForm = false; }
        else state.buyerUi.watchError = reply.error || "Could not watch this page.";
        renderBuyer();
      });
    } else if (form.dataset.act === "regret-save") {
      askWorker("BUYER_ANSWER", { purchase_id: form.dataset.id, verdict: "regret", reason: field("reason") })
        .then((reply) => {
          if (reply.ok) { state.buyerDue = state.buyerDue.filter((one) => one.purchase_id !== form.dataset.id); }
          state.buyerUi.regretFor = null;
          renderBuyer();
        });
    }
  }

  // The look before paying is a small card of its own, not the panel: it
  // speaks up on a cart page the reader has not asked anything of, so it must
  // be easy to dismiss, quiet in what it says, and never in the way of the pay
  // button (bottom left, away from where checkouts put theirs).
  const TOAST_STYLE = `<style>
      .kriko-guard-card,.kriko-due-card{font:13px/1.45 system-ui,sans-serif;max-width:340px;padding:12px 14px;border-radius:10px;
        background:#111522;color:#eef1f9;border:1px solid rgba(255,255,255,.18);box-shadow:0 12px 32px rgba(0,0,0,.45)}
      .kriko-guard-card[data-verdict="stop"]{border-color:#ff6b7a}
      .kriko-guard-card[data-verdict="check"]{border-color:#f5b84b}
      .kriko-due-card{border-color:#3d6bff}
      .kriko-guard-card ul{margin:6px 0 8px;padding-left:18px}
      .kriko-guard-card li{margin:2px 0}
      .kriko-due-card p{margin:0 0 6px}
      .lite-buy-due{background:none;padding:0;margin:0;box-shadow:none}
      .kriko-guard-actions,.lite-buy-actions,.lite-buy-form{display:flex;flex-wrap:wrap;gap:6px 8px}
      .kriko-guard-actions button,.lite-buy-btn{font:600 12px system-ui,sans-serif;padding:4px 10px;border-radius:6px;cursor:pointer;
        border:1px solid rgba(255,255,255,.25);background:transparent;color:inherit}
      .lite-buy-btn[data-primary="1"]{background:#3d6bff;border-color:#3d6bff;color:#fff}
      .lite-buy-form input{flex:1;min-width:140px;padding:4px 8px;border-radius:6px;border:1px solid rgba(255,255,255,.25);
        background:#0b0e17;color:inherit;font:13px system-ui,sans-serif}
      </style>`;
  // A card on the page that is not the panel, in a shadow root of its own so the
  // page's styles cannot reach it. One of each kind at a time.
  const toasts = {};
  function showToast(kind, html, onClick, onSubmit) {
    if (toasts[kind]) toasts[kind].remove();
    const host = document.createElement(`kriko-${kind}-host`);
    host.style.cssText = "all:initial;position:fixed;left:16px;bottom:16px;z-index:2147483646;";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = TOAST_STYLE + html;
    root.addEventListener("click", (event) => {
      const act = event.target.closest && event.target.closest("[data-act]");
      if (act) onClick(act, host, root);
    });
    if (onSubmit) root.addEventListener("submit", (event) => { event.preventDefault(); onSubmit(event.target, host, root); });
    toasts[kind] = host;
    document.documentElement.appendChild(host);
    return host;
  }
  function closeToast(kind) {
    if (toasts[kind]) { toasts[kind].remove(); toasts[kind] = null; }
  }

  function showGuard(result) {
    if (!BUYER || !result) return;
    const html = BUYER.renderGuard(result);
    if (!html) return;
    showToast("guard", html, (act) => {
      if (act.dataset.act === "guard-open") { closeToast("guard"); openPanel(); }
      if (act.dataset.act === "guard-dismiss") closeToast("guard");
    });
  }

  // "Did it hold up?", asked on a page Kriko reads. The same four answers as in
  // the panel, and a way to ignore it: a question, not a gate.
  function showDueNudge(purchase) {
    if (!BUYER || !purchase) return;
    const ui = {};
    const draw = (root) => {
      root.innerHTML = TOAST_STYLE + `<div class="kriko-due-card">${BUYER.renderDue([purchase], ui)}
        <div class="kriko-guard-actions"><button type="button" data-act="due-dismiss">Not now</button></div></div>`;
    };
    const finish = (verdict, reason) => askWorker("BUYER_ANSWER", {
      purchase_id: purchase.purchase_id, verdict, reason: reason || "" }).then((reply) => {
      if (reply.ok) { state.buyerDue = state.buyerDue.filter((one) => one.purchase_id !== purchase.purchase_id); renderBuyer(); }
      closeToast("due");
    });
    const host = showToast("due", "", (act, _host, root) => {
      const what = act.dataset.act;
      if (what === "answer") void finish(act.dataset.verdict);
      else if (what === "regret") { ui.regretFor = purchase.purchase_id; draw(root); }
      else if (what === "snooze") askWorker("BUYER_SNOOZE", { purchase_id: purchase.purchase_id }).then(() => closeToast("due"));
      else if (what === "due-dismiss") closeToast("due");
    }, (form) => {
      const field = form.querySelector('[name="reason"]');
      void finish("regret", field ? field.value : "");
    });
    draw(host.shadowRoot);
  }

  function renderCriticalAlerts() {
    const slot = bodyEl.querySelector(".lite-alerts-slot");
    if (!slot) return;
    const alerts = buildCriticalAlerts(state.listingMeta);
    if (!alerts.length) { slot.innerHTML = ""; return; }
    slot.innerHTML = `
      <div class="lite-alerts" data-open="1">
        <button type="button" class="lite-alerts-head">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="miter" style="flex:0 0 auto;color:var(--high-ink);"><path d="M12 3 1.5 21h21z"/><line x1="12" y1="10" x2="12" y2="14"/><line x1="12" y1="17.5" x2="12" y2="17.6"/></svg>
          <span class="lite-alerts-label">CRITICAL ALERTS</span>
          <span class="lite-alerts-toggle">–</span>
        </button>
        <div class="lite-alerts-bodywrap">
          <div class="lite-alerts-bodyclip">
            ${alerts.map(a => `<div class="lite-alerts-row">${escapeHtml(a)}</div>`).join("")}
          </div>
        </div>
      </div>
    `;
    const alertsEl = slot.querySelector(".lite-alerts");
    const toggleEl = slot.querySelector(".lite-alerts-toggle");
    slot.querySelector(".lite-alerts-head").addEventListener("click", () => {
      const isOpen = alertsEl.dataset.open === "1";
      alertsEl.dataset.open = isOpen ? "0" : "1";
      toggleEl.textContent = isOpen ? "+" : "–";
    });
  }

  function renderListingDetails() {
    const slot = bodyEl.querySelector(".lite-details-slot");
    if (!slot) return;
    const lm = state.listingMeta;
    if (!lm) { slot.innerHTML = ""; lastDetailsListingMeta = null; return; }
    const damage = lm.damage_info || {};
    const panel = lm.panel || {};
    const equipment = lm.equipment || {};
    const equipmentEntries = Object.entries(equipment).filter(([, items]) => items && items.length);

    // Which local rows exist, what each is called, which tone it takes and
    // what it warns about are all the answering pack's declarations. This
    // panel used to name four of them itself, in English, over Turkish keys
    // — which is how "add a listing site" and "add a category" both became
    // extension releases. A state the pack declares without a title is
    // scraped and not shown: an untouched panel is the absence of a finding,
    // and a row of them would bury the rows that are findings.
    const declaredRows = [];
    for (const state of panel.states || []) {
      if (!state.title) continue;
      const items = Array.isArray(damage[state.key]) ? damage[state.key] : [];
      if (!items.length) continue;
      declaredRows.push({
        title: state.title, tone: state.tone || "neutral", items, hint: state.hint || "",
      });
    }
    for (const measure of panel.measures || []) {
      if (!measure.title) continue;
      const amount = damage[measure.key];
      if (!amount) continue;
      const currency =
        (measure.currency_key ? damage[measure.currency_key] : null) ||
        measure.default_currency || "";
      declaredRows.push({
        title: measure.title, tone: measure.tone || "neutral",
        items: [`${Number(amount).toLocaleString()}${currency ? ` ${currency}` : ""}`],
        hint: measure.hint || "",
      });
    }

    if (!declaredRows.length && !equipmentEntries.length) {
      slot.innerHTML = "";
      lastDetailsListingMeta = null;
      return;
    }

    // Build the DOM only when the underlying listing changes. Toggles after
    // that mutate data-open on the existing elements so CSS grid-template-rows
    // can animate.
    if (lm !== lastDetailsListingMeta) {
      lastDetailsListingMeta = lm;

      const rows = declaredRows.slice();
      for (const [category, items] of equipmentEntries) {
        rows.push({ title: category, tone: "neutral", items });
      }

      const totalChips = rows.reduce((n, r) => n + r.items.length, 0);

      const rowHtml = rows.map((r) => {
        const rowOpen = state.openDetailRows.has(r.title);
        const chips = r.items.map(p =>
          `<span class="lite-tag" data-tone="${escapeHtml(r.tone)}">${escapeHtml(p)}</span>`
        ).join("");
        return `
          <div class="lite-detrow" data-row="${escapeHtml(r.title)}" data-open="${rowOpen ? "1" : "0"}">
            <button type="button" class="lite-detrow-head">
              <span class="toggle-glyph">${iconSvg(rowOpen ? "minus" : "plus", { size: 9 })}</span>
              <span>${escapeHtml(r.title)}</span>
              <span class="count">· ${r.items.length}</span>
            </button>
            ${r.hint ? `<div class="lite-detrow-hint">${escapeHtml(r.hint)}</div>` : ""}
            <div class="lite-detrow-bodywrap">
              <div class="lite-detrow-bodyclip">
                <div class="lite-detrow-chips">${chips}</div>
              </div>
            </div>
          </div>
        `;
      }).join("");

      slot.innerHTML = `
        <div class="lite-details" data-open="${state.detailsOpen ? "1" : "0"}">
          <button type="button" class="lite-details-head">
            <span>Listing details · ${totalChips}</span>
            <span class="toggle-glyph">${iconSvg(state.detailsOpen ? "minus" : "plus", { size: 12 })}</span>
          </button>
          <div class="lite-details-bodywrap">
            <div class="lite-details-bodyclip">
              <div class="lite-details-rows">${rowHtml}</div>
            </div>
          </div>
        </div>
      `;

      // Wire panel head
      const panelEl = slot.querySelector(".lite-details");
      const panelHead = slot.querySelector(".lite-details-head");
      const panelGlyph = panelHead.querySelector(".toggle-glyph");
      panelHead.addEventListener("click", () => {
        state.detailsOpen = !state.detailsOpen;
        panelEl.dataset.open = state.detailsOpen ? "1" : "0";
        panelGlyph.innerHTML = iconSvg(state.detailsOpen ? "minus" : "plus", { size: 12 });
      });

      // Wire each row head
      slot.querySelectorAll(".lite-detrow").forEach((rowEl) => {
        const head = rowEl.querySelector(".lite-detrow-head");
        const glyph = head.querySelector(".toggle-glyph");
        head.addEventListener("click", () => {
          const title = rowEl.dataset.row;
          const nowOpen = !state.openDetailRows.has(title);
          if (nowOpen) state.openDetailRows.add(title);
          else state.openDetailRows.delete(title);
          rowEl.dataset.open = nowOpen ? "1" : "0";
          glyph.innerHTML = iconSvg(nowOpen ? "minus" : "plus", { size: 9 });
        });
      });
    }
  }

  // The one idle state where the primary button's lookup is a dead end: a
  // product nothing installed knows is answered "unknown" every time. The card
  // under the button already offers the research; this makes the button offer
  // it too, so a press does something the reader can see.
  function ctaIsResearch() {
    return Boolean(state.unknownProduct) && state.pipeline === "idle";
  }

  function renderCta() {
    if (!ctaBtn) return;
    const isAnalyzing = state.pipeline === "analyzing";
    const hasResult   = state.pipeline === "result";
    ctaBtn.dataset.analyzing = isAnalyzing ? "1" : "0";
    ctaBtn.disabled = isAnalyzing;
    const iconName = isAnalyzing || hasResult ? "refresh" : "scan";
    const label = isAnalyzing
      ? "Searching…"
      : (hasResult ? "Search again"
        : (ctaIsResearch() ? "Research this product" : "Search this product"));
    const iconWrap = ctaBtn.querySelector(".lite-cta-icon");
    iconWrap.innerHTML = iconSvg(iconName, { size: 15 });
    ctaBtn.querySelector(".lite-cta-label").textContent = label;
    /* One indicator while a run is in flight, and it is the skeleton list.
     *
     * Three things used to move at once here: this key's icon, the header's
     * refresh icon, and the shimmering rows the answer will land in. Three
     * indicators that always start and stop together are not three pieces of
     * information, they are one fact drawn three times — and the stage
     * sentence above them is the fourth statement of it. The skeleton is the
     * one kept, because it is the only one that says where the answer goes.
     */
    // B152.8: once there is an answer the header's refresh icon is the one
    // way to ask again; a second full-width "Refresh analysis" under it was
    // the same control twice, pushing the risks down the panel.
    const wrap = ctaBtn.closest(".lite-cta-wrap");
    if (wrap) wrap.style.display = hasResult ? "none" : "";
  }

  /* The step a run is on, in words that are true.
   *
   * What stood here was one fixed sentence naming two steps the engine does
   * not have — it read as progress and carried none, which is the precise
   * complaint: a run that *looks* alive without *being* legible. These four
   * are the worker's actual steps, and a step this panel has no name for is
   * shown as itself rather than smoothed into a nicer lie.
   */
  const STAGE_WORDS = {
    adapters: "Checking which pack reads this site",
    reading: "Reading this page",
    asking: "Asking Kriko what is known",
    cached: "Reusing the answer already stored",
    done: "Done",
    failed: "Could not finish",
  };

  function stageSentence(stage) {
    if (!stage || !stage.name) return "Starting…";
    const words = STAGE_WORDS[stage.name] || stage.name;
    return stage.detail ? `${words} · ${stage.detail}` : `${words}…`;
  }

  /* ─── What the rest of Kriko is doing ──────────────────────────────────
   *
   * The app has a screen for this and the reader is not on it — they are
   * here, on a listing, which is the whole reason the extension exists. So a
   * research run their own coding agent started against the very product in
   * front of them was invisible from the one surface they were looking at.
   *
   * Deliberately small, and shown only while something is actually running.
   * This is a window onto the feed, not a second copy of it: no details, no
   * payloads, no Stop. What a run *produced* is the app's to show, and the
   * panel already has a button that opens it.
   */
  const DOOR_WORDS = {
    mcp: "your agent",
    job: "the app",
    extension: "this extension",
    app: "the app",
    cli: "the command line",
  };

  function renderLive() {
    const slot = bodyEl?.querySelector(".lite-live-slot");
    if (!slot) return;
    // `null` is "not asked yet" and must not paint an empty answer.
    const going = (state.live || []).filter((one) => one.state === "running");
    if (!going.length) {
      slot.innerHTML = "";
      return;
    }
    slot.innerHTML = `
      <div class="lite-live">
        <div class="lite-live-head">Also running</div>
        <ul class="lite-live-list"></ul>
      </div>
    `;
    const list = slot.querySelector(".lite-live-list");
    for (const row of going) {
      const item = document.createElement("li");
      const who = DOOR_WORDS[row.door] || row.door;
      // The stage when the row has one. A job carries its own live message;
      // an agent's tool call does not, and inventing one for it is what the
      // status line above this was doing wrong.
      const note = row.note
        ? row.note
        : "";
      item.textContent = note
        ? `${row.name} · ${who} · ${note}`
        : `${row.name} · ${who}`;
      if (typeof row.progress === "number") {
        const bar = document.createElement("div");
        bar.className = "lite-progress lite-progress-row";
        bar.setAttribute("role", "progressbar");
        bar.innerHTML = `<div class="lite-progress-fill"></div>`;
        showProgress(bar, row.progress);
        item.appendChild(bar);
      }
      list.appendChild(item);
    }
  }

  /** Ask what is running, and keep asking while the panel is open.
   *
   * Polled rather than streamed, for the reason `pollResearchJob` is: the
   * panel holds no open connection to the app, and a content script that did
   * would hold it open on every listing page the reader leaves in a tab. */
  function pollLive() {
    // A tab left open in the background still counts as "visible" by our own
    // bookkeeping (the panel is still mounted) — but nobody is looking, so a
    // request every 2s there is pure cost. document.hidden catches exactly
    // that case; the visibilitychange listener below resumes polling the
    // moment the tab is looked at again.
    if (!state.visible || document.hidden) { stopLive(); return; }
    chrome.runtime.sendMessage({ type: "OPERATIONS", payload: { limit: 6 } }, (response) => {
      if (!state.visible) return;
      const ok = !chrome.runtime.lastError && response?.ok;
      if (!ok) {
        // An unreachable app is not worth a banner here: the analysis path
        // above already says so, loudly, and this section is an aside. It
        // falls quiet instead, which is what "nothing is running" looks like
        // and is the honest reading of "cannot tell".
        state.live = [];
      } else {
        state.live = Array.isArray(response.feed?.items) ? response.feed.items : [];
        const clock = response.feed?.knowledge;
        if (clock) {
          if (state.knowledge && clock !== state.knowledge) knowledgeMoved();
          state.knowledge = clock;
        }
      }
      renderLive();
      // A dead engine does not get asked every 2s until the next Analyze —
      // that is a request a page load that never answers, forever. Back off
      // to 30s; a live one keeps its snappier interval.
      if (state.visible) state.liveTimer = setTimeout(pollLive, ok ? 2000 : 30000);
    });
  }

  /** Something wrote to the knowledge while this panel was open (B152.4):
   * an agent's findings, a research run, a pack install. The answer on screen
   * is asked again in place — background.js writes it to session storage and
   * the listener below applies it — and a product nobody knew is asked about
   * again, quietly, in case it is known now. */
  function knowledgeMoved() {
    if (state.pipeline === "result" && state.result && state.result.lookup_id) {
      chrome.runtime.sendMessage({
        type: "REFRESH_ANSWER",
        payload: { url: window.location.href, lookupId: state.result.lookup_id },
      }, () => { void chrome.runtime.lastError; });
      return;
    }
    if (state.pipeline === "idle" && state.unknownProduct) {
      chrome.runtime.sendMessage(
        { type: "ANALYZE", payload: { url: window.location.href, fresh: true } },
        (response) => {
          if (chrome.runtime.lastError) return;
          if (response && response.ok && response.result) {
            state.unknownProduct = "";
            applyEntry({ ok: true, result: response.result });
          }
        });
    }
  }

  function stopLive() {
    if (state.liveTimer) clearTimeout(state.liveTimer);
    state.liveTimer = null;
  }

  // The resume half of the `document.hidden` stop in `pollLive`: the tab
  // coming back into view asks again at once instead of waiting for Analyze.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.visible && !state.liveTimer) pollLive();
  });

  function renderStatus() {
    if (!statusEl) return;
    if (state.pipeline === "idle") {
      statusEl.textContent = ctaIsResearch() ? UNKNOWN_HINT : IDLE_HINT;
      statusEl.style.display = "";
    } else if (state.pipeline === "analyzing") {
      statusEl.textContent = stageSentence(state.stage);
      statusEl.style.display = "";
    } else if (state.pipeline === "result") {
      // The claim list below says everything; a status line repeating it is
      // a line the eye has to skip on every result.
      statusEl.textContent = "";
      statusEl.style.display = "none";
    } else if (state.pipeline === "error") {
      // The error box below says it, with its way out beside it; the same
      // sentence again under the key was the panel saying it twice.
      statusEl.textContent = "";
      statusEl.style.display = "none";
    }
  }

  // Render claims header helper
  /* ─── How sure the engine is, and what to do about it ──────────────────
   *
   * The panel had two states for four situations. A page the packs recognised
   * exactly and a page they had never heard of both rendered as claims or as
   * a blank, and the reader who met the blank had a good pack installed for
   * that exact product with no way to find out which of four things had gone
   * wrong: a pack never installed, a page misread, a catalog spelling one
   * value differently, or a genuine gap.
   *
   * `verdict`, `score`, `considered` and `next_step` are the engine's answer
   * to that, and every one of them is *the engine's* — this renders them and
   * writes none of the copy. `next_step.say` is a sentence `app/matching.py`
   * composed from the same objects the answer was built from, and `action` is
   * a closed vocabulary. A client writing its own copy from a status code
   * stops agreeing with the engine the first time a method is added, which is
   * the failure this whole block exists to end rather than to repeat.
   */
  /* What the button says, and it is a function rather than a map because the
   * same action word can only do two different things here.
   *
   * `research` arrives with a `subject_id` when the engine resolved something
   * to research (a recognised product the packs hold nothing on), and without
   * one when it did not (a page nothing placed). The second cannot start a
   * research run — there is no subject to run it against — so it goes to
   * search, and the button has to say so. A button labelled "Research it"
   * that opens a search field is a button the reader stops trusting. */
  function actionLabel(action, step) {
    if (action === "install") return "Open Kriko";
    if (action === "research") {
      return "Research this product";
    }
    if (action === "confirm") return "Not this one; search";
    return "";
  }

  /* ─── Typing the name, when standing on the page was not enough ────────
   *
   * "The extension has no way to search for a particular product. I have to be
   * standing on the right page and hope recognition fires."
   *
   * Every way into this panel was the page: an adapter matched, a scrape ran,
   * and either the packs placed it or the reader got a blank. That is fine
   * when it works and a dead end when it does not — a site with no adapter, a
   * listing that names the thing in words no pack declared, or somebody
   * comparing two of something from their sofa.
   *
   * So: a field. It is also where three of the four verdicts send the reader,
   * which is the point rather than a convenience — "we could not place this
   * page" and "type what it is" are the same moment.
   *
   * **Every result carries its identity, and that is the feature.** Two rows
   * reading `Golf VII` are not a choice; the same name followed by the two
   * configurations that differ is. A list of labels cannot tell one of a thing
   * from another of it, which is the entire reason the reader asked.
   */
  const SEARCH_MIN = 2;
  const SEARCH_DEBOUNCE_MS = 220;
  let searchTimer = null;
  let searchRunId = 0;
  let webSearch = false;

  function openSearch(query = "") {
    const initialQuery = String(query || "").trim();
    if (initialQuery) {
      state.searchQuery = initialQuery;
      state.searchResults = null;
      state.searchError = null;
      state.searchBusy = false;
    }
    state.searchOpen = true;
    renderSearch();
    const field = bodyEl && bodyEl.querySelector(".lite-search-field");
    if (field) {
      if (initialQuery) field.value = initialQuery;
      field.focus();
    }
    if (initialQuery.length >= SEARCH_MIN) runSearch(initialQuery);
  }

  function runSearch(text) {
    const query = String(text || "").trim();
    state.searchQuery = query;
    if (searchTimer) clearTimeout(searchTimer);
    const runId = ++searchRunId;
    state.searchError = null;
    if (query.length < SEARCH_MIN) {
      state.searchResults = null;
      state.searchBusy = false;
      return renderSearchResults();
    }
    // Debounced, and every reply carries the id of the keystroke that asked
    // for it: without that, a slow answer to "gol" lands after a fast one to
    // "golf" and the reader watches their own typing undo itself.
    state.searchBusy = true;
    renderSearchResults();
    searchTimer = setTimeout(() => {
      chrome.runtime.sendMessage({ type: webSearch ? "WEB_SEARCH" : "SEARCH", payload: { q: query } }, (reply) => {
        if (runId !== searchRunId) return;
        state.searchBusy = false;
        if (chrome.runtime.lastError || !reply || !reply.ok) {
          state.searchResults = [];
          state.searchError = (reply && reply.error)
            || (chrome.runtime.lastError && chrome.runtime.lastError.message)
            || "Could not search.";
        } else {
          state.searchError = null;
          state.searchResults = Array.isArray(reply.items) ? reply.items : [];
        }
        renderSearchResults();
      });
    }, webSearch ? 600 : SEARCH_DEBOUNCE_MS);
  }

  function renderSearch() {
    const slot = bodyEl && bodyEl.querySelector(".lite-search-slot");
    if (!slot) return;
    if (!state.searchOpen) { slot.innerHTML = ""; return; }
    if (slot.querySelector(".lite-search")) return renderSearchResults();

    slot.innerHTML = `
      <div class="lite-search">
        <div class="lite-search-bar">
          <span class="lite-search-icon">${iconSvg("search", { size: 15 })}</span>
          <input class="lite-search-field" type="text" autocomplete="off"
                 spellcheck="false" placeholder="Type a product name"
                 aria-label="${webSearch ? "Search the web" : "Search the installed packs"}" />
          <button type="button" class="lite-search-close"
                  title="Close search" aria-label="Close search">
            ${iconSvg("x", { size: 14, strokeWidth: 2 })}
          </button>
        </div>
        <div class="lite-search-modes">
          <button type="button" class="lite-search-local" aria-pressed="${!webSearch}">Installed packs</button>
          <button type="button" class="lite-search-web" aria-pressed="${webSearch}">Search the web</button>
        </div>
        <div class="lite-search-results"></div>
      </div>
    `;
    const field = slot.querySelector(".lite-search-field");
    field.value = state.searchQuery || "";
    field.addEventListener("input", (event) => runSearch(event.target.value));
    field.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { event.stopPropagation(); closeSearch(); }
    });
    slot.querySelector(".lite-search-close")
      .addEventListener("click", () => closeSearch());
    const chooseMode = (web) => {
      webSearch = web;
      slot.querySelector(".lite-search-local").setAttribute("aria-pressed", String(!web));
      slot.querySelector(".lite-search-web").setAttribute("aria-pressed", String(web));
      field.setAttribute("aria-label", web ? "Search the web" : "Search the installed packs");
      runSearch(field.value);
    };
    slot.querySelector(".lite-search-local").addEventListener("click", () => chooseMode(false));
    slot.querySelector(".lite-search-web").addEventListener("click", () => chooseMode(true));
    renderSearchResults();
  }

  function closeSearch() {
    ++searchRunId;
    state.searchOpen = false;
    state.searchQuery = "";
    state.searchResults = null;
    state.searchError = null;
    if (searchTimer) clearTimeout(searchTimer);
    renderSearch();
  }

  function renderSearchResults() {
    const box = bodyEl && bodyEl.querySelector(".lite-search-results");
    if (!box) return;
    const signature = JSON.stringify({
      query: state.searchQuery,
      busy: state.searchBusy,
      error: state.searchError,
      results: state.searchResults,
      web: webSearch,
    });
    // Listing refreshes are independent from search. Keep matching cards
    // mounted so polling cannot reset their expansion, focus or scroll.
    if (box.dataset.renderKey === signature) return;
    box.dataset.renderKey = signature;
    box.innerHTML = "";

    if (state.searchBusy) {
      box.innerHTML = `<p class="lite-search-note">Searching…</p>`;
      return;
    }
    if (state.searchError) {
      box.innerHTML = `<p class="lite-search-note">${escapeHtml(state.searchError)}</p>`;
      return;
    }
    if (state.searchResults === null) {
      box.innerHTML =
        `<p class="lite-search-note">At least ${SEARCH_MIN} characters. ` +
        `Names, aliases or values.</p>`;
      return;
    }
    if (!state.searchResults.length) {
      box.innerHTML =
        `<p class="lite-search-note">${webSearch ? "No web results found. Try fewer words."
          : "Nothing in the installed packs matches that. Try Search the web."}</p>`;
      return;
    }

    for (const row of state.searchResults) {
      if (webSearch) {
        const url = String(row.url || "").trim();
        if (!url || !/^https?:\/\//i.test(url)) continue;
        const link = document.createElement("a");
        link.className = "lite-search-hit";
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.innerHTML = `<span class="lite-search-label">${escapeHtml(row.title || row.url)}</span>
          <span class="lite-search-identity">${escapeHtml(row.site || "")}</span>
          <span>${escapeHtml(row.snippet || "")}</span>`;
        box.appendChild(link);
        continue;
      }
      const item = document.createElement("button");
      item.type = "button";
      item.className = "lite-search-hit";
      // The identity, spelled out, is the half that makes this a choice.
      const identity = Object.entries(row.identity || {})
        .map(([key, value]) => `
          <span class="lite-search-id">
            <span class="lite-search-id-key">${escapeHtml(key)}</span>
            ${escapeHtml(String(value))}
          </span>`)
        .join("");
      const claims = typeof row.claims === "number" ? row.claims : null;
      item.innerHTML = `
        <span class="lite-search-hit-head">
          <span class="lite-search-label">${escapeHtml(row.label || row.subject_id || "")}</span>
          ${claims !== null
            ? `<span class="lite-search-count">${claims} known</span>`
            : ""}
        </span>
        <span class="lite-search-identity">${identity}</span>
      `;
      item.addEventListener("click", () => openInApp(
        `subject/${encodeURIComponent(row.subject_id)}`,
        appUrlFor(`subject/${encodeURIComponent(row.subject_id)}`),
      ));
      box.appendChild(item);
      const research = document.createElement("button");
      research.type = "button";
      research.className = "lite-search-research";
      research.textContent = `Research ${row.label || row.subject_id}`;
      research.addEventListener("click", () => researchSubject(row));
      box.appendChild(research);
    }
  }

  function renderVerdict() {
    const slot = bodyEl?.querySelector(".lite-verdict-slot");
    if (!slot) return;
    slot.innerHTML = "";

    if (state.unknownProduct && state.pipeline !== "result") {
      const card = document.createElement("div");
      card.className = "lite-verdict";
      card.dataset.verdict = "unknown-product";
      card.innerHTML = `
        <div class="lite-verdict-head">
          <span class="lite-verdict-word">New to Kriko</span>
        </div>
        <p class="lite-verdict-say">Kriko doesn't know
          <strong class="lite-unknown-name"></strong> yet. Research it.</p>
      `;
      card.querySelector(".lite-unknown-name").textContent = state.unknownProduct;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-verdict-btn lite-unknown-research";
      button.textContent = "Research";
      button.title = "A quick look answers here; a deeper run follows.";
      button.setAttribute("aria-label", "Research this product");
      button.addEventListener("click", () =>
        researchSubject({ label: state.unknownProduct }));
      card.appendChild(button);
      // On a site nothing reads, the product is half of it: the other half is
      // teaching Kriko the page, so the next one of its listings reads too.
      if (state.learnable && !state.researchOpen) {
        requestAgents();
        const learn = document.createElement("div");
        learn.innerHTML = `${agentRowMarkup(false)}${learnMarkup()}`;
        wireLearn(learn);
        paintLearn(learn);
        card.appendChild(learn);
      }
      slot.appendChild(card);
      return;
    }

    if (state.noAdapter && state.pipeline !== "result") {
      const card = document.createElement("div");
      card.className = "lite-verdict";
      card.dataset.verdict = "no-adapter";
      // A site with an installed adapter and a page that adapter doesn't
      // recognise (a category page, a search page) is not "nothing reads
      // this site" — that copy, and the offer to go write an adapter, is
      // only true when no pack has this host at all.
      if (state.hostKnown) {
        card.innerHTML = `
          <div class="lite-verdict-head">
            <span class="lite-verdict-word">Not a listing</span>
          </div>
          <p class="lite-verdict-say">Kriko reads this site's listings. This
            page isn't one.</p>
        `;
        slot.appendChild(card);
        return;
      }
      // The way out of "nothing reads this site" is on the card itself: the
      // page is already open, so the reader presses Learn this page and an
      // agent goes through it, rather than being sent to another window to
      // ask for the same thing.
      requestAgents();
      card.innerHTML = `
        <div class="lite-verdict-head">
          <span class="lite-verdict-word">Not read here</span>
        </div>
        <p class="lite-verdict-say">Nothing installed knows how to read this
          site yet. Kriko can learn it from this page.</p>
        ${agentRowMarkup(false)}
        ${learnMarkup()}
      `;
      wireLearn(card);
      paintLearn(card);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-verdict-btn lite-site-add";
      button.textContent = "Add this site";
      button.title = "In Kriko, an agent can write most of it.";
      button.setAttribute("aria-label", "Add this site; an agent can write most of the adapter");
      button.addEventListener("click", () =>
        openInApp("sites", appUrlFor("sites")));
      card.appendChild(button);
      slot.appendChild(card);
      return;
    }

    if (state.pipeline !== "result" || !state.result) return;

    const verdict = state.result.verdict || "";
    const step = state.result.next_step || null;
    // `recognised` with claims is the ordinary case and says nothing: a banner
    // on every successful answer is a banner nobody reads by the third one.
    if (verdict === "recognised" && !(step && step.say)) return;
    if (!verdict && !step) return;

    const card = document.createElement("div");
    card.className = "lite-verdict";
    card.dataset.verdict = verdict || "unknown";

    const head = document.createElement("div");
    head.className = "lite-verdict-head";
    head.innerHTML = `
      <span class="lite-verdict-word">${escapeHtml(VERDICT_WORD[verdict] || verdict)}</span>
      ${typeof state.result.score === "number" && verdict !== "recognised" && verdict !== "several"
        ? `<span class="lite-verdict-score">${(state.result.score * 100).toFixed(0)}%</span>`
        : ""}
    `;
    card.appendChild(head);

    const action = step && step.action && step.action !== "none" ? step.action : "";
    // A recognised product the packs hold nothing on is the one `recognised`
    // case worth a banner. The engine's sentence is the warrant, not the
    // headline: the card states the gap in a phrase and keeps the full
    // sentence as the card's title, so nothing is hidden and nothing is read
    // twice. `several` is the other long engine sentence the reader meets by
    // default; it gets the same treatment. `probably` stays word for word —
    // the engine's own question is the point of that card.
    const recognisedGap = verdict === "recognised" && action === "research";
    const shortSay = recognisedGap ? "Recognised. Nothing installed covers it yet."
      : verdict === "several" ? "One of several. Pick the one on the listing."
        : "";
    if (step && step.say) {
      if (shortSay) {
        card.title = step.say;
        const say = document.createElement("p");
        say.className = "lite-verdict-say";
        say.textContent = shortSay;
        say.title = step.say;
        card.appendChild(say);
      } else {
        const say = document.createElement("p");
        say.className = "lite-verdict-say";
        say.textContent = step.say;
        card.appendChild(say);
      }
    }

    const weighed = renderConsidered();
    if (weighed) card.appendChild(weighed);

    // `choose`: the page fits several products, and the reader can say which.
    // Each opens that product in the app, where all of what is known shows.
    if (action === "choose" && Array.isArray(step.choices) && step.choices.length) {
      const list = document.createElement("div");
      list.className = "lite-verdict-choices";
      for (const one of step.choices) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "lite-verdict-btn";
        button.textContent = one.label || one.subject_id;
        const route = `subject/${encodeURIComponent(one.subject_id)}`;
        button.addEventListener("click", () => openInApp(route, appUrlFor(route)));
        list.appendChild(button);
      }
      card.appendChild(list);
    }
    const label = recognisedGap ? "Research" : actionLabel(action, step);
    if (label) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-verdict-btn";
      button.textContent = label;
      if (recognisedGap) button.title = step.say;
      button.addEventListener("click", () => takeNextStep(action, step, button));
      card.appendChild(button);
    }

    slot.appendChild(card);
  }

  /* What the reader was actually shown, which is not always what was weighed.
   *
   * A verdict is a number, and a number nobody can decompose is a number
   * nobody can argue with. Each row here is one subject the engine considered
   * and each key's own reading — and the two readings that matter are the two
   * that point at different bugs: a key reading `conflict` is usually the
   * page, a key reading `absent` is usually the adapter. That sentence is in
   * `docs/HOW_IT_WORKS.md` and until now there was nowhere to act on it.
   */
  function renderConsidered() {
    const rows = (state.result.considered || []).slice(0, 3);
    if (!rows.length) return null;

    const box = document.createElement("details");
    box.className = "lite-weighed";
    const many = rows.length === 1 ? "1 subject weighed" : `${rows.length} subjects weighed`;
    box.innerHTML = `<summary>${escapeHtml(many)}</summary>`;

    for (const row of rows) {
      const one = document.createElement("div");
      one.className = "lite-weighed-row";
      const keys = (row.keys || [])
        .map((key) => `
          <span class="lite-weighed-key" data-how="${escapeHtml(key.how || "")}">
            ${escapeHtml(key.key)}
            <span class="lite-weighed-how">${escapeHtml(key.how || "")}</span>
          </span>`)
        .join("");
      one.innerHTML = `
        <div class="lite-weighed-label">
          ${escapeHtml(row.label || row.subject_id || "")}
          <span class="lite-weighed-score">${((row.score || 0) * 100).toFixed(0)}%</span>
        </div>
        <div class="lite-weighed-keys">${keys}</div>
      `;
      box.appendChild(one);
    }
    return box;
  }

  function takeNextStep(action, step, button) {
    if (action === "research") {
      const subject = (state.result.subjects || [])
        .find((one) => one.subject_id === step?.subject_id);
      return researchSubject(subject || (step?.subject_id ? step : null));
    }
    if (action === "install") {
      // No pack here covers this kind of product at all, which is not
      // something the panel can fix — installing or writing one is the app's
      // job, and raising it is the whole step.
      return openInApp("packs", appUrlFor("packs"));
    }
    // Everything else lands on search, and that is not a fallback: a page the
    // packs could not place is exactly when a reader wants to type the name
    // themselves, which is the thing the panel could never do.
    openSearch();
  }

  function renderClaimsHeader() {
    if (!claimsHeadEl) return;
    if (state.pipeline !== "result" || !state.result) {
      claimsHeadEl.innerHTML = "";
      return;
    }
    const total = state.result.claims.length;
    // Nothing to expand, collapse or count: the row would be three zeroes and
    // two controls that do nothing.
    if (!total) { claimsHeadEl.innerHTML = ""; return; }
    const allOpen  = state.openIds.size === total && total > 0;
    const allClose = state.openIds.size === 0;

    // Build once. On subsequent toggles, mutate in place so the entrance
    // animation does not retrigger.
    let head = claimsHeadEl.querySelector(".lite-claims-head");
    if (!head) {
      claimsHeadEl.innerHTML = `
        <div class="lite-claims-head">
          <div class="lite-claims-label">Risks · ${total}</div>
          <div class="lite-chip-group">
            <button type="button" class="lite-chip lite-chip-expand" data-on="${allOpen ? "1" : "0"}">
              + Expand all
            </button>
            <button type="button" class="lite-chip lite-chip-collapse" data-on="${allClose ? "1" : "0"}">
              − Collapse all
            </button>
          </div>
        </div>
      `;
      claimsHeadEl.querySelector(".lite-chip-expand").addEventListener("click", expandAll);
      claimsHeadEl.querySelector(".lite-chip-collapse").addEventListener("click", collapseAll);
      return;
    }

    // Update in place
    const label = head.querySelector(".lite-claims-label");
    if (label) label.textContent = `Risks · ${total}`;
    const expandBtn   = head.querySelector(".lite-chip-expand");
    const collapseBtn = head.querySelector(".lite-chip-collapse");
    if (expandBtn)   expandBtn.dataset.on   = allOpen  ? "1" : "0";
    if (collapseBtn) collapseBtn.dataset.on = allClose ? "1" : "0";
  }

  function renderClaimsList() {
    if (!claimsListEl) return;
    claimsListEl.dataset.compact = state.compact ? "1" : "0";
    // Keep the result tree while reconciling a live answer. Clearing it
    // restarts entrance animations and drops focus and collapsed groups.
    if (state.pipeline !== "result" || !state.result?.claims?.length
        || state.noAdapter || state.unknownProduct) claimsListEl.replaceChildren();

    if (state.pipeline === "analyzing") {
      const skel = document.createElement("div");
      skel.className = "lite-skeleton-list";
      for (let i = 0; i < 3; i++) {
        const row = document.createElement("div");
        row.className = "lite-skeleton";
        skel.appendChild(row);
      }
      claimsListEl.appendChild(skel);
      return;
    }

    if (state.pipeline === "error") {
      const err = document.createElement("div");
      err.className = "lite-error";
      err.textContent = state.errorMsg || "Analysis failed.";
      // One failure has a cause the reader can only fix in the extension's
      // own settings: the app is listening somewhere this extension is not
      // looking. That page is otherwise reachable only through the browser's
      // extension manager, which nobody opens while reading a listing.
      if (state.errorCode === "APP_NOT_RUNNING") {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "lite-open-app";
        button.textContent = "Extension settings";
        button.addEventListener("click", () =>
          chrome.runtime.sendMessage({ type: "OPEN_OPTIONS" }, () => {}));
        err.append(" ", button);
      }
      claimsListEl.appendChild(err);
      // A page the panel could not read is the page to learn: the reader is
      // already on it, and an agent can work out what to take from it.
      if (state.errorCode === "SCRAPE_FAILED" && state.learnable) {
        requestAgents();
        const learn = document.createElement("div");
        learn.className = "lite-error-learn";
        learn.innerHTML = `${agentRowMarkup(false)}${learnMarkup()}`;
        wireLearn(learn);
        paintLearn(learn);
        claimsListEl.appendChild(learn);
      }
      return;
    }

    // The no-adapter card above already says everything there is to say;
    // "hit Analyze" under it reads as Kriko not noticing its own answer.
    if (state.noAdapter || state.unknownProduct) return;

    if (state.pipeline === "idle" || !state.result) {
      const empty = document.createElement("div");
      empty.className = "lite-empty";
      empty.innerHTML = `
        <span class="lite-empty-icon">${iconSvg("search", { size: 18 })}</span>
        <div>No search yet. Press <b>Search this product</b>.</div>
      `;
      claimsListEl.appendChild(empty);
      return;
    }

    // An answer with no claims is not the same as no answer. If the packs
    // resolved this listing and hold nothing on it, that gap is the content.
    if (!state.result.claims || !state.result.claims.length) {
      const gaps = (state.result.subjects || []).filter((s) => !s.claims);
      if (!gaps.length) {
        // Deliberately nothing here when the verdict block has already spoken.
        // It says which of four things happened and what to do about it; a
        // second, vaguer sentence underneath ("no installed pack recognises
        // it") is the dead end this release removed, re-added below itself.
        if (!state.result.next_step && !state.result.verdict) {
          const empty = document.createElement("div");
          empty.className = "lite-empty";
          // Recognised with nothing known is a gap, not "not recognised":
          // the header above already names the product.
          empty.textContent = state.result.coverage === "MATCHED_NO_DATA"
            ? "Recognised, but the installed packs hold nothing about it yet."
            : "Nothing matched this listing. No pack recognises it.";
          claimsListEl.appendChild(empty);
        }
      }
      renderGaps();
      return;
    }

    // Group for display by the claim's own domain, retaining cards by key.
    // A domain is whatever string the answering pack's claim carries — engine
    // parts today, drill bits or anything else tomorrow. Title-casing each
    // word is a generic text transform, not a lookup keyed on car vocabulary
    // (extension-22, B145 audit): the old fixed map of engine/transmission/
    // emissions/... only ever covered the cars pack, and silently fell back
    // to a half-capitalized string for every domain a future pack invented.
    function titleCaseDomain(domain) {
      return domain.replace(/[a-z]+/gi, (word) =>
        word.charAt(0).toUpperCase() + word.slice(1));
    }

    // Grouped by the claim's own domain. There used to be a branch above this
    // one reading a `subsystems` array off the result, with a `display_tr`
    // label — a server field that has never existed and a site's own language
    // living in the client. Both are gone; this is the only path.
    let groups;
    {
      const byDomain = {};
      state.result.claims.forEach((claim, i) => {
        const d = (claim.domain || "other").toLowerCase().trim();
        if (!byDomain[d]) byDomain[d] = [];
        byDomain[d].push({ claim, idx: i });
      });
      groups = Object.entries(byDomain).map(([domain, items]) => ({
        iconDomain: domain,
        label: titleCaseDomain(domain),
        items,
      }));
    }

    const oldGroups = new Map([...claimsListEl.querySelectorAll(".lite-domain-group")]
      .map(group => [group.dataset.domain, group]));
    const oldCards = new Map([...claimsListEl.querySelectorAll(".lite-claim-anim")]
      .map(wrap => [wrap.dataset.claimKey, wrap]));
    const initial = oldGroups.size === 0;
    const keptGroups = new Set();
    const keptCards = new Set();
    let delayCounter = 0;
    for (const { iconDomain, label, items } of groups) {
      const high = items.filter(i => i.claim.severity === "high").length;
      const med  = items.filter(i => i.claim.severity === "medium").length;
      const low  = items.filter(i => i.claim.severity === "low").length;

      // Build severity dots summary
      const sevHtml = [];
      if (high) sevHtml.push('<span class="lite-domain-sev-dot" data-sev="high"></span>' + high);
      if (med)  sevHtml.push('<span class="lite-domain-sev-dot" data-sev="med"></span>' + med);
      if (low)  sevHtml.push('<span class="lite-domain-sev-dot" data-sev="low"></span>' + low);

      let groupEl = oldGroups.get(iconDomain);
      if (!groupEl) {
        groupEl = document.createElement("div");
        groupEl.className = "lite-domain-group";
        groupEl.dataset.domain = iconDomain;
        groupEl.dataset.open = "1";
        groupEl.innerHTML = `
        <button type="button" class="lite-domain-head" aria-expanded="true">
          <span class="lite-domain-icon">${domainIconSvg(iconDomain, { size: 15 })}</span>
          <span class="lite-domain-name">${escapeHtml(label)}</span>
          <span class="lite-domain-count">${items.length}</span>
          <span class="lite-domain-sev">${sevHtml.join('')}</span>
          <span class="lite-domain-toggle" aria-hidden="true">&minus;</span>
        </button>
        <div class="lite-domain-body"></div>
      `;
        const head = groupEl.querySelector(".lite-domain-head");
        head.addEventListener("click", () => {
          const isOpen = head.getAttribute("aria-expanded") === "true";
          head.setAttribute("aria-expanded", isOpen ? "false" : "true");
          groupEl.dataset.open = isOpen ? "0" : "1";
          groupEl.querySelector(".lite-domain-toggle").textContent = isOpen ? "+" : "\u2212";
        });
      }
      keptGroups.add(groupEl);
      groupEl.querySelector(".lite-domain-count").textContent = items.length;
      groupEl.querySelector(".lite-domain-sev").innerHTML = sevHtml.join("");

      // Populate body with claim cards
      const bodyEl = groupEl.querySelector(".lite-domain-body");
      items.forEach(({ claim }, position) => {
        const key = claimKeyOf(claim);
        let wrap = oldCards.get(key);
        if (!wrap) {
          wrap = document.createElement("div");
          wrap.className = "lite-claim-anim";
          wrap.dataset.claimKey = key;
          if (initial) wrap.style.animationDelay = (80 + delayCounter++ * 70) + "ms";
          else wrap.style.animation = "none";
        }
        keptCards.add(wrap);
        let card = wrap.querySelector(".lite-rc");
        const signature = JSON.stringify(claim);
        if (!card || wrap._claimSignature !== signature) {
          const next = renderClaimCard(claim, { open: state.openIds.has(key), compact: state.compact });
          if (card) {
            // Changed evidence updates the existing article without replaying
            // the wrapper's animation. Unchanged cards keep all their controls.
            card.innerHTML = next.innerHTML;
            card.dataset.sev = next.dataset.sev;
            card.dataset.strength = next.dataset.strength;
          } else {
            card = next;
            wrap.appendChild(card);
            card.addEventListener("click", (event) => {
              if (event.target.closest(".lite-rc-toggle")) toggleOne(key, card);
              const fact = event.target.closest(".lite-rc-factbtn");
              if (fact) checkFacts(wrap._claim, card);
              const mark = event.target.closest(".lite-rc-markbtn");
              if (mark) markClaim(wrap._claim, mark.dataset.verdict, card);
            });
          }
          wrap._claimSignature = signature;
        }
        wrap._claim = claim;
        updateClaimCard(card, { open: state.openIds.has(key), compact: state.compact });
        if (state.freshKeys.has(key) && !card.querySelector(".lite-rc-new")) {
          const title = card.querySelector(".lite-rc-title");
          const chip = document.createElement("span");
          chip.className = "lite-rc-new";
          chip.title = "Added while this answer was open";
          chip.textContent = "New";
          if (title) title.prepend(chip);
          card.dataset.fresh = "1";
        }
        // Re-assert any verdict this claim already carries: the list is
        // rebuilt on every expand-all and every fresh analysis, and a mark
        // that disappeared on redraw would read as one that failed to save.
        if (claim.claim_id && state.marks.has(claim.claim_id)) {
          markClaimCard(card, state.marks.get(claim.claim_id));
        }
        // Re-asserted on redraw for the same reason a mark is: the list is
        // rebuilt on every expand-all, and a verdict that vanished would read
        // as one that failed.
        if (claim.claim_id && state.facts.has(claim.claim_id)) {
          factClaimCard(card, state.facts.get(claim.claim_id),
            state.checkingFacts.has(claim.claim_id));
        }
        // Avoid even moving an already correctly placed card: DOM moves can
        // blur a focused button. New cards insert around the existing tree.
        const at = bodyEl.children[position];
        if (at !== wrap) bodyEl.insertBefore(wrap, at || null);
      });
      const at = claimsListEl.children[keptGroups.size - 1];
      if (at !== groupEl) claimsListEl.insertBefore(groupEl, at || null);
    }
    for (const wrap of oldCards.values()) if (!keptCards.has(wrap)) wrap.remove();
    for (const group of oldGroups.values()) if (!keptGroups.has(group)) group.remove();
    // Remove skeletons/gaps left from the first answer arriving.
    for (const child of [...claimsListEl.children]) if (!keptGroups.has(child)) child.remove();

    renderGaps();
  }

  /** "We know this car and have nothing on it" — the actionable emptiness.
   *
   * Distinct from "nothing matched", which is a coverage problem in the pack's
   * adapter and not something the reader can act on. A subject that resolved
   * with zero claims is a named gap, so it gets a button rather than an
   * apology.
   */
  function renderGaps() {
    if (!claimsListEl || !state.result) return;
    // Never on NOT_MATCHED: a page nothing adapted has no `subjects` at all
    // (the backend only resolves subject_ids when something matched), so this
    // filter already excludes it — there is no separate check to remember or
    // forget here.
    // A subject with zero *direct* claims is not a gap when claims reached
    // through its parts are already on screen — extension-4 (B145 audit): the
    // gap card used to say "no knowledge for this car" directly under 8
    // risks, because `subject.claims` only ever counts direct hits and never
    // the claims the panel reached through part expansion.
    const gaps = (state.result.claims || []).length
      ? []
      : (state.result.subjects || []).filter((s) => !s.claims);
    if (!gaps.length) return;

    // Ask what this would cost before drawing a single button — the sentence
    // has to be on screen the first time a reader sees "Research it", not
    // after they've already clicked it once.
    requestResearchPlane();
    const cost = costLine();

    // Re-render (rather than append) each time so a plane answer that arrives
    // after the first paint, or a poll updating one card's progress text,
    // does not leave stale duplicate cards behind.
    claimsListEl.querySelectorAll(".lite-gap").forEach((el) => el.remove());

    for (const subject of gaps) {
      const card = document.createElement("div");
      card.className = "lite-gap";
      // The explanation is the card's tooltip; the card itself is a phrase.
      card.title = "In the catalogue, but nothing researched for it yet.";
      card.innerHTML = `
        <div class="lite-gap-body">
          <div class="lite-gap-title">No knowledge on
            ${escapeHtml(subject.label)} yet</div>
          ${cost ? `<div class="lite-gap-cost">${escapeHtml(cost)}</div>` : ""}
        </div>
        <button type="button" class="lite-gap-btn" title="Research this product with your agent"
          aria-label="Research this product">Research</button>
      `;
      const button = card.querySelector(".lite-gap-btn");
      button.addEventListener("click", () => researchSubject(subject, button));
      claimsListEl.appendChild(card);
    }
  }

  // Backlog B15, re-pointed. The footer has always named whatever answered, so
  // that a stale answer was visible to anyone looking at the panel rather than
  // silently rendering as fresh. There is no server to be stale now — what a
  // reader needs to identify is WHOSE knowledge this is, because several packs
  // may be installed, none of them is authoritative, and "disable the pack
  // that is wrong" is only possible if the panel says which one spoke.
  function setPipeline(stage) {
    state.pipeline = stage;
    if (hostEl) hostEl.dataset.pipeline = stage;
  }

  function renderFooter() {
    if (!footerEl) return;
    if (state.pipeline !== "result" || !state.result) {
      footerEl.hidden = true;
      footerEl.textContent = "";
      return;
    }
    const packs = Array.isArray(state.result.packs) ? state.result.packs : [];
    footerEl.textContent = packs.map((p) => `${p.pack_id} · ${p.version}`).join("  |  ");
    // A separator only when something stands before the button.
    const join = () => { if (footerEl.textContent) footerEl.append(" · "); };

    // The app stored this same answer and can show the whole of it. Offered
    // only when the app said so: a link to a report that was never written is
    // worse than no link.
    // A button, not a link. An `<a href>` at the app's own port opens the
    // report in a *browser tab* — beside the desktop app the reader already
    // has running, which is not what "open in Kriko" means to anyone. The
    // button posts the route instead and the app raises itself; the tab is
    // kept only as the fallback for when no shell is listening.
    const routes = state.result.app_routes || {};
    const urls = state.result.app_urls || {};
    if (state.result.app_route || state.result.app_url) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-open-app";
      button.textContent = "Open in Kriko";
      button.addEventListener("click", () =>
        openInApp(state.result.app_route || "check", state.result.app_url));
      join();
      footerEl.append(button);
    }

    // What a reader does with the answer once read: line it up against
    // another. Offered only when the app handed back a route for it, because a
    // button that opens an empty screen teaches the reader the button is broken.
    if (routes.compare) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-open-app";
      button.textContent = "Compare";
      button.addEventListener("click", () => openInApp(routes.compare, urls.compare));
      join();
      footerEl.append(button);
    }
    footerEl.hidden = false;
  }

  function renderProductActions() {
    const knownProduct = (state.result?.subjects || []).some((one) => one.kind === "product");
    const find = bodyEl?.querySelector(".lite-find-product");
    const research = bodyEl?.querySelector(".lite-research-product");
    if (find) find.textContent = knownProduct ? "Search again" : "Search packs";
    if (research) research.hidden = knownProduct;
  }

  function renderBody() {
    if (!bodyEl) return;
    const scrollTop = bodyEl.scrollTop;
    const top = bodyEl.getBoundingClientRect().top;
    const anchor = [...(claimsListEl?.querySelectorAll(".lite-rc") || [])]
      .find(card => card.getBoundingClientRect().bottom > top);
    const anchorTop = anchor?.getBoundingClientRect().top;
    const focused = shadow.activeElement;
    renderListingHeader();
    renderBuyer();
    renderQueue();
    renderDecide();
    renderCriticalAlerts();
    renderCta();
    renderStatus();
    renderProductActions();
    renderSearch();
    renderLive();
    renderResearch();
    renderVerdict();
    renderClaimsHeader();
    renderClaimsList();
    renderListingDetails();
    renderFooter();
    // New cards above the one being read should not push it out of view.
    bodyEl.scrollTop = scrollTop + (anchor?.isConnected
      ? anchor.getBoundingClientRect().top - anchorTop : 0);
    if (focused?.isConnected && shadow.activeElement !== focused) {
      focused.focus({ preventScroll: true });
    }
  }

  // ─── Interactions ─────────────────────────────────────────────────────
  function toggleOne(key, cardEl) {
    if (state.openIds.has(key)) state.openIds.delete(key);
    else state.openIds.add(key);
    updateClaimCard(cardEl, { open: state.openIds.has(key) });
    // Update Expand/Collapse-all chip "on" state
    renderClaimsHeader();
  }
  function setAllOpen(open) {
    if (!state.result) return;
    state.openIds = open
      ? new Set(state.result.claims.map(claimKeyOf))
      : new Set();
    // Mutate cards in place so each one runs its own expand/collapse animation
    // — re-rendering the list would retrigger the entrance animation.
    const cards = claimsListEl.querySelectorAll(".lite-rc");
    cards.forEach((card) => updateClaimCard(card, { open }));
    renderClaimsHeader();
  }
  function expandAll()   { setAllOpen(true); }
  function collapseAll() { setAllOpen(false); }
})();
