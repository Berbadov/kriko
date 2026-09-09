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
  const { renderRiskCard, updateRiskCard, markRiskCard, factRiskCard } =
    window.__KrikoPanelRiskCard;

  const HOST_TAG = "kriko-panel-host";

  // ─── State ────────────────────────────────────────────────────────────
  const state = {
    mounted: false,            // panel currently in DOM
    closing: false,            // exit animation in flight
    visible: false,            // logical visibility (mounted && !closing)
    side: "right",             // initial dock side
    pos: null,                 // {left, top} once dragged
    dragging: false,
    compact: false,
    openIds: new Set(),        // expanded risk indices
    detailsOpen: false,        // Listing-details panel collapsed by default
    openDetailRows: new Set(), // expanded rows inside listing details
    summaryExpanded: false,    // Summary card line-clamped by default
    pipeline: "idle",          // idle | analyzing | result | error
    result: null,              // AnalyzeResponse
    errorMsg: null,
    errorCode: null,
    listingMeta: null,         // derived from background metadata response
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
  };

  // ─── Element refs (populated in mount) ────────────────────────────────
  let hostEl = null;
  let shadow = null;
  let panel = null;
  let countsEl = null;
  let bodyEl = null;
  let statusEl = null;
  let ctaBtn = null;
  let risksHeadEl = null;
  let risksListEl = null;
  let densityBtn = null;
  let closeBtn = null;
  let footerEl = null;

  let closeTimer = null;

  // Memo refs so summary / listing-details only rebuild when the underlying
  // data changes — toggles flip data-attributes in place so the CSS
  // animations can play.
  let lastSummaryText = null;
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

  // What the panel puts above the risks. Two sources, and the split is the
  // point of Phase 6c:
  //
  //   `entry.result`  — what the ENGINE understood. Rendering this rather than
  //                     the page's own words makes the header double as the
  //                     answer to "did it understand this car?", which is the
  //                     question a reader actually has when the risks look
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

    let equipment = {};
    if (Array.isArray(listing.equipment)) {
      if (listing.equipment.length) equipment = { "Donanım": listing.equipment };
    } else if (listing.equipment && typeof listing.equipment === "object") {
      equipment = listing.equipment;
    }

    const identityLine = Object.values(identity)
      .filter((v) => v !== null && v !== undefined && v !== "")
      .join(" ");

    // A number with a unit is a magnitude and reads better grouped
    // ("190,000 km"); a number without one is as likely to be a year, where
    // grouping would render 2014 as "2,014".
    const facts = Object.entries(context)
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
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
    };
  }

  // ── Critical alerts: hard-coded rules over damage_info so the buyer can't
  // miss a heavy-collision red flag while skimming.
  const PART_RE = {
    kaput:     /\b(motor\s*kaputu|kaput)\b/i,
    tavan:     /\btavan\b/i,
    bagaj:     /\bbagaj(\s*kapa[ğg][ıi])?\b/i,
    marspiyel: /\bmar[şs]piyel\b/i,
  };
  function sideCounts(parts) {
    return {
      sol: parts.filter(p => /\bsol\b/i.test(p)).length,
      sag: parts.filter(p => /\bsa[ğg]\b/i.test(p)).length,
    };
  }
  function sameSideCount(parts) {
    const { sol, sag } = sideCounts(parts);
    return Math.max(sol, sag);
  }
  function buildCriticalAlerts(lm) {
    const alerts = [];
    if (!lm) return alerts;
    const damage = lm.damage_info || {};
    const changed = damage.changed || [];
    const painted = damage.painted || [];
    const tramer = Number(damage.tramer_amount || 0);
    const anyChanged = (re) => changed.some(p => re.test(p));
    const anyPainted = (re) => painted.some(p => re.test(p));

    if (anyChanged(PART_RE.kaput))
      alerts.push("Hood replaced: likely severe frontal collision. Have an expert inspect the chassis rails and engine mounts.");
    if (anyChanged(PART_RE.tavan))
      alerts.push("Roof replaced: possible rollover or major impact. A-pillars and chassis alignment must be checked.");
    if (anyChanged(PART_RE.bagaj))
      alerts.push("Trunk lid replaced: likely serious rear impact. Inspect rear chassis members and the rear floor.");
    const sameSideChanged = sameSideCount(changed);
    if (sameSideChanged >= 2)
      alerts.push(`${sameSideChanged} panels replaced on the same side: likely side-impact collision. Have an expert check pillars and chassis straightness.`);
    if (changed.length >= 3 && sameSideChanged < 2)
      alerts.push(`${changed.length} panels replaced overall: significant repair history. Do not buy without a full pre-purchase inspection.`);

    if (anyPainted(PART_RE.tavan) && !anyChanged(PART_RE.tavan))
      alerts.push("Roof painted: roofs are rarely repainted without a real cause. Check pillars and chassis alignment.");
    if (anyPainted(PART_RE.kaput) && !anyChanged(PART_RE.kaput))
      alerts.push("Hood painted: possible front impact or scratch repair. Verify engine mounts, headlight fit and color match.");
    if (anyPainted(PART_RE.bagaj) && !anyChanged(PART_RE.bagaj))
      alerts.push("Trunk lid painted: possible rear impact repair. Check rear cross-member and trunk seal alignment.");
    const paintedSides = sideCounts(painted);
    if (paintedSides.sol >= 2 && paintedSides.sag >= 2)
      alerts.push(`Painted panels on both sides (left: ${paintedSides.sol}, right: ${paintedSides.sag}): likely multiple impacts or extensive cosmetic refinishing.`);
    else if (painted.length >= 4)
      alerts.push(`${painted.length} panels painted overall: a large portion of the car has been refinished. Inspect for color mismatch, rust, and hidden damage.`);

    if (tramer >= 15000)
      alerts.push(`High insurance claim recorded (${tramer.toLocaleString()} TRY): significant past damage. Request the full Tramer history report.`);

    return alerts;
  }

  function counts() {
    if (!state.result || !Array.isArray(state.result.risks)) {
      return { high: 0, medium: 0, low: 0, total: 0 };
    }
    const out = { high: 0, medium: 0, low: 0, total: state.result.risks.length };
    for (const r of state.result.risks) {
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
      state.result = entry.result;
      state.errorMsg = null;
      setPipeline("result");
      state.openIds = new Set();
    } else if (entry.ok === false) {
      state.errorMsg = entry.error || "Analysis failed.";
      setPipeline("error");
    }
    if (state.mounted) renderBody();
    if (state.mounted) renderCounts();
  }

  // The reader's verdict on one claim. Sent to the app, which owns it —
  // nothing about ranking changes, because one reader's car is not a
  // refutation. What it buys is a queue of claims worth re-researching in the
  // reader's own words, which is the best signal this project can receive and
  // was previously being dropped on the floor.
  function markClaim(risk, verdict, cardEl) {
    if (!risk.claim_id || !risk.pack_id) return;
    const previous = state.marks.get(risk.claim_id);
    // Pressing the pressed one takes it back. Painted immediately and
    // reverted if the app disagrees: a verdict button that waits for a round
    // trip feels broken on a local app that answers in 3ms.
    const next = previous === verdict ? null : verdict;
    if (next) state.marks.set(risk.claim_id, next);
    else state.marks.delete(risk.claim_id);
    if (cardEl) markRiskCard(cardEl, next);

    chrome.runtime.sendMessage(
      {
        type: "MARK_CLAIM",
        payload: {
          pack_id: risk.pack_id,
          claim_id: risk.claim_id,
          subject_id: risk.subject_id || "",
          title: risk.title || "",
          verdict: next,
        },
      },
      (response) => {
        if (chrome.runtime.lastError || (response && !response.ok)) {
          if (previous) state.marks.set(risk.claim_id, previous);
          else state.marks.delete(risk.claim_id);
          if (cardEl) markRiskCard(cardEl, previous);
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
  function checkFacts(risk, cardEl) {
    if (!risk.claim_id || !risk.pack_id) return;
    if (state.checkingFacts.has(risk.claim_id)) return;
    state.checkingFacts.add(risk.claim_id);
    if (cardEl) factRiskCard(cardEl, state.facts.get(risk.claim_id), true);

    chrome.runtime.sendMessage(
      {
        type: "CHECK_FACTS",
        payload: { pack_id: risk.pack_id, claim_id: risk.claim_id },
      },
      (response) => {
        state.checkingFacts.delete(risk.claim_id);
        if (!chrome.runtime.lastError && response && response.ok && response.check) {
          state.facts.set(risk.claim_id, response.check);
        }
        // A failure leaves the card as it was. The claim and its sources are
        // on screen and the reader can open the link themselves, which is
        // what they did before this button existed — a panel-wide error over
        // a supplementary badge would be the tail wagging the dog.
        if (cardEl) factRiskCard(cardEl, state.facts.get(risk.claim_id), false);
      }
    );
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
        // A refusal is different: the only way to get one is for this
        // extension to have built a route the app cannot navigate to, which
        // is a defect in *our* code and belongs where a developer will find
        // it rather than in front of the reader.
        if (chrome.runtime.lastError || (response && !response.ok)) {
          console.warn(
            "Kriko: could not open the app on",
            route,
            chrome.runtime.lastError?.message || response?.error
          );
        }
      }
    );
  }

  // Nothing known about a subject the packs *do* recognise. That is the one
  // emptiness worth a button: the gap is identified, so filling it is a job
  // the app can start rather than a shrug.
  function researchSubject(subject, buttonEl) {
    state.researching = subject.subject_id;
    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.textContent = "Starting…";
    }
    chrome.runtime.sendMessage(
      {
        type: "RESEARCH_SUBJECT",
        payload: { subject_id: subject.subject_id, pack_id: subject.pack_id },
      },
      (response) => {
        state.researching = null;
        if (!buttonEl) return;
        const failed = chrome.runtime.lastError || (response && !response.ok);
        buttonEl.disabled = false;
        buttonEl.textContent = failed ? "Could not start — retry" : "Running in Kriko";
      }
    );
  }

  function triggerAnalyze() {
    setPipeline("analyzing");
    state.errorMsg = null;
    state.errorCode = null;
    renderBody();
    renderCounts();

    // background.js asks content.js for a fresh scrape, POSTs it to
    // /api/analyze, writes the full entry (result + the local-only listing
    // extras) to chrome.storage.session, and returns the result here.
    chrome.runtime.sendMessage(
      { type: "ANALYZE", payload: { url: window.location.href } },
      (response) => {
        if (chrome.runtime.lastError) {
          setPipeline("error");
          state.errorCode = null;
          state.errorMsg = chrome.runtime.lastError.message || "Background unreachable.";
          renderBody();
          return;
        }
        if (response && !response.ok) {
          if (response.code === "NO_ADAPTER") {
            // Nothing installed reads this site. Say nothing rather than
            // painting a red banner over an ordinary web page.
            setPipeline("idle");
            state.errorMsg = null;
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
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "session") return;
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
    risksHeadEl = panel.querySelector(".lite-risks-head-slot");
    risksListEl = panel.querySelector(".lite-risks");
    densityBtn  = panel.querySelector(".lite-btn-density");
    closeBtn    = panel.querySelector(".lite-btn-close");
    footerEl    = panel.querySelector(".lite-footer");

    // Wire panel-level handlers
    panel.addEventListener("pointerdown", onPointerDown);
    panel.addEventListener("pointermove", onPointerMove);
    panel.addEventListener("pointerup", onPointerUp);
    panel.addEventListener("pointercancel", onPointerUp);

    ctaBtn.addEventListener("click", triggerAnalyze);
    densityBtn.addEventListener("click", triggerAnalyze);
    closeBtn.addEventListener("click", closePanel);

    // Initial render
    renderBody();
    renderCounts();

    // Pull any cached result so a backgrounded auto-analysis shows instantly.
    // If nothing is cached yet on a listing page, kick off (or join) the run so
    // the panel shows progress instead of an empty state.
    requestCached({ triggerIfMissing: true });

    // Strip the mount flag so future state changes don't re-trigger the entry
    // animation.
    setTimeout(() => { if (panel) delete panel.dataset.mounting; }, 280);
  }

  function unmount() {
    if (!hostEl) return;
    try { hostEl.remove(); } catch (_) {}
    hostEl = shadow = panel = null;
    countsEl = bodyEl = statusEl = ctaBtn = null;
    risksHeadEl = risksListEl = densityBtn = closeBtn = null;
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
    return Math.max(520, Math.min(window.innerHeight - PAD_DOCK * 2, window.innerHeight - 32));
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
          <div class="lite-title">Kriko<span class="cc">.cc</span></div>
          <div class="lite-subtitle">Floating panel · drag to reposition</div>
        </div>
        <button type="button" class="lite-iconbtn lite-btn-density"
                title="Refresh analysis" aria-label="Refresh analysis">
          ${iconSvg("refresh", { size: 16, strokeWidth: 2 })}
        </button>
        <button type="button" class="lite-iconbtn lite-btn-menu"
                title="Menu" aria-label="Menu">
          ${iconSvg("rowsLoose", { size: 18, strokeWidth: 2 })}
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
          <p class="lite-status">Open a Sahibinden listing, then analyze.</p>
        </div>
        <div class="lite-risks-head-slot"></div>
        <section class="lite-risks"></section>
        <div class="lite-summary-slot"></div>
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
      .join('<span class="sep">·</span>');

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

  function renderSummary() {
    const slot = bodyEl.querySelector(".lite-summary-slot");
    if (!slot) return;
    if (state.pipeline !== "result" || !state.result || !state.result.summary) {
      slot.innerHTML = "";
      lastSummaryText = null;
      return;
    }

    const txt = state.result.summary;

    // Rebuild only when the text itself changes — otherwise just flip the
    // expanded attribute in place so the CSS animation runs.
    if (txt !== lastSummaryText) {
      lastSummaryText = txt;
      slot.innerHTML = `
        <div class="lite-summary" data-expanded="${state.summaryExpanded ? "1" : "0"}">
          <div class="lite-summary-label">SUMMARY</div>
          <p class="lite-summary-body">${escapeHtml(txt)}</p>
          <button type="button" class="lite-summary-toggle" hidden>
            ${state.summaryExpanded ? "SHOW LESS" : "SHOW MORE"}
          </button>
        </div>
      `;
      const card = slot.querySelector(".lite-summary");
      const body = slot.querySelector(".lite-summary-body");
      const toggle = slot.querySelector(".lite-summary-toggle");

      // Show toggle only when the text actually overflows the clamp.
      requestAnimationFrame(() => {
        const overflows = body.scrollHeight - body.clientHeight > 1;
        toggle.hidden = !overflows;
      });

      function setSummaryExpanded(next) {
        if (next === state.summaryExpanded) return;
        state.summaryExpanded = next;
        toggle.textContent = next ? "SHOW LESS" : "SHOW MORE";
        if (next) {
          // Expand: animate from clamped (CSS default) to exact content height.
          body.style.maxHeight = body.scrollHeight + "px";
          card.dataset.expanded = "1";
          const onEnd = (e) => {
            if (e.propertyName !== "max-height") return;
            // Drop the inline cap so future content changes adapt naturally.
            body.style.maxHeight = "none";
            body.removeEventListener("transitionend", onEnd);
          };
          body.addEventListener("transitionend", onEnd);
        } else {
          // Collapse: pin current height in px so the transition has a
          // starting value to interpolate from, then revert to the CSS clamp.
          body.style.maxHeight = body.scrollHeight + "px";
          void body.offsetHeight; // force reflow
          body.style.maxHeight = "";
          card.dataset.expanded = "0";
        }
      }

      toggle.addEventListener("click", () => setSummaryExpanded(!state.summaryExpanded));
      // Clicking the clamped text itself also expands — matches the user's
      // "click on the …" intuition. (Doesn't collapse on click.)
      body.addEventListener("click", () => {
        if (!state.summaryExpanded) setSummaryExpanded(true);
      });
      return;
    }

    // In-place state sync
    const card = slot.querySelector(".lite-summary");
    const toggle = slot.querySelector(".lite-summary-toggle");
    if (card) card.dataset.expanded = state.summaryExpanded ? "1" : "0";
    if (toggle) toggle.textContent = state.summaryExpanded ? "SHOW LESS" : "SHOW MORE";
  }

  function renderListingDetails() {
    const slot = bodyEl.querySelector(".lite-details-slot");
    if (!slot) return;
    const lm = state.listingMeta;
    if (!lm) { slot.innerHTML = ""; lastDetailsListingMeta = null; return; }
    const damage = lm.damage_info || {};
    const changed = damage.changed || [];
    const painted = damage.painted || [];
    const local   = damage.local_painted || [];
    const tramer  = damage.tramer_amount;
    const equipment = lm.equipment || {};
    const equipmentEntries = Object.entries(equipment).filter(([, items]) => items && items.length);

    if (!changed.length && !painted.length && !local.length && !tramer && !equipmentEntries.length) {
      slot.innerHTML = "";
      lastDetailsListingMeta = null;
      return;
    }

    // Build the DOM only when the underlying listing changes. Toggles after
    // that mutate data-open on the existing elements so CSS grid-template-rows
    // can animate.
    if (lm !== lastDetailsListingMeta) {
      lastDetailsListingMeta = lm;

      const rows = [];
      if (changed.length) rows.push({
        title: "Replaced", tone: "danger", items: changed,
        hint: "The panel was removed and a new one installed. Strong signal of serious prior damage; if the hood, roof or trunk lid is here, demand a chassis inspection.",
      });
      if (painted.length) rows.push({
        title: "Painted", tone: "warn", items: painted,
        hint: "The panel was resprayed. Panels are rarely repainted without a reason — usually an old impact or scratch repair. Check for color mismatch and rust.",
      });
      if (local.length) rows.push({
        title: "Local paint", tone: "warn", items: local,
        hint: "Only a small area was repainted. Usually a minor scrape or stone-chip touch-up.",
      });
      if (tramer) rows.push({
        title: "Damage claim", tone: "danger",
        items: [`${Number(tramer).toLocaleString()} ${damage.tramer_currency || "TRY"}`],
        hint: "Insurance-recorded damage amount. The larger the figure, the more serious the past repair.",
      });
      for (const [category, items] of equipmentEntries) {
        rows.push({ title: category, tone: "neutral", items });
      }

      const totalChips =
        changed.length + painted.length + local.length +
        (tramer ? 1 : 0) +
        equipmentEntries.reduce((n, [, items]) => n + items.length, 0);

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

  function renderStatus() {
    if (!statusEl) return;
    if (state.pipeline === "idle") {
      statusEl.textContent = "Open a Sahibinden listing, then analyze.";
      statusEl.style.display = "";
    } else if (state.pipeline === "analyzing") {
      statusEl.textContent = "Resolving engine family · retrieving transcripts…";
      statusEl.style.display = "";
    } else if (state.pipeline === "result") {
      // Summary card below has the prose; keep the status line out of the way.
      statusEl.textContent = "";
      statusEl.style.display = "none";
    } else if (state.pipeline === "error") {
      statusEl.textContent = state.errorMsg || "Analysis failed.";
      statusEl.style.display = "";
    }
  }

  // Render risks header helper
  function renderRisksHeader() {
    if (!risksHeadEl) return;
    if (state.pipeline !== "result" || !state.result) {
      risksHeadEl.innerHTML = "";
      return;
    }
    const total = state.result.risks.length;
    const allOpen  = state.openIds.size === total && total > 0;
    const allClose = state.openIds.size === 0;

    // Build once. On subsequent toggles, mutate in place so the entrance
    // animation does not retrigger.
    let head = risksHeadEl.querySelector(".lite-risks-head");
    if (!head) {
      risksHeadEl.innerHTML = `
        <div class="lite-risks-head">
          <div class="lite-risks-label">RISKS · ${total}</div>
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
      risksHeadEl.querySelector(".lite-chip-expand").addEventListener("click", expandAll);
      risksHeadEl.querySelector(".lite-chip-collapse").addEventListener("click", collapseAll);
      return;
    }

    // Update in place
    const label = head.querySelector(".lite-risks-label");
    if (label) label.textContent = `RISKS · ${total}`;
    const expandBtn   = head.querySelector(".lite-chip-expand");
    const collapseBtn = head.querySelector(".lite-chip-collapse");
    if (expandBtn)   expandBtn.dataset.on   = allOpen  ? "1" : "0";
    if (collapseBtn) collapseBtn.dataset.on = allClose ? "1" : "0";
  }

  function renderRisksList() {
    if (!risksListEl) return;
    risksListEl.dataset.compact = state.compact ? "1" : "0";
    risksListEl.innerHTML = "";

    if (state.pipeline === "analyzing") {
      const skel = document.createElement("div");
      skel.className = "lite-skeleton-list";
      for (let i = 0; i < 3; i++) {
        const row = document.createElement("div");
        row.className = "lite-skeleton";
        skel.appendChild(row);
      }
      risksListEl.appendChild(skel);
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
      risksListEl.appendChild(err);
      return;
    }

    if (state.pipeline === "idle" || !state.result) {
      const empty = document.createElement("div");
      empty.className = "lite-empty";
      empty.innerHTML = `
        <span class="lite-empty-icon">${iconSvg("search", { size: 18 })}</span>
        <div>No analysis yet. Hit <b>Analyze current page</b> — typical run is under 2&nbsp;s.</div>
      `;
      risksListEl.appendChild(empty);
      return;
    }

    // An answer with no risks is not the same as no answer. If the packs
    // resolved this listing and hold nothing on it, that gap is the content.
    if (!state.result.risks || !state.result.risks.length) {
      const gaps = (state.result.subjects || []).filter((s) => !s.claims);
      if (!gaps.length) {
        const empty = document.createElement("div");
        empty.className = "lite-empty";
        empty.textContent =
          "Nothing matched this listing. No installed pack recognises it.";
        risksListEl.appendChild(empty);
      }
      renderGaps();
      return;
    }

    // Group for display. Serving payload v2: when the backend sends
    // `subsystems` (registry component groups — engine/timing, body/comfort, …),
    // render those sections with the Turkish label; otherwise fall back to the
    // legacy domain grouping. Global risk indices into state.result.risks are
    // preserved either way so toggleOne/setAllOpen keep working.
    const domainLabels = {
      engine: "Engine", transmission: "Transmission", emissions: "Emissions",
      electrical: "Electrical", "fuel system": "Fuel System", cooling: "Cooling",
      suspension: "Suspension", brakes: "Brakes", exhaust: "Exhaust",
      interior: "Interior", "body/structure": "Body", steering: "Steering",
    };

    let groups;
    if (state.result.subsystems && state.result.subsystems.length) {
      groups = state.result.subsystems
        .map((g) => ({
          iconDomain: (g.name || "other").split("/")[0],
          label: g.display_tr || g.name || "Other",
          items: (g.risks || [])
            .map((risk) => ({ risk, idx: state.result.risks.indexOf(risk) }))
            .filter((it) => it.idx >= 0),
        }))
        .filter((g) => g.items.length);
    } else {
      const byDomain = {};
      state.result.risks.forEach((risk, i) => {
        const d = (risk.domain || "other").toLowerCase().trim();
        if (!byDomain[d]) byDomain[d] = [];
        byDomain[d].push({ risk, idx: i });
      });
      groups = Object.entries(byDomain).map(([domain, items]) => ({
        iconDomain: domain,
        label: domainLabels[domain] || domain.charAt(0).toUpperCase() + domain.slice(1),
        items,
      }));
    }

    let delayCounter = 0;
    for (const { iconDomain, label, items } of groups) {
      const high = items.filter(i => i.risk.severity === "high").length;
      const med  = items.filter(i => i.risk.severity === "medium").length;
      const low  = items.filter(i => i.risk.severity === "low").length;

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
          <span class="lite-domain-toggle">&minus;</span>
        </button>
        <div class="lite-domain-body"></div>
      `;

      // Populate body with risk cards
      const bodyEl = groupEl.querySelector(".lite-domain-body");
      items.forEach(({ risk, idx }) => {
        const wrap = document.createElement("div");
        wrap.className = "lite-risk-anim";
        wrap.style.animationDelay = (80 + delayCounter * 70) + "ms";
        delayCounter++;
        const card = renderRiskCard(risk, { open: state.openIds.has(idx), compact: state.compact });
        const btn = card.querySelector(".lite-rc-toggle");
        btn.addEventListener("click", () => toggleOne(idx, card));
        // Re-assert any verdict this claim already carries: the list is
        // rebuilt on every expand-all and every fresh analysis, and a mark
        // that disappeared on redraw would read as one that failed to save.
        if (risk.claim_id && state.marks.has(risk.claim_id)) {
          markRiskCard(card, state.marks.get(risk.claim_id));
        }
        // Re-asserted on redraw for the same reason a mark is: the list is
        // rebuilt on every expand-all, and a verdict that vanished would read
        // as one that failed.
        if (risk.claim_id && state.facts.has(risk.claim_id)) {
          factRiskCard(card, state.facts.get(risk.claim_id),
            state.checkingFacts.has(risk.claim_id));
        }
        const factBtn = card.querySelector(".lite-rc-factbtn");
        if (factBtn) {
          factBtn.addEventListener("click", (event) => {
            event.stopPropagation(); // the card header toggles on click
            checkFacts(risk, card);
          });
        }
        card.querySelectorAll(".lite-rc-markbtn").forEach((markBtn) => {
          markBtn.addEventListener("click", (event) => {
            event.stopPropagation(); // the card header toggles on click
            markClaim(risk, markBtn.dataset.verdict, card);
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

      risksListEl.appendChild(groupEl);
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
    if (!risksListEl || !state.result) return;
    const gaps = (state.result.subjects || []).filter((s) => !s.claims);
    if (!gaps.length) return;

    for (const subject of gaps) {
      const card = document.createElement("div");
      card.className = "lite-gap";
      card.innerHTML = `
        <div class="lite-gap-body">
          <div class="lite-gap-title">Nothing known about ${escapeHtml(subject.label)}</div>
          <div class="lite-gap-note">This is in the catalogue, but no claim has been
            researched for it yet.</div>
        </div>
        <button type="button" class="lite-gap-btn">Research it</button>
      `;
      const button = card.querySelector(".lite-gap-btn");
      button.addEventListener("click", () => researchSubject(subject, button));
      risksListEl.appendChild(card);
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
    // who had just read the risks had to go and find the same listing again
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
    renderRisksHeader();
    renderRisksList();
    renderSummary();
    renderListingDetails();
    renderFooter();
  }

  // ─── Interactions ─────────────────────────────────────────────────────
  function toggleOne(idx, cardEl) {
    if (state.openIds.has(idx)) state.openIds.delete(idx);
    else state.openIds.add(idx);
    updateRiskCard(cardEl, { open: state.openIds.has(idx) });
    // Update Expand/Collapse-all chip "on" state
    renderRisksHeader();
  }
  function setAllOpen(open) {
    if (!state.result) return;
    state.openIds = open
      ? new Set(state.result.risks.map((_, i) => i))
      : new Set();
    // Mutate cards in place so each one runs its own expand/collapse animation
    // — re-rendering the list would retrigger the entrance animation.
    const cards = risksListEl.querySelectorAll(".lite-rc");
    cards.forEach((card) => updateRiskCard(card, { open }));
    renderRisksHeader();
  }
  function expandAll()   { setAllOpen(true); }
  function collapseAll() { setAllOpen(false); }
})();
