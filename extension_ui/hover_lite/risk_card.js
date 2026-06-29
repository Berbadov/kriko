/* RiskCard — dark left-tile layout matching Kriko Panel design. */

(function () {
  const { iconSvg } = window.__KrikoPanelIcons;

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
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

  window.__KrikoPanelRiskCard = { renderRiskCard, updateRiskCard };
})();
