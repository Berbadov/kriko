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
  const { renderRiskCard, updateRiskCard } = window.__KrikoPanelRiskCard;

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
    listingMeta: null,         // derived from background metadata response
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

  // ─── Font preload in host document ────────────────────────────────────
  (function ensureFonts() {
    if (document.getElementById("kriko-panel-fonts")) return;
    const link = document.createElement("link");
    link.id = "kriko-panel-fonts";
    link.rel = "stylesheet";
    link.href =
      "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700" +
      "&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap";
    (document.head || document.documentElement).appendChild(link);
  })();

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

  function deriveListingMeta(adMetadata) {
    if (!adMetadata) return null;
    // Equipment can arrive as array (older payloads) or { category: [features] }
    // (current scraper). Normalize to a category map.
    let equipment = {};
    if (Array.isArray(adMetadata.equipment)) {
      if (adMetadata.equipment.length) equipment = { "Donanım": adMetadata.equipment };
    } else if (adMetadata.equipment && typeof adMetadata.equipment === "object") {
      equipment = adMetadata.equipment;
    }
    const engineFamily =
      adMetadata.trim ||
      adMetadata.engine_family ||
      [adMetadata.make, adMetadata.model].filter(Boolean).join(" ") ||
      null;
    return {
      title: adMetadata.title || "Untitled listing",
      year: adMetadata.year || null,
      mileage_km: adMetadata.mileage_km || null,
      annual_km: adMetadata.annual_km || null,
      fuel: adMetadata.fuel_type || null,
      engine_family: engineFamily,
      damage_info: adMetadata.damage_info || null,
      equipment,
    };
  }

  // Green / yellow / red tint based on average annual km.
  function annualKmTone(annualKm) {
    if (!annualKm) return null;
    if (annualKm < 15000) return { ink: "var(--low-ink)",  surface: "var(--low-surface)" };
    if (annualKm < 20000) return { ink: "var(--med-ink)",  surface: "var(--med-surface)" };
    return                       { ink: "var(--high-ink)", surface: "var(--high-surface)" };
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

  // ─── Backend messaging ────────────────────────────────────────────────
  // Sahibinden listing detail pages auto-analyze in the background on load.
  // When the panel opens on such a page with nothing cached yet, we want to
  // show the analyzing state and join that run rather than sit on "idle".
  function isAnalyzableListing() {
    if (!window.location.hostname.includes("sahibinden.com")) return false;
    const path = window.location.pathname;
    return path.includes("/ilan/") || path.includes("/detail");
  }

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
          if (triggerIfMissing && state.pipeline === "idle" && isAnalyzableListing()) {
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
    if (entry.adMetadata) {
      state.listingMeta = deriveListingMeta(entry.adMetadata);
    }
    if (entry.ok && entry.result) {
      state.result = entry.result;
      state.errorMsg = null;
      state.pipeline = "result";
      state.openIds = new Set();
    } else if (entry.ok === false) {
      state.errorMsg = entry.error || "Analysis failed.";
      state.pipeline = "error";
    }
    if (state.mounted) renderBody();
    if (state.mounted) renderCounts();
  }

  function triggerAnalyze() {
    state.pipeline = "analyzing";
    state.errorMsg = null;
    renderBody();
    renderCounts();

    // background.js re-fetches metadata from the page via content.js, runs
    // /analyze, writes the full entry (adMetadata + result) to
    // chrome.storage.session, and returns the result in the response.
    chrome.runtime.sendMessage(
      { type: "ANALYZE_AD", payload: { url: window.location.href } },
      (response) => {
        if (chrome.runtime.lastError) {
          state.pipeline = "error";
          state.errorMsg = chrome.runtime.lastError.message || "Background unreachable.";
          renderBody();
          return;
        }
        if (response && !response.ok) {
          state.pipeline = "error";
          state.errorMsg = response.error || "Analysis failed.";
          renderBody();
          return;
        }
        // Apply the result the response already carries so the panel can never
        // get stuck on "analyzing" if the follow-up cache read races or the
        // service worker recycled the message port before onChanged fired.
        // requestCached() then enriches with adMetadata (listing header,
        // critical alerts, listing details), which the response omits.
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

    // Title + a compact meta line of year / km / fuel / engine.
    // No price, no power — those live in the listing-details panel.
    const tone = annualKmTone(lm.annual_km);
    const kmTag = (lm.annual_km && tone)
      ? `<span class="lite-km-tag" style="color:${tone.ink};background:${tone.surface};">~${Number(lm.annual_km).toLocaleString()}/yr</span>`
      : "";

    const bits = [];
    if (lm.year)       bits.push(`<span>${escapeHtml(String(lm.year))}</span>`);
    if (lm.mileage_km) bits.push(`<span class="km">${Number(lm.mileage_km).toLocaleString()} km${kmTag}</span>`);
    if (lm.fuel)       bits.push(`<span>${escapeHtml(lm.fuel)}</span>`);
    const metaLine = bits.join('<span class="sep">·</span>');

    slot.innerHTML = `
      <div class="lite-listing">
        <div class="lite-listing-title">${escapeHtml(lm.title || "")}</div>
        ${bits.length ? `<div class="lite-listing-meta">${metaLine}</div>` : ""}
        ${lm.engine_family ? `<div class="lite-listing-engine">${escapeHtml(lm.engine_family)}</div>` : ""}
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

    // Group by domain, preserving global indices for toggleOne/setAllOpen
    const groups = {};
    state.result.risks.forEach((risk, i) => {
      const d = (risk.domain || "other").toLowerCase().trim();
      if (!groups[d]) groups[d] = [];
      groups[d].push({ risk, idx: i });
    });

    const domainLabels = {
      engine: "Engine", transmission: "Transmission", emissions: "Emissions",
      electrical: "Electrical", "fuel system": "Fuel System", cooling: "Cooling",
      suspension: "Suspension", brakes: "Brakes", exhaust: "Exhaust",
      interior: "Interior", "body/structure": "Body", steering: "Steering",
    };

    let delayCounter = 0;
    for (const [domain, items] of Object.entries(groups)) {
      const label = domainLabels[domain] || domain.charAt(0).toUpperCase() + domain.slice(1);
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
          <span class="lite-domain-icon">${domainIconSvg(domain, { size: 15 })}</span>
          <span class="lite-domain-name">${label}</span>
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
  }

  // Deploy-staleness guard (B15): the footer names the backend build that
  // answered, so a stale deploy is visible to anyone looking at the panel.
  // Pre-B15 backends omit `build` and unstamped builds report "unknown" — both
  // render as "api · unknown", which is itself the tell.
  function renderFooter() {
    if (!footerEl) return;
    if (state.pipeline !== "result" || !state.result) {
      footerEl.hidden = true;
      footerEl.textContent = "";
      return;
    }
    const commit = state.result.build && state.result.build.commit;
    footerEl.textContent = `api · ${commit || "unknown"}`;
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
