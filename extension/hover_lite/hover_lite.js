/* Hover Lite — floating analyzer card injected into Sahibinden / carchecker
   listing pages via Shadow DOM. The toolbar action toggles visibility.

   State machine:
     idle      → no analysis run yet (button: "Analyze current page")
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
  const { renderClaimCard, updateClaimCard, markClaimCard, factClaimCard } =
    window.__KrikoPanelClaimCard;

  const HOST_TAG = "kriko-panel-host";

  /* What the panel says before anything has been analysed.
   *
   * It used to name one site — "Open a Sahibinden listing, then analyze." —
   * which was the last of the site's own knowledge left in the client after
   * every other trace of it was pushed into the pack's adapter. The panel only
   * ever mounts on a page an adapter matched, so naming *which* site was never
   * information the reader needed; it was only a sentence that would be wrong
   * on the second site and unnoticed on the third. */
  const IDLE_HINT = "Analyze this page to see what is known about it.";

  /* The engine's verdict, as a word the panel shows. Three of the four are
   * worth a banner; `recognised` is the ordinary case and gets none. */
  const VERDICT_WORD = {
    recognised: "Recognised",
    probably: "Probably this one",
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
    openIds: new Set(),        // expanded claim indices
    detailsOpen: false,        // Listing-details panel collapsed by default
    openDetailRows: new Set(), // expanded rows inside listing details
    pipeline: "idle",          // idle | analyzing | result | error
    result: null,              // AnalyzeResponse
    errorMsg: null,
    errorCode: null,
    listingMeta: null,         // derived from background metadata response
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
    // B148: the quick look's answer, kept while the deeper run goes on.
    // `{ assumed, risks, dropped }` or null.
    researchQuick: null,
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
  // The panel's CSS asks for the same stack it always did; with nothing
  // preloaded it lands on the system face, which is what the reader's other
  // applications use. Guarded by a test that fails on a remote URL anywhere
  // in the extension.

  // ─── Helpers ──────────────────────────────────────────────────────────
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
  // sahibinden.com here, which meant installing a pack for a second listing
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

  // Apply entry helper
  function applyEntry(entry) {
    if (!entry) return;
    if (entry.listing || (entry.ok && entry.result)) {
      state.listingMeta = deriveListingMeta(entry);
    }
    if (entry.ok && entry.result) {
      // An answer means something read this page after all.
      state.noAdapter = false;
      state.unknownProduct = "";
      state.errorCode = null;
      state.result = entry.result;
      state.errorMsg = null;
      setPipeline("result");
      state.openIds = new Set();
    } else if (entry.ok === false) {
      // extension-5/extension-8 (B145 audit): the stored-result path (a page
      // reloaded onto a cached entry, or the panel reopened) used to ignore
      // `entry.code` entirely, so NO_ADAPTER rendered as a red error and
      // APP_NOT_RUNNING hid the settings button the live ANALYZE path already
      // knows to show. Both paths now read the same code.
      state.errorCode = entry.code || null;
      state.unknownProduct = "";
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
          if (response?.code === "APP_NOT_RUNNING") {
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

  // The sentence a reader sees before the button does anything at all. Named
  // *before* the click, not after: the whole point of asking the plane first
  // is that "this spends money" cannot be information the reader gets from
  // the bill.
  function costLine() {
    const plane = state.researchPlane;
    if (!plane) return "";
    if (plane.backend === "api") {
      const cap = Number(plane.budget_usd || 0);
      return cap > 0
        ? `Costs money — this run is capped at $${cap.toFixed(2)} of your API keys.`
        : "Costs money — spent through your configured API keys.";
    }
    return "Costs nothing — runs through your coding agent.";
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
    state.researchName = subject?.label || state.searchQuery || state.listingMeta?.title || document.title || "";
    state.researchContext = "";
    state.researchOpen = true;
    state.researchJob = null;
    state.researchQuick = null;
    state.researchState = "";
    state.researchMessage = "";
    requestResearchPlane();
    renderResearch();
  }

  /* One button (B148). A name the packs know is researched into them; one
   * they do not gets a quick look answered here in a minute or two, and the
   * deeper draft run starts beside it. The reader used to choose between two
   * buttons whose difference they had no way to know. */
  function startResearch() {
    if (state.researching || !state.researchPlane) return;
    const subject_id = state.researchTarget?.subject_id;
    const q = [state.researchName.trim(), state.researchContext.trim()].filter(Boolean).join(" — ");
    if (!subject_id && !q) return;
    const cap = Number(state.researchPlane.budget_usd);
    state.researching = subject_id || q;
    state.researchState = "starting";
    state.researchMessage = "Looking it up…";
    state.researchAnswers = {};
    state.researchTold = {};
    state.researchQuick = null;
    renderResearch();
    chrome.runtime.sendMessage({ type: "RESEARCH_PRODUCT", payload: {
      ...(subject_id ? { subject_id } : { q, allow_draft: true, url: location.href }),
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
      state.researchMessage = response.job.kind === "quick_look" ? "Looking it up…" : "Queued";
      renderResearch();
      pollResearchJob(response.job.job_id);
    });
  }

  /* The quick look finished — well or not. Keep what it found, then follow
   * the deeper run it started beside, so the panel keeps saying what is
   * happening rather than ending on "done" while the real work goes on. */
  function quickLookDone(job) {
    const result = job.result || {};
    state.researchQuick = {
      assumed: result.assumed || "",
      risks: Array.isArray(result.risks) ? result.risks : [],
      dropped: Number(result.dropped) || 0,
    };
    const deepen = result.deepen_job_id || state.researchJob?.deepen_job_id;
    const found = state.researchQuick.risks.length;
    const said = job.state === "succeeded"
      ? (found ? `${found} thing${found === 1 ? "" : "s"} to know, from a quick look.`
        : "The quick look found nothing it could source.")
      : "The quick look did not finish.";
    if (!deepen) {
      state.researching = null;
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

  function renderResearch() {
    const slot = bodyEl?.querySelector(".lite-research-slot");
    if (!slot) return;
    if (!state.researchOpen) { slot.innerHTML = ""; return; }
    const busy = Boolean(state.researching);
    const target = state.researchTarget;
    const draft = state.researchJob?.kind === "pack_author";
    const cost = costLine();
    const asked = (state.researchJob?.attention?.questions || []).filter((q) => q && q.id);
    slot.innerHTML = `
      <section class="lite-research" data-state="${escapeHtml(state.researchState)}">
        <strong>Research this product</strong>
        ${target ? `<p>${escapeHtml(target.label || target.subject_id)}</p>` : `
          <label>Product name<input class="lite-research-name" maxlength="350" ${busy ? "disabled" : ""} /></label>
          <label>Context<textarea class="lite-research-context" maxlength="140" ${busy ? "disabled" : ""}></textarea></label>`}
        <p class="lite-gap-cost">${escapeHtml(cost || state.researchPlaneError || "Checking research costs…")}</p>
        <p class="lite-research-status" role="status">${escapeHtml(state.researchMessage)}</p>
        ${state.researchQuick?.risks.length ? `<div class="lite-quick">
          ${state.researchQuick.assumed ? `<p class="lite-quick-assumed">Taken as: ${escapeHtml(state.researchQuick.assumed)}</p>` : ""}
          <div class="lite-quick-cards"></div>
        </div>` : ""}
        ${asked.length ? `<div class="lite-asked" aria-live="polite">
          <p class="lite-asked-lede"><span class="lite-asked-mark" aria-hidden="true">?</span>${busy
            ? "Your agent has a question. Pick an answer and it hears it now."
            : "Your agent had a question and went with its guess. Pick an answer to run it again."}</p>
          ${asked.map((q, qi) => `<fieldset class="lite-asked-q"><legend>${escapeHtml(q.ask)}</legend>
            ${(q.options || []).length ? `<div class="lite-chips">${q.options.map((o, oi) => `
              <button type="button" class="lite-chip" data-q="${qi}" data-o="${oi}"
                aria-pressed="${state.researchAnswers[q.id] === o}">${escapeHtml(o)}${
                o === q.default && !state.researchAnswers[q.id] ? ` <span class="lite-chip-note">its guess</span>` : ""}</button>`).join("")}</div>`
              : `<p class="lite-told">Answer this one in Kriko: open the research job below.</p>`}
            ${state.researchTold[q.id] ? `<p class="lite-told">${escapeHtml(state.researchTold[q.id])}</p>` : ""}
          </fieldset>`).join("")}
        </div>` : ""}
        ${!busy ? `<button type="button" class="lite-research-start" ${!state.researchPlane ? "disabled" : ""}>${state.researchJob ? "Research again" : "Research this product"}</button>` : ""}
        ${busy && state.researchJob ? `<button type="button" class="lite-research-cancel" ${state.cancelling ? "disabled" : ""}>${state.cancelling ? "Cancelling…" : "Cancel"}</button>` : ""}
        ${state.researchJob ? `<button type="button" class="lite-research-output">${draft ? "Open exact draft output" : "Open research job"}</button>` : ""}
        ${state.researchPlaneError ? `<button type="button" class="lite-research-cost-retry">Retry cost check</button>` : ""}
      </section>`;
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
    const quickCards = slot.querySelector(".lite-quick-cards");
    (quickCards ? state.researchQuick.risks : []).forEach((risk, i) => {
      const wrap = document.createElement("div");
      wrap.className = "lite-claim-anim";
      wrap.style.animationDelay = (i * 70) + "ms";
      const card = renderClaimCard(risk, { open: false, compact: state.compact });
      card.querySelector(".lite-rc-toggle")?.addEventListener("click", () =>
        updateClaimCard(card, { open: card.dataset.open !== "1" }));
      // Where the line came from, in its own words: a quick look is not a
      // stored claim, so the page and its quote are the only warrant it has.
      const src = (risk.sources || [])[0];
      const body = card.querySelector(".lite-rc-body");
      if (src?.url && body) {
        const cite = document.createElement("blockquote");
        cite.className = "lite-quick-src";
        cite.textContent = `\u201c${src.quote}\u201d `;
        const link = document.createElement("a");
        link.href = src.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = src.domain || src.url;
        cite.appendChild(link);
        body.appendChild(cite);
      }
      wrap.appendChild(card);
      quickCards.appendChild(wrap);
    });
    slot.querySelector(".lite-research-cancel")?.addEventListener("click", cancelResearch);
    slot.querySelectorAll(".lite-chip").forEach((chip) => chip.addEventListener("click", () => {
      const question = asked[Number(chip.dataset.q)];
      const option = question?.options?.[Number(chip.dataset.o)];
      if (question && option !== undefined) answerQuestion(question, option);
    }));
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

  // Progress shown in the gap card itself — the panel stays put, and the
  // reader watches the run land without ever leaving the listing they were
  // reading. Polled rather than pushed: the panel has no open connection to
  // the app, and a job id is cheap to ask about again.
  function pollResearchJob(jobId) {
    if (state.researchJob?.job_id !== jobId || !state.researching) return;
    chrome.runtime.sendMessage({ type: "JOB_STATUS", payload: { job_id: jobId } }, (response) => {
      if (state.researchJob?.job_id !== jobId || !state.researching) return;
      if (chrome.runtime.lastError || !response?.ok || !response.job) {
        state.researchMessage = "Cannot check progress. The job may still be running; open its exact output below or cancel.";
        renderResearch();
        setTimeout(() => pollResearchJob(jobId), 3000);
        return;
      }
      const job = response.job;
      state.researchJob = { ...state.researchJob, ...job, job_id: jobId };
      state.researchState = job.state;
      const done = job.done || ["succeeded", "cancelled", "failed", "interrupted"].includes(job.state);
      if (!done) {
        const pct = Math.max(0, Math.min(100, Math.round((job.progress || 0) * 100)));
        state.researchMessage = `${job.message || job.state || "Researching"} · ${pct}%`;
        renderResearch();
        setTimeout(() => pollResearchJob(jobId), 1000);
        return;
      }
      if (state.researchJob.kind === "quick_look" && job.state !== "cancelled") {
        quickLookDone(job);
        return;
      }
      state.researching = null;
      state.cancelling = false;
      state.researchMessage = job.state === "cancelled" ? "Research cancelled."
        : job.state === "succeeded" ? (state.researchJob.kind === "pack_author"
          ? (job.result?.installed
            ? "Deeper research done and installed. Refreshing this listing…"
            : `${state.researchQuick ? "Deeper research done. " : ""}A draft pack is ready in Kriko — it could not install itself; open it there.`)
          : job.result?.brief && !job.result?.documents
            ? "Brief ready. Open the research job to continue with your agent."
            : "Research completed. Open the research job for findings.")
        : job.state === "interrupted" ? "Research interrupted by an app restart."
        : `Research failed. ${job.error || job.message || "Open the job for details."}`;
      renderResearch();
      // B148: the pack the deep run installed is knowledge now, so the
      // listing is asked again and its cards arrive without a press.
      if (job.state === "succeeded" && job.result?.installed) triggerAnalyze(true);
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
    if (request && request.type === "TOGGLE_HOVER_LITE") {
      togglePanel();
    }
  });

  // runtime.sendMessage broadcasts only reach extension UI surfaces, not
  // content scripts, so we rely on chrome.storage.session instead: background
  // writes the result under STORAGE_KEY_PREFIX + url, and onChanged fires here
  // even when the panel is closed (state stays warm for the next open). This
  // requires background to grant content scripts session access via
  // setAccessLevel(TRUSTED_AND_UNTRUSTED_CONTEXTS) — without it this listener
  // never fires (issue #28).
  const STORAGE_KEY = "kriko_result_" + window.location.href;
  const STAGE_KEY = "kriko_stage_" + window.location.href;
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "session") return;
    // The stage first: it is written before the result it narrates, and a
    // change event carrying both should not paint the answer and then the
    // sentence that says the answer is still coming.
    if (STAGE_KEY in changes && changes[STAGE_KEY].newValue) {
      state.stage = changes[STAGE_KEY].newValue;
      renderStatus();
    }
    if (!(STORAGE_KEY in changes)) return;
    const next = changes[STORAGE_KEY].newValue;
    if (!next) return;
    applyEntry(next);
  });

  // ─── Mount / unmount with animation ───────────────────────────────────
  function mount() {
    if (state.mounted) return;
    state.mounted = true;
    state.closing = false;
    state.visible = true;

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

    // Wire panel-level handlers
    panel.addEventListener("pointerdown", onPointerDown);
    panel.addEventListener("pointermove", onPointerMove);
    panel.addEventListener("pointerup", onPointerUp);
    panel.addEventListener("pointercancel", onPointerUp);

    // A press of either control is the reader asking again on purpose, so
    // both bypass the cache; the automatic run at page load calls
    // triggerAnalyze() directly with no argument and gets the cache.
    ctaBtn.addEventListener("click", () => triggerAnalyze(true));
    densityBtn.addEventListener("click", () => triggerAnalyze(true));
    searchBtn.addEventListener("click", () =>
      (state.searchOpen ? closeSearch() : openSearch()));
    closeBtn.addEventListener("click", closePanel);
    panel.querySelector(".lite-find-product").addEventListener("click", openSearch);
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

    // Only while the panel is on screen. A closed panel that kept asking
    // would be a request a second, forever, on every tab left open.
    stopLive();
    pollLive();

    // Strip the mount flag so future state changes don't re-trigger the entry
    // animation.
    setTimeout(() => { if (panel) delete panel.dataset.mounting; }, 280);
  }

  function unmount() {
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
    const left = state.side === "left" ? PAD_DOCK : (window.innerWidth - PANEL_W - PAD_DOCK);
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
    const dragDots = `<svg class="lite-drag-dots" width="14" height="20" viewBox="0 0 14 20" aria-hidden="true"><g fill="currentColor"><rect x="1" y="2" width="3" height="3"/><rect x="10" y="2" width="3" height="3"/><rect x="1" y="8.5" width="3" height="3"/><rect x="10" y="8.5" width="3" height="3"/><rect x="1" y="15" width="3" height="3"/><rect x="10" y="15" width="3" height="3"/></g></svg>`;

    return `
      <header class="lite-header">
        ${dragDots}
        <div class="lite-titlebox">
          <div class="lite-title">Kriko</div>
          <div class="lite-subtitle">drag to move</div>
        </div>
        <button type="button" class="lite-iconbtn lite-btn-density"
                title="Refresh analysis" aria-label="Refresh analysis">
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
        <div class="lite-alerts-slot"></div>
        <div class="lite-cta-wrap">
          <button type="button" class="lite-cta">
            <span class="lite-cta-icon">${iconSvg("scan", { size: 15 })}</span>
            <span class="lite-cta-label">Analyze current page</span>
          </button>
          <p class="lite-status">${escapeHtml(IDLE_HINT)}</p>
        </div>
        <div class="lite-product-actions">
          <button type="button" class="lite-find-product">Find in installed packs</button>
          <button type="button" class="lite-research-product">Research this product</button>
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
    countsEl.innerHTML = `
      <div class="lite-counts">
        <span class="lite-count" data-sev="high">
          <span class="dot"></span>
          <span class="num">${c.high}</span>
          <span class="lbl">HIGH</span>
        </span>
        <span class="lite-count" data-sev="medium">
          <span class="dot"></span>
          <span class="num">${c.medium}</span>
          <span class="lbl">MED</span>
        </span>
        <span class="lite-count" data-sev="low">
          <span class="dot"></span>
          <span class="num">${c.low}</span>
          <span class="lbl">LOW</span>
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
        <span class="lite-counts-total">${c.total} RISKS</span>
      </div>
    `;
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
            ? `<div class="lite-listing-engine">${escapeHtml(lm.identity_line)}</div>`
            : `<div class="lite-listing-engine" data-unresolved="1">Not recognised — no pack matched this page</div>`}
      </div>
    `;
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
          `<span class="lite-tag" data-tone="${r.tone}">${escapeHtml(p)}</span>`
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

  function renderCta() {
    if (!ctaBtn) return;
    const isAnalyzing = state.pipeline === "analyzing";
    const hasResult   = state.pipeline === "result";
    ctaBtn.dataset.analyzing = isAnalyzing ? "1" : "0";
    ctaBtn.disabled = isAnalyzing;
    const iconName = isAnalyzing || hasResult ? "refresh" : "scan";
    const label = isAnalyzing
      ? "Analyzing…"
      : (hasResult ? "Refresh analysis" : "Analyze current page");
    const iconWrap = ctaBtn.querySelector(".lite-cta-icon");
    iconWrap.innerHTML = iconSvg(iconName, { size: 15 });
    iconWrap.classList.toggle("spin", isAnalyzing);
    ctaBtn.querySelector(".lite-cta-label").textContent = label;
    if (densityBtn) densityBtn.dataset.spinning = isAnalyzing ? "1" : "0";
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
        <div class="lite-live-head">Also running now</div>
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
        ? `${row.note}${row.progress ? ` · ${Math.round(row.progress * 100)}%` : ""}`
        : "";
      item.textContent = note
        ? `${row.name} · ${who} · ${note}`
        : `${row.name} · ${who}`;
      list.appendChild(item);
    }
  }

  /** Ask what is running, and keep asking while the panel is open.
   *
   * Polled rather than streamed, for the reason `pollResearchJob` is: the
   * panel holds no open connection to the app, and a content script that did
   * would hold it open on every listing page the reader leaves in a tab. */
  function pollLive() {
    if (!state.visible) { stopLive(); return; }
    chrome.runtime.sendMessage({ type: "OPERATIONS", payload: { limit: 6 } }, (response) => {
      if (!state.visible) return;
      if (chrome.runtime.lastError || !response?.ok) {
        // An unreachable app is not worth a banner here: the analysis path
        // above already says so, loudly, and this section is an aside. It
        // falls quiet instead, which is what "nothing is running" looks like
        // and is the honest reading of "cannot tell".
        state.live = [];
      } else {
        state.live = Array.isArray(response.feed?.items) ? response.feed.items : [];
      }
      renderLive();
      if (state.visible) state.liveTimer = setTimeout(pollLive, 2000);
    });
  }

  function stopLive() {
    if (state.liveTimer) clearTimeout(state.liveTimer);
    state.liveTimer = null;
  }

  function renderStatus() {
    if (!statusEl) return;
    if (state.pipeline === "idle") {
      statusEl.textContent = IDLE_HINT;
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
      statusEl.textContent = state.errorMsg || "Analysis failed.";
      statusEl.style.display = "";
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
    if (action === "confirm") return "Not this one — search";
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

  function openSearch() {
    state.searchOpen = true;
    renderSearch();
    const field = bodyEl && bodyEl.querySelector(".lite-search-field");
    if (field) field.focus();
  }

  function runSearch(text) {
    const query = String(text || "").trim();
    state.searchQuery = query;
    if (searchTimer) clearTimeout(searchTimer);
    if (query.length < SEARCH_MIN) {
      state.searchResults = null;
      state.searchBusy = false;
      return renderSearchResults();
    }
    // Debounced, and every reply carries the id of the keystroke that asked
    // for it: without that, a slow answer to "gol" lands after a fast one to
    // "golf" and the reader watches their own typing undo itself.
    const runId = ++searchRunId;
    state.searchBusy = true;
    renderSearchResults();
    searchTimer = setTimeout(() => {
      chrome.runtime.sendMessage({ type: "SEARCH", payload: { q: query } }, (reply) => {
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
    }, SEARCH_DEBOUNCE_MS);
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
                 aria-label="Search the installed packs" />
          <button type="button" class="lite-search-close"
                  title="Close search" aria-label="Close search">
            ${iconSvg("x", { size: 14, strokeWidth: 2 })}
          </button>
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
    renderSearchResults();
  }

  function closeSearch() {
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
        `<p class="lite-search-note">Type at least ${SEARCH_MIN} characters. ` +
        `Every word has to land somewhere — a name, an alias, or one of the ` +
        `values the thing is made of.</p>`;
      return;
    }
    if (!state.searchResults.length) {
      box.innerHTML =
        `<p class="lite-search-note">Nothing in the installed packs matches ` +
        `that. Fewer words usually finds more.</p>`;
      return;
    }

    for (const row of state.searchResults) {
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
    const slot = bodyEl.querySelector(".lite-verdict-slot");
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
          <strong class="lite-unknown-name"></strong> yet. A quick look answers
          here in a minute or two, and a deeper run keeps going after.</p>
      `;
      card.querySelector(".lite-unknown-name").textContent = state.unknownProduct;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-verdict-btn lite-unknown-research";
      button.textContent = "Research this product";
      button.addEventListener("click", () =>
        researchSubject({ label: state.unknownProduct }));
      card.appendChild(button);
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
          <p class="lite-verdict-say">Kriko reads listings on this site, but
            this page isn't one. Open a specific car's listing and analyze
            that.</p>
        `;
        slot.appendChild(card);
        return;
      }
      card.innerHTML = `
        <div class="lite-verdict-head">
          <span class="lite-verdict-word">Not read here</span>
        </div>
        <p class="lite-verdict-say">Nothing installed knows how to read this
          site yet. Teaching Kriko a site is a few minutes in the app, and an
          agent can write most of it.</p>
      `;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-verdict-btn";
      button.textContent = "Add this site";
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
      ${typeof state.result.score === "number" && verdict !== "recognised"
        ? `<span class="lite-verdict-score">${(state.result.score * 100).toFixed(0)}%</span>`
        : ""}
    `;
    card.appendChild(head);

    if (step && step.say) {
      const say = document.createElement("p");
      say.className = "lite-verdict-say";
      say.textContent = step.say;
      card.appendChild(say);
    }

    const weighed = renderConsidered();
    if (weighed) card.appendChild(weighed);

    const action = step && step.action && step.action !== "none" ? step.action : "";
    const label = actionLabel(action, step);
    if (label) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-verdict-btn";
      button.textContent = label;
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
    const allOpen  = state.openIds.size === total && total > 0;
    const allClose = state.openIds.size === 0;

    // Build once. On subsequent toggles, mutate in place so the entrance
    // animation does not retrigger.
    let head = claimsHeadEl.querySelector(".lite-claims-head");
    if (!head) {
      claimsHeadEl.innerHTML = `
        <div class="lite-claims-head">
          <div class="lite-claims-label">RISKS · ${total}</div>
          <div class="lite-chip-group">
            <button type="button" class="lite-chip lite-chip-expand" data-on="${allOpen ? "1" : "0"}">
              + EXPAND ALL
            </button>
            <button type="button" class="lite-chip lite-chip-collapse" data-on="${allClose ? "1" : "0"}">
              − COLLAPSE ALL
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
    if (label) label.textContent = `RISKS · ${total}`;
    const expandBtn   = head.querySelector(".lite-chip-expand");
    const collapseBtn = head.querySelector(".lite-chip-collapse");
    if (expandBtn)   expandBtn.dataset.on   = allOpen  ? "1" : "0";
    if (collapseBtn) collapseBtn.dataset.on = allClose ? "1" : "0";
  }

  function renderClaimsList() {
    if (!claimsListEl) return;
    claimsListEl.dataset.compact = state.compact ? "1" : "0";
    claimsListEl.innerHTML = "";

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
        <div>No analysis yet. Press <b>Analyze current page</b>.</div>
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
          empty.textContent =
            "Nothing matched this listing. No installed pack recognises it.";
          claimsListEl.appendChild(empty);
        }
      }
      renderGaps();
      return;
    }

    // Group for display, by the claim's own domain. Global claim indices into
    // state.result.claims are preserved so toggleOne/setAllOpen keep working.
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

      const groupEl = document.createElement("div");
      groupEl.className = "lite-domain-group";
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

      // Populate body with claim cards
      const bodyEl = groupEl.querySelector(".lite-domain-body");
      items.forEach(({ claim, idx }) => {
        const wrap = document.createElement("div");
        wrap.className = "lite-claim-anim";
        wrap.style.animationDelay = (80 + delayCounter * 70) + "ms";
        delayCounter++;
        const card = renderClaimCard(claim, { open: state.openIds.has(idx), compact: state.compact });
        const btn = card.querySelector(".lite-rc-toggle");
        btn.addEventListener("click", () => toggleOne(idx, card));
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
        const factBtn = card.querySelector(".lite-rc-factbtn");
        if (factBtn) {
          factBtn.addEventListener("click", (event) => {
            event.stopPropagation(); // the card header toggles on click
            checkFacts(claim, card);
          });
        }
        card.querySelectorAll(".lite-rc-markbtn").forEach((markBtn) => {
          markBtn.addEventListener("click", (event) => {
            event.stopPropagation(); // the card header toggles on click
            markClaim(claim, markBtn.dataset.verdict, card);
          });
        });
        wrap.appendChild(card);
        bodyEl.appendChild(wrap);
      });

      // Wire group toggle
      const head = groupEl.querySelector(".lite-domain-head");
      const toggleSpan = groupEl.querySelector(".lite-domain-toggle");
      head.addEventListener("click", () => {
        const isOpen = head.getAttribute("aria-expanded") === "true";
        head.setAttribute("aria-expanded", isOpen ? "false" : "true");
        groupEl.dataset.open = isOpen ? "0" : "1";
        toggleSpan.textContent = isOpen ? "+" : "\u2212";
      });

      claimsListEl.appendChild(groupEl);
    }

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
      card.innerHTML = `
        <div class="lite-gap-body">
          <div class="lite-gap-title">Couldn't find the knowledge on
            ${escapeHtml(subject.label)} — research it with your agent?</div>
          <div class="lite-gap-note">This is in the catalogue, but no claim has been
            researched for it yet.</div>
          ${cost ? `<div class="lite-gap-cost">${escapeHtml(cost)}</div>` : ""}
        </div>
        <button type="button" class="lite-gap-btn">Research it</button>
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
    footerEl.textContent = packs.length
      ? packs.map((p) => `${p.pack_id} · ${p.version}`).join("  |  ")
      : "unknown";

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
      footerEl.append(" · ", button);
    }

    // The panel's job ends at "here is what to worry about"; these two are
    // what a reader does with that. Both were app-only screens, so a reader
    // who had just read the claims had to go and find the same listing again
    // by hand — the answer is already stored under an id, and the id is right
    // here.
    //
    // Offered only when the app handed back a route for them: a stored answer
    // is what makes either screen possible, and a button that opens an empty
    // question sheet teaches the reader that the button does not work.
    for (const [key, label] of [
      ["questions", "Ask the seller"],
      ["compare", "Compare"],
    ]) {
      if (!routes[key]) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lite-open-app";
      button.textContent = label;
      button.addEventListener("click", () => openInApp(routes[key], urls[key]));
      footerEl.append(" · ", button);
    }
    footerEl.hidden = false;
  }

  function renderBody() {
    if (!bodyEl) return;
    renderListingHeader();
    renderCriticalAlerts();
    renderCta();
    renderStatus();
    renderSearch();
    renderLive();
    renderResearch();
    renderVerdict();
    renderClaimsHeader();
    renderClaimsList();
    renderListingDetails();
    renderFooter();
  }

  // ─── Interactions ─────────────────────────────────────────────────────
  function toggleOne(idx, cardEl) {
    if (state.openIds.has(idx)) state.openIds.delete(idx);
    else state.openIds.add(idx);
    updateClaimCard(cardEl, { open: state.openIds.has(idx) });
    // Update Expand/Collapse-all chip "on" state
    renderClaimsHeader();
  }
  function setAllOpen(open) {
    if (!state.result) return;
    state.openIds = open
      ? new Set(state.result.claims.map((_, i) => i))
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
