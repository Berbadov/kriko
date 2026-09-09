/* RiskCard — dark left-tile layout matching Kriko Panel design. */

(function () {
  const { iconSvg } = window.__KrikoPanelIcons;

  /* What a re-check of a claim's sources means, in words.
   *
   * The verdicts are a closed vocabulary owned by `src/app/factcheck.py`, and
   * `test_factcheck.py` fails if this map and that one drift apart — a panel
   * that silently rendered an unknown verdict as reassurance would be the
   * worst possible default.
   *
   * "missing" says the page changed, never that the claim is false: pages get
   * rewritten, and Kriko has no authority to retract anything. */
  const FACT_WORD = {
    quoted: "Source still says this",
    missing: "Source has changed",
    unreadable: "Cannot check automatically",
    unreachable: "Source unreachable",
  };

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /** Whether this claim can be re-checked: an identity the app can look up,
   * and a page to re-read. */
  function canCheck(risk) {
    return Boolean(
      risk.claim_id
        && risk.pack_id
        && (risk.sources || []).some((source) => source && source.url)
    );
  }

  function renderRiskCard(risk, { open = false, compact = false } = {}) {
    const sev = ["high", "medium", "low"].includes(risk.severity) ? risk.severity : "medium";

    // Strength badge: four tiers — confirmed, due, due_stated, reported.
    const confirmed = risk.strength === "confirmed";
    const due       = risk.strength === "due";
    const dueStated = risk.strength === "due_stated";
    // Only show numeric confidence on confirmed cards — on other cards a score
    // reads as trustworthy and undercuts the amber/orange label.
    const confText =
      confirmed && typeof risk.confidence === "number" ? risk.confidence.toFixed(2) : null;
    const srcN = typeof risk.source_count === "number" ? risk.source_count : null;
    const strengthLabel = confirmed  ? "Confirmed"
      : due       ? "Due unless serviced"
      : dueStated ? "Seller states done — verify"
      : `Reported${srcN ? ` · ${srcN} source${srcN === 1 ? "" : "s"}` : ""}`;
    const strengthAttr = risk.strength || "reported";

    const article = document.createElement("article");
    article.className = "lite-rc";
    article.dataset.sev = sev;
    article.dataset.strength = strengthAttr;
    article.dataset.open = open ? "1" : "0";
    if (compact) article.dataset.compact = "1";

    article.innerHTML = `
      <div class="lite-rc-head">
        <div class="lite-rc-domain" aria-hidden="true">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="miter"><path d="M12 3 1.5 21h21z"/><line x1="12" y1="10" x2="12" y2="14"/><line x1="12" y1="17.5" x2="12" y2="17.6"/></svg>
        </div>
        <div class="lite-rc-titlebox">
          <div class="lite-rc-title">${escapeHtml(risk.title)}</div>
          ${risk.why_shown && risk.why_shown.length ? `
            <div class="lite-rc-why">
              ${risk.why_shown.map((w) => `<span class="lite-rc-why-chip">${escapeHtml(w)}</span>`).join("")}
            </div>` : ""}
          <div class="lite-rc-meta">
            <span class="lite-rc-strength" data-strength="${escapeHtml(strengthAttr)}">${escapeHtml(strengthLabel)}</span>
            <span class="sep"> · </span><span>${escapeHtml(risk.domain || "")}</span>
            ${confText ? `<span class="sep"> · </span><span>conf ${confText}</span>` : ""}
          </div>
        </div>
        <button type="button" class="lite-rc-toggle"
                aria-expanded="${open ? "true" : "false"}"
                aria-label="${open ? "Collapse" : "Expand"}"
                title="${open ? "Collapse" : "Expand"}">
          ${open ? "–" : "+"}
        </button>
      </div>
      <div class="lite-rc-bodywrap">
        <div class="lite-rc-bodyclip">
          <div class="lite-rc-body">
            <p class="lite-rc-rationale">${escapeHtml(risk.rationale || "")}</p>
            ${risk.inspection_advice ? `
              <div class="lite-rc-insp">
                <span class="lite-rc-insp-icon">${iconSvg("eye", { size: 13 })}</span>
                <div class="lite-rc-insp-body">
                  <div class="lite-rc-insp-label">Inspection</div>
                  ${escapeHtml(risk.inspection_advice)}
                </div>
              </div>` : ""}
            ${canCheck(risk) ? `
              <div class="lite-rc-fact">
                <button type="button" class="lite-rc-factbtn"
                        title="Re-read the page this claim cites">Check the source</button>
                <span class="lite-rc-factverdict" hidden></span>
              </div>` : ""}
            ${risk.claim_id ? `
              <div class="lite-rc-mark" role="group" aria-label="Was this any use?">
                <span class="lite-rc-mark-label">Was this any use?</span>
                <button type="button" class="lite-rc-markbtn" data-verdict="useful"
                        aria-pressed="false" title="Worth knowing">Useful</button>
                <button type="button" class="lite-rc-markbtn" data-verdict="not_applicable"
                        aria-pressed="false"
                        title="True of this engine, but not of this car">Not mine</button>
                <button type="button" class="lite-rc-markbtn" data-verdict="wrong"
                        aria-pressed="false" title="Not true">Wrong</button>
              </div>` : ""}
          </div>
        </div>
      </div>
    `;
    return article;
  }

  function updateRiskCard(article, { open, compact }) {
    if (open !== undefined) {
      article.dataset.open = open ? "1" : "0";
      const toggleBtn = article.querySelector(".lite-rc-toggle");
      if (toggleBtn) {
        toggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
        toggleBtn.setAttribute("aria-label", open ? "Collapse" : "Expand");
        toggleBtn.setAttribute("title", open ? "Collapse" : "Expand");
        toggleBtn.textContent = open ? "–" : "+";
      }
    }
    if (compact !== undefined) {
      if (compact) article.dataset.compact = "1";
      else delete article.dataset.compact;
    }
  }

  /** Show which verdict, if any, this claim already carries.
   *
   * Separate from `updateRiskCard` because a mark arrives from a round trip
   * to the app while `open`/`compact` are local state — folding them together
   * would make every expand re-assert a verdict the server may have refused.
   */
  function markRiskCard(article, verdict) {
    article.querySelectorAll(".lite-rc-markbtn").forEach((button) => {
      const on = button.dataset.verdict === verdict;
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  /** Paint what the cited page says now.
   *
   * Its own function for the same reason `markRiskCard` is: this arrives from
   * a round trip to the app, while `open`/`compact` are local state.
   */
  function factRiskCard(article, check, busy) {
    const button = article.querySelector(".lite-rc-factbtn");
    const label = article.querySelector(".lite-rc-factverdict");
    if (button) {
      button.disabled = Boolean(busy);
      button.textContent = busy
        ? "Reading the source\u2026"
        : check ? "Check again" : "Check the source";
    }
    if (!label) return;
    if (!check) {
      label.hidden = true;
      label.textContent = "";
      return;
    }
    label.hidden = false;
    label.dataset.verdict = check.verdict || "";
    // The date, always: "source still says this" with no when on it is the
    // kind of reassurance that ages badly.
    const when = (check.checked_at || "").slice(0, 10);
    label.textContent = (FACT_WORD[check.verdict] || check.verdict || "")
      + (when ? ` \u00b7 ${when}` : "");
  }

  window.__KrikoPanelRiskCard = {
    renderRiskCard,
    updateRiskCard,
    markRiskCard,
    factRiskCard,
    canCheck,
    FACT_WORD,
  };
})();
