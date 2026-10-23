/* The reader as a buyer, as the panel draws it.
 *
 * Pure renderers: data in, an HTML string out, every value escaped. What a
 * price verdict, an audit or a pick *means* is decided by the app
 * (`app/pricewatch.py`, `app/audit.py`, `app/pick.py`); this file only has
 * words and tones for the closed lists those modules return, so a verdict this
 * file does not know is drawn as plain text, never as reassurance. */

(function () {
  function esc(value) {
    if (value == null) return "";
    return String(value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function money(amount, currency) {
    if (amount == null || Number.isNaN(Number(amount))) return "";
    const text = Number(amount).toLocaleString(undefined, { maximumFractionDigits: 2 });
    return currency ? `${text} ${currency}` : text;
  }

  // Tone is a colour class, never the verdict itself: "muted" says the app does
  // not know enough to judge, which must not read as good news.
  const PRICE_TONE = { lowest: "good", usual: "neutral", high: "warn", thin: "muted", first: "muted" };
  const PRICE_WORD = {
    lowest: "Lowest seen", usual: "Usual price", high: "High right now",
    thin: "Not enough history", first: "First sighting",
  };
  const DISCOUNT_TONE = { real: "good", inflated: "bad", usual_price: "warn", unknown: "muted" };
  const DISCOUNT_WORD = {
    real: "Discount holds up", inflated: "Old price looks invented",
    usual_price: "Not a real sale", unknown: "Discount unchecked",
  };
  const SELLER_WORD = { green: "Seller looks fine", amber: "Check the seller", red: "Seller warning" };
  const SELLER_TONE = { green: "good", amber: "warn", red: "bad" };
  const CLAIM_WORD = {
    backed: "backed on the page", unbacked: "no evidence on the page",
    seller_word: "only the seller's word", puffery: "no measure could back it",
  };
  const CLAIM_TONE = { backed: "good", unbacked: "warn", seller_word: "warn", puffery: "muted" };
  const CONFIDENCE_WORD = {
    clear: "A clear pick", close: "A close call", toss_up: "Nearly a toss-up",
    thin: "Little to go on",
  };

  function chip(tone, text) {
    return `<span class="lite-buy-chip" data-tone="${esc(tone)}">${esc(text)}</span>`;
  }

  function sparkline(series) {
    const prices = (series || []).map((one) => Number(one.price)).filter((n) => Number.isFinite(n));
    if (prices.length < 2) return "";
    const low = Math.min(...prices);
    const span = Math.max(...prices) - low || 1;
    const step = 100 / (prices.length - 1);
    const points = prices.map((price, index) =>
      `${(index * step).toFixed(1)},${(22 - ((price - low) / span) * 20).toFixed(1)}`).join(" ");
    const label = `Price over time, from ${money(prices[0])} to ${money(prices[prices.length - 1])}`;
    return `<svg class="lite-buy-line" viewBox="0 0 100 24" preserveAspectRatio="none" role="img"
      aria-label="${esc(label)}"><polyline fill="none" stroke="currentColor" stroke-width="1.6"
      vector-effect="non-scaling-stroke" points="${points}"/></svg>`;
  }

  function renderPrice(price) {
    if (!price) return "";
    const tone = PRICE_TONE[price.verdict] || "muted";
    const word = PRICE_WORD[price.verdict];
    let discount = "";
    if (price.discount) {
      discount = `<p class="lite-buy-discount" data-tone="${esc(DISCOUNT_TONE[price.discount] || "muted")}">
        ${esc(price.discount_summary || DISCOUNT_WORD[price.discount] || "")}</p>`;
    }
    // Only a web address becomes a link: the app keeps pages the reader opened,
    // but a link is the one place a stored string is followed, so it is checked here too.
    const elsewhere = (price.elsewhere || [])
      .filter((one) => /^https?:\/\//i.test(String(one.url || "")))
      .filter((one) => one.price < price.price * 0.97)
      .slice(0, 2).map((one) => `<li><a href="${esc(one.url)}" target="_blank" rel="noopener noreferrer">
        ${esc(one.host)}</a> ${esc(money(one.price, one.currency))}</li>`).join("");
    return `<div class="lite-buy-price">
      <div class="lite-buy-now"><strong>${esc(money(price.price, price.currency))}</strong>
        ${word ? chip(tone, word) : ""}
        ${price.discount && DISCOUNT_WORD[price.discount] ? chip(DISCOUNT_TONE[price.discount], DISCOUNT_WORD[price.discount]) : ""}
      </div>
      ${sparkline(price.series)}
      <p class="lite-buy-note">${esc(price.summary || "")}</p>
      ${discount}
      ${elsewhere ? `<p class="lite-buy-note">Cheaper elsewhere Kriko has seen:</p><ul class="lite-buy-elsewhere">${elsewhere}</ul>` : ""}
    </div>`;
  }

  function renderFit(fit) {
    if (!fit) return "";
    const broken = (fit.breaks || []).length > 0;
    const good = !broken && fit.score >= 60;
    if (!broken && !good && !(fit.reasons || []).length) return "";
    const title = broken ? "Not for you" : good ? "Fits what you need" : "What Kriko can check against what you need";
    const rows = (fit.reasons || []).map((one) =>
      `<li data-kind="${esc(one.kind)}">${esc(one.message)}</li>`).join("");
    return `<div class="lite-buy-fit" data-tone="${broken ? "bad" : good ? "good" : "muted"}">
      <strong>${esc(title)}</strong><ul>${rows}</ul></div>`;
  }

  function renderAudit(audit) {
    if (!audit) return "";
    const seller = audit.seller || {};
    const reviews = audit.reviews || {};
    const claims = (audit.claims && audit.claims.items) || [];
    const rows = [];
    if (seller.level && seller.level !== "green") {
      rows.push(`<li>${chip(SELLER_TONE[seller.level] || "muted", SELLER_WORD[seller.level] || "Seller")}
        ${esc((seller.notes || []).join("; "))}</li>`);
    }
    if (reviews.doubtful) {
      rows.push(`<li>${chip("warn", `Rated ${reviews.adjusted} after few ratings are discounted`)}
        ${esc((reviews.notes || []).join("; "))}</li>`);
    }
    for (const one of claims) {
      rows.push(`<li>${chip(CLAIM_TONE[one.status] || "muted", one.status === "backed" ? "Backed" : "Unbacked")}
        “${esc(one.phrase)}”: ${esc(one.status === "backed" ? CLAIM_WORD.backed : one.why || CLAIM_WORD[one.status] || "")}</li>`);
    }
    if (!rows.length) return "";
    const meter = audit.claims && audit.claims.meter != null
      ? ` <span class="lite-buy-meter" title="Share of the page's checkable claims it also shows evidence for">${esc(audit.claims.meter)}% of claims backed</span>` : "";
    return `<details class="lite-buy-audit" ${seller.level === "red" ? "open" : ""}>
      <summary>Listing check${meter}</summary><ul>${rows.join("")}</ul></details>`;
  }

  function renderActions(buyer, ui) {
    const watch = buyer.watch;
    if (ui && ui.watchForm) {
      const suggested = buyer.price ? Math.floor(buyer.price.price * 0.9) : "";
      return `<form class="lite-buy-form" data-act="watch-save">
        <label>Tell me at or below
          <input name="target" inputmode="decimal" value="${esc(suggested)}" aria-label="Price to be told at"/></label>
        ${buyer.cloud && buyer.cloud.connected
          ? `<label class="lite-buy-check" title="Your relay reads this page while your computer is off, so it is told the page.">
              <input type="checkbox" name="cloud"/> Also watch while my computer is off</label>` : ""}
        <button type="submit" class="lite-buy-btn" data-primary="1">Watch</button>
        <button type="button" class="lite-buy-btn" data-act="watch-cancel">Cancel</button></form>`;
    }
    const watchButton = watch
      ? `<span class="lite-buy-watching">Watching${watch.target ? ` · alert at ${esc(money(watch.target, watch.currency))} or less` : ""}</span>
         <button type="button" class="lite-buy-btn" data-act="unwatch" data-id="${esc(watch.watch_id)}">Stop</button>`
      : `<button type="button" class="lite-buy-btn" data-act="watch-open">Watch this price</button>`;
    const bought = ui && ui.bought
      ? `<span class="lite-buy-watching">Noted. Kriko will ask how it went.</span>`
      : `<button type="button" class="lite-buy-btn" data-act="bought">I bought this</button>`;
    return `<div class="lite-buy-actions">${watchButton}${bought}</div>`;
  }

  /* The whole card, or "" when the page gave nothing to say. */
  function renderBuyerCard(buyer, ui) {
    if (!buyer) return "";
    const inner = [renderPrice(buyer.price), renderFit(buyer.fit), renderAudit(buyer.audit)].join("");
    if (!inner.trim() && !buyer.price) return "";
    return `<section class="lite-buy" aria-label="This page as a purchase">
      <h3 class="lite-buy-title">As a purchase</h3>${inner}${renderActions(buyer, ui)}</section>`;
  }

  /* "Did it hold up?", for each purchase whose question has come round. */
  function renderDue(due, ui) {
    if (!due || !due.length) return "";
    const one = due[0];
    const open = ui && ui.regretFor === one.purchase_id;
    return `<section class="lite-buy-due" aria-label="A question about something you bought">
      <p>Did your <strong>${esc(one.name)}</strong> hold up?</p>
      ${open ? `<form class="lite-buy-form" data-act="regret-save" data-id="${esc(one.purchase_id)}">
          <input name="reason" maxlength="300" placeholder="What went wrong? (optional)" aria-label="What went wrong"/>
          <button type="submit" class="lite-buy-btn" data-primary="1">Save</button></form>`
        : `<div class="lite-buy-actions">
          <button type="button" class="lite-buy-btn" data-act="answer" data-id="${esc(one.purchase_id)}" data-verdict="glad">Glad I did</button>
          <button type="button" class="lite-buy-btn" data-act="answer" data-id="${esc(one.purchase_id)}" data-verdict="fine">It's fine</button>
          <button type="button" class="lite-buy-btn" data-act="regret" data-id="${esc(one.purchase_id)}">Regret it</button>
          <button type="button" class="lite-buy-btn" data-act="snooze" data-id="${esc(one.purchase_id)}">Ask later</button></div>`}
    </section>`;
  }

  /* The committed pick of the shortlist, and the four ways to ask more of it. */
  function renderPick(result, ui) {
    if (!result) return "";
    const picked = result.picked;
    if (!picked) {
      return `<section class="lite-pick"><h3 class="lite-buy-title">Decide</h3>
        <p class="lite-buy-note">Kriko needs at least two products in the queue that it has read. Add more from their listings.</p></section>`;
    }
    const list = (items) => (items || []).map((text) => `<li>${esc(text)}</li>`).join("");
    const advice = ui && ui.advice;
    const busy = advice && advice.state === "running";
    const modes = [["pick", "Say it well"], ["debate", "Debate it"], ["tco", "Cost to own"], ["timing", "Is now the time?"]]
      .map(([mode, label]) => `<button type="button" class="lite-buy-btn" data-act="advise" data-mode="${mode}"
        ${busy ? "disabled" : ""}>${label}</button>`).join("");
    const answer = advice && advice.answer
      ? `<div class="lite-pick-answer" data-mode="${esc(advice.mode)}">${
        window.__KrikoPanelClaimCard ? window.__KrikoPanelClaimCard.renderRichText(advice.answer) : esc(advice.answer)}</div>`
      : busy ? `<p class="lite-buy-note" role="status">Your agent is working on it…</p>`
        : advice && advice.error ? `<p class="lite-buy-note" data-tone="bad">${esc(advice.error)}</p>` : "";
    const others = (result.ranked || []).slice(1).map((one) =>
      `<li>${esc(one.name)} <span class="lite-buy-note">${esc(one.score)}</span></li>`).join("");
    return `<section class="lite-pick" aria-label="Kriko's pick">
      <h3 class="lite-buy-title">Kriko's pick</h3>
      <p class="lite-pick-winner"><strong>${esc(picked.name)}</strong>
        ${chip(result.confidence === "clear" ? "good" : result.confidence === "close" ? "neutral" : "warn",
          CONFIDENCE_WORD[result.confidence] || "")}
        ${picked.price != null ? `<span class="lite-buy-note">${esc(money(picked.price, picked.currency))}</span>` : ""}</p>
      ${(picked.strengths || []).length ? `<ul class="lite-pick-for">${list(picked.strengths)}</ul>` : ""}
      ${(result.gave_up || []).length ? `<p class="lite-buy-note">It costs you:</p><ul>${list(result.gave_up)}</ul>` : ""}
      ${(result.switch_if || []).length ? `<p class="lite-buy-note">Switch if:</p><ul>${list(result.switch_if)}</ul>` : ""}
      ${(result.check_first || []).length ? `<p class="lite-buy-note">Check first:</p><ul>${list(result.check_first)}</ul>` : ""}
      ${others ? `<details class="lite-buy-rest"><summary>The rest</summary><ul>${others}</ul></details>` : ""}
      <div class="lite-buy-actions">${modes}</div>${answer}</section>`;
  }

  /* The look before paying: a verdict and what it rests on. */
  function renderGuard(result) {
    if (!result || result.verdict === "go") return "";
    const rows = (result.findings || []).filter((one) => one.severity !== "ok").slice(0, 5)
      .map((one) => `<li data-severity="${esc(one.severity)}">${esc(one.message)}</li>`).join("");
    const title = result.verdict === "stop" ? "Stop and check before paying" : "Check before paying";
    return `<div class="kriko-guard-card" data-verdict="${esc(result.verdict)}" role="alert">
      <strong>${esc(title)}</strong><ul>${rows}</ul>
      <div class="kriko-guard-actions"><button type="button" data-act="guard-open">Open Kriko</button>
        <button type="button" data-act="guard-dismiss">Dismiss</button></div></div>`;
  }

  window.__KrikoBuyer = {
    renderBuyerCard, renderDue, renderPick, renderGuard, renderPrice, renderFit, renderAudit,
    sparkline, money, esc,
  };
})();
