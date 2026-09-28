/* ClaimCard — dark left-tile layout matching Kriko Panel design. */

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
  function canCheck(claim) {
    return Boolean(
      claim.claim_id
        && claim.pack_id
        && (claim.sources || []).some((source) => source && source.url)
    );
  }

  function renderClaimCard(claim, { open = false, compact = false } = {}) {
    const sev = ["high", "medium", "low"].includes(claim.severity) ? claim.severity : "medium";

    /* Strength badge: two tiers, and it used to claim four.
     *
     * `due` and `due_stated` — "Due unless serviced", "Seller states done —
     * verify" — were rendered here and `_strengthOf` in the worker can only
     * ever return `confirmed` or `reported`, so neither label has been
     * reachable for as long as the branch has existed. They are a good idea
     * (the product principle's maintenance-interval claims are exactly that
     * shape) and they belong wherever that shape is decided, which is the
     * pack's bar and the engine's ranking — not in a dead branch of a card
     * renderer where nothing can ever set them. */
    const confirmed = claim.strength === "confirmed";
    // Only show numeric confidence on confirmed cards — on other cards a score
    // reads as trustworthy and undercuts the amber/orange label.
    const confText =
      confirmed && typeof claim.confidence === "number" ? claim.confidence.toFixed(2) : null;
    const srcN = typeof claim.source_count === "number" ? claim.source_count : null;
    const strengthLabel = confirmed  ? "Confirmed"
      : `Reported${srcN ? ` · ${srcN} source${srcN === 1 ? "" : "s"}` : ""}`;
    const strengthAttr = claim.strength || "reported";

    // `why_shown` is the engine's own ranking diagnostics, not a buyer's
    // vocabulary. Severity is already the card's icon and colour, and which
    // pack answered is already the panel's footer — repeating either here as
    // a chip is noise. What's worth a chip is why *this* claim reached *this*
    // car (a shared part, a downrank) and it belongs in the body a reader
    // opens on purpose, not on the collapsed title every card shows first.
    const shownWhy = (claim.why_shown || []).filter(
      (w) => !/ severity$/.test(w) && !/^from pack:/.test(w)
    );

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
          <div class="lite-rc-title">${escapeHtml(claim.title)}</div>
          <div class="lite-rc-meta">
            <span class="lite-rc-strength" data-strength="${escapeHtml(strengthAttr)}">${escapeHtml(strengthLabel)}</span>
            <span class="sep" aria-hidden="true"> · </span><span>${escapeHtml(claim.domain || "")}</span>
            ${confText ? `<span class="sep" aria-hidden="true"> · </span><span>conf ${confText}</span>` : ""}
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
            <p class="lite-rc-text">${escapeHtml(claim.body || "")}</p>
            ${shownWhy.length ? `
              <div class="lite-rc-why">
                ${shownWhy.map((w) => `<span class="lite-rc-why-chip">${escapeHtml(w)}</span>`).join("")}
              </div>` : ""}
            ${claim.advice ? `
              <div class="lite-rc-insp">
                <span class="lite-rc-insp-icon">${iconSvg("eye", { size: 13 })}</span>
                <div class="lite-rc-insp-body">
                  <div class="lite-rc-insp-label">What to ask</div>
                  ${escapeHtml(claim.advice)}
                </div>
              </div>` : ""}
            ${canCheck(claim) ? `
              <div class="lite-rc-fact">
                <button type="button" class="lite-rc-factbtn"
                        title="Re-read the page this claim cites">Check the source</button>
                <span class="lite-rc-factverdict" hidden></span>
              </div>` : ""}
            ${claim.claim_id ? `
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

  function updateClaimCard(article, { open, compact }) {
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
   * Separate from `updateClaimCard` because a mark arrives from a round trip
   * to the app while `open`/`compact` are local state — folding them together
   * would make every expand re-assert a verdict the server may have refused.
   */
  function markClaimCard(article, verdict) {
    article.querySelectorAll(".lite-rc-markbtn").forEach((button) => {
      const on = button.dataset.verdict === verdict;
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  /** Paint what the cited page says now.
   *
   * Its own function for the same reason `markClaimCard` is: this arrives from
   * a round trip to the app, while `open`/`compact` are local state.
   */
  function factClaimCard(article, check, busy) {
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

  window.__KrikoPanelClaimCard = {
    renderClaimCard,
    updateClaimCard,
    markClaimCard,
    factClaimCard,
    canCheck,
    FACT_WORD,
  };
})();
