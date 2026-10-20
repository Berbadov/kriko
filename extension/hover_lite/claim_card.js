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

  /* Prose a pack or an agent wrote carries light markdown: **bold** and
   * `code`. Shown raw, the asterisks read as noise, so this renders just those
   * two, on top of the escaped text: nothing the author writes can become
   * markup of its own. Page text and the reader's own words never come here. */
  function renderRichText(s) {
    return escapeHtml(s)
      .replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`\n]+?)`/g, "<code>$1</code>");
  }

  /* ─── The sources a claim stands on ────────────────────────────────────
   *
   * A finding reads claim first, then where it came from and the words it
   * quotes (#262). One reader of a source row for every card, so a stored
   * claim and a quick look's finding show their evidence the same way.
   * Only an http(s) address becomes a link; anything else is shown as text,
   * because a source row is data a pack or an agent wrote. */
  function hostOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ""); } catch (_) { return ""; }
  }

  function readSources(claim) {
    const rows = Array.isArray(claim && claim.sources) ? claim.sources : [];
    return rows
      .filter((row) => row && typeof row === "object" && (row.quote || row.url))
      .map((row) => {
        const url = /^https?:\/\//i.test(String(row.url || "")) ? String(row.url) : "";
        return {
          url,
          domain: String(row.domain || hostOf(url) || row.url || ""),
          quote: String(row.quote || "").replace(/\s+/g, " ").trim(),
          disputes: row.stance === "refutes",
        };
      });
  }

  function sourceMarkup(source) {
    const link = source.url
      ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.domain)}</a>`
      : `<span>${escapeHtml(source.domain)}</span>`;
    return `<figure class="lite-rc-src"${source.disputes ? ' data-stance="refutes"' : ""}>
      ${source.quote ? `<blockquote>\u201c${escapeHtml(source.quote)}\u201d</blockquote>` : ""}
      <figcaption>${link}${source.disputes ? ' <span class="lite-rc-src-note">disputes this</span>' : ""}</figcaption>
    </figure>`;
  }

  /* The first two are shown; the rest fold away, so a claim with six sources
   * is not a card six quotes tall. */
  const SOURCES_SHOWN = 2;
  function sourcesMarkup(sources) {
    if (!sources.length) return "";
    const shown = sources.slice(0, SOURCES_SHOWN).map(sourceMarkup).join("");
    const rest = sources.slice(SOURCES_SHOWN);
    return `<div class="lite-rc-sources">
      <div class="lite-rc-label">${sources.length === 1 ? "Source" : `Sources \u00b7 ${sources.length}`}</div>
      ${shown}
      ${rest.length ? `<details class="lite-rc-more"><summary>${rest.length} more source${rest.length === 1 ? "" : "s"}</summary>${rest.map(sourceMarkup).join("")}</details>` : ""}
    </div>`;
  }

  /* ─── How much a finding stands on (#263) ──────────────────────────────
   *
   * The reader's words: "info sensitivity setting, showing or not showing
   * thin evidences, with an indicator next to info cards". Thin is derived
   * from the claim itself, never listed per product or per category.
   *
   * The engine owns the verdict (`src/app/evidence.py`, exposed as `thin` on
   * a claim row: an object `{ level, reasons }`, or just the level as a
   * string). Until a row carries it, the same signals are read here from
   * what the row already says, and ONLY from what it says: an absent field
   * is never taken as a weakness, so a quick look's finding, which has no
   * trust tier, is not called low-trust for lacking one.
   *
   * Swapping to the engine alone is one line: delete the `deriveEvidence`
   * call in `evidenceOf`. */
  const EVIDENCE_LEVELS = ["solid", "partial", "thin"];
  const EVIDENCE_WORD = { solid: "Solid evidence", partial: "Partial evidence", thin: "Thin evidence" };
  const EVIDENCE_SHORT = { solid: "Solid", partial: "Partial", thin: "Thin" };

  /* The reasons the engine names as codes, in words. Anything it names that
   * is not here is shown as its own words with the underscores taken out. */
  const REASON_WORD = {
    no_source: "no source is attached",
    single_source: "it rests on a single source",
    low_trust_tier: "its sources are of a low trust tier",
    partial_quote: "the quote only partly matches",
    unmet_condition: "it depends on a condition your product may not meet",
  };
  const reasonWords = (reason) => {
    const key = String(reason || "").trim();
    return REASON_WORD[key] || key.replace(/_/g, " ");
  };

  /* Tiers whose word stands on its own: the same two the worker calls
   * "confirmed" (`CONFIRMING_TIERS` in background.js), so a card's strength
   * chip and its evidence mark cannot disagree. */
  const CONFIRMING = new Set(["authoritative", "manufacturer"]);

  function deriveEvidence(claim) {
    const rows = Array.isArray(claim && claim.sources) ? claim.sources.filter((r) => r && typeof r === "object") : [];
    const count = rows.length || (typeof (claim && claim.source_count) === "number" ? claim.source_count : 0);
    const reasons = [];
    if (!count) {
      reasons.push("no_source");
    } else {
      if (count === 1) reasons.push("single_source");
      // Trust is judged only where the rows say a tier at all.
      const tiers = rows.map((r) => r.tier).filter((t) => typeof t === "string" && t);
      const known = tiers.length === rows.length && tiers.length > 0;
      const confirmed = (claim && claim.strength === "confirmed") || tiers.some((t) => CONFIRMING.has(t));
      if (known && !confirmed) reasons.push("low_trust_tier");
    }
    // A claim with nothing behind it is thin outright; otherwise one weakness
    // is partial and two are thin.
    const level = reasons.includes("no_source") || reasons.length >= 2
      ? "thin" : (reasons.length === 1 ? "partial" : "solid");
    return { level, reasons };
  }

  /* What the engine said, in one shape, or null when it said nothing this
   * understands (so the caller falls back, never guesses). */
  function readEngineEvidence(value) {
    if (value === true) return { level: "thin", reasons: [] };
    if (value === false) return { level: "solid", reasons: [] };
    if (typeof value === "string") {
      return EVIDENCE_LEVELS.includes(value) ? { level: value, reasons: [] } : null;
    }
    if (!value || typeof value !== "object") return null;
    let level = EVIDENCE_LEVELS.includes(value.level) ? value.level : null;
    if (!level && typeof value.thin === "boolean") level = value.thin ? "thin" : "solid";
    if (!level) return null;
    const raw = Array.isArray(value.reasons) ? value.reasons : (value.reason ? [value.reason] : []);
    return { level, reasons: raw.map(String).filter(Boolean) };
  }

  function evidenceOf(claim) {
    const said = readEngineEvidence(claim && claim.thin);
    return said || deriveEvidence(claim);
  }

  /* The three steps. `all` shows everything; `hide_thin` hides what is thin;
   * `strict` shows only what is solid. Anything else is `all`: a setting the
   * panel cannot read must never hide evidence. */
  const SENSITIVITIES = ["all", "hide_thin", "strict"];
  const normaliseSensitivity = (value) => (SENSITIVITIES.includes(value) ? value : "all");

  function isHidden(level, sensitivity) {
    const mode = normaliseSensitivity(sensitivity);
    if (mode === "strict") return level !== "solid";
    if (mode === "hide_thin") return level === "thin";
    return false;
  }

  /* Split a list of claims by the reader's setting. `reveal` shows them all
   * anyway: hidden is a view, never a deletion. */
  function filterByEvidence(claims, sensitivity, reveal) {
    const all = Array.isArray(claims) ? claims : [];
    if (reveal) return { shown: all, hidden: [] };
    const shown = [];
    const hidden = [];
    for (const claim of all) (isHidden(evidenceOf(claim).level, sensitivity) ? hidden : shown).push(claim);
    return { shown, hidden };
  }

  /* "3 thin findings hidden" / "1 finding hidden": "thin" only when the
   * setting hides nothing but thin ones, because strict also hides partial
   * evidence and calling that thin would be wrong. */
  function hiddenWords(count, sensitivity, revealed) {
    const kind = normaliseSensitivity(sensitivity) === "strict" ? "" : "thin ";
    return `${count} ${kind}finding${count === 1 ? "" : "s"} ${revealed ? "shown" : "hidden"}`;
  }

  function evidenceLabel(evidence) {
    const why = evidence.reasons.length
      ? evidence.reasons.map(reasonWords).join("; ")
      : (evidence.level === "solid" ? "more than one source, and no weakness found" : "");
    return why ? `${EVIDENCE_WORD[evidence.level]}: ${why}` : EVIDENCE_WORD[evidence.level];
  }

  /* The mark: three rising bars, lit one, two or three. Shape and word carry
   * the level, so it does not depend on colour. Focusable, so the reason is
   * as reachable by keyboard as by pointer; the panel draws it (one tip, not
   * clipped by the card), reading it from the label. */
  function evidenceMarkup(evidence) {
    const lit = { thin: 1, partial: 2, solid: 3 }[evidence.level];
    const label = evidenceLabel(evidence);
    const bar = (i, h) => `<rect x="${i * 5}" y="${12 - h}" width="3.5" height="${h}" rx="0.8" data-lit="${i < lit ? "1" : "0"}"/>`;
    return `<span class="lite-rc-ev" data-level="${evidence.level}" role="img" tabindex="0"
        aria-label="${escapeHtml(label)}">
      <svg width="14" height="12" viewBox="0 0 14 12" aria-hidden="true">${bar(0, 4)}${bar(1, 8)}${bar(2, 12)}</svg>
      ${evidence.level === "solid" ? "" : `<span class="lite-rc-ev-word" aria-hidden="true">${EVIDENCE_SHORT[evidence.level]}</span>`}
    </span>`;
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

    const sources = readSources(claim);
    const evidence = evidenceOf(claim);
    // The first quote, ahead of opening the card: the claim is the headline
    // and its evidence is the line under it, so a collapsed card already says
    // what it rests on.
    const peekSource = sources.find((one) => one.quote);

    const article = document.createElement("article");
    article.className = "lite-rc";
    article.dataset.sev = sev;
    article.dataset.strength = strengthAttr;
    article.dataset.evidence = evidence.level;
    article.dataset.open = open ? "1" : "0";
    if (compact) article.dataset.compact = "1";

    article.innerHTML = `
      <div class="lite-rc-head">
        <div class="lite-rc-domain" aria-hidden="true">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="miter"><path d="M12 3 1.5 21h21z"/><line x1="12" y1="10" x2="12" y2="14"/><line x1="12" y1="17.5" x2="12" y2="17.6"/></svg>
        </div>
        <div class="lite-rc-titlebox">
          <div class="lite-rc-title">${renderRichText(claim.title)}</div>
          <div class="lite-rc-meta">
            <span class="lite-rc-strength" data-strength="${escapeHtml(strengthAttr)}">${escapeHtml(strengthLabel)}</span>
            <span class="sep" aria-hidden="true"> · </span><span>${escapeHtml(claim.domain || "")}</span>
            ${confText ? `<span class="sep" aria-hidden="true"> · </span><span>conf ${confText}</span>` : ""}
            ${evidenceMarkup(evidence)}
          </div>
          ${peekSource ? `<div class="lite-rc-peek"><span class="lite-rc-peek-src">${escapeHtml(peekSource.domain)}</span> \u201c${escapeHtml(peekSource.quote)}\u201d</div>` : ""}
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
            <p class="lite-rc-text">${renderRichText(claim.body || "")}</p>
            ${sourcesMarkup(sources)}
            ${shownWhy.length ? `
              <div class="lite-rc-why">
                ${shownWhy.map((w) => `<span class="lite-rc-why-chip">${escapeHtml(w)}</span>`).join("")}
              </div>` : ""}
            ${claim.advice ? `
              <div class="lite-rc-insp">
                <span class="lite-rc-insp-icon">${iconSvg("eye", { size: 13 })}</span>
                <div class="lite-rc-insp-body">
                  <div class="lite-rc-insp-label">What to ask</div>
                  ${renderRichText(claim.advice)}
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
    renderRichText,
    readSources,
    evidenceOf,
    deriveEvidence,
    filterByEvidence,
    normaliseSensitivity,
    hiddenWords,
    FACT_WORD,
  };
})();
