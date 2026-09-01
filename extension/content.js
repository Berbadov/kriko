// The listing scraper. Its whole job is to report what the page says.
//
// Before Phase 6c this file also decided what the page MEANT: which label was
// the fuel type, that "Seri" holds the model while "Model" holds the trim,
// that "110 hp" under "Engine Capacity" is not a displacement. All of that is
// site knowledge, and site knowledge now lives in the pack, as
// `packs/cars/adapters/sahibinden.json`. Two reasons it moved:
//
//   * A site redesign used to require an extension release. It is now a data
//     edit — the same rule the catalog has always been held to.
//   * Interpreting here meant a hardcoded list of car makes in JavaScript, and
//     a make missing from it silently produced a listing nobody could match.
//
// What is left is the part only a browser can do: find label/value pairs in
// markup that changes without notice. Even the labels to look for come down
// the wire from the installed pack (`GET /api/adapters`), so this file carries
// no vocabulary of its own.

function textBySelector(selector) {
  const node = document.querySelector(selector);
  return node ? node.textContent.trim() : null;
}

function cleanText(text) {
  if (!text) return null;
  return text.replace(/\s+/g, " ").trim();
}

// Last resort when no known container selector matches: find the LABEL text
// itself anywhere in the document and read the value next to it. Sahibinden has
// redesigned this markup repeatedly, and every redesign silently zeroed every
// field — the extension kept "working" while the server answered "no identity
// resolved". Anchoring on the label survives a class rename.
//
// `knownLabels` comes from the server, casefolded. With none supplied this
// finds nothing, which is correct: an empty scrape fails open and is visible,
// while a scrape guessed from a stale built-in list is wrong and is not.
// Reduce a label the way the server reduces it, or the scan finds nothing and
// nobody can see why. Combining marks are the trap: "İ".toLowerCase() is "i"
// plus a combining dot, so "İlan No" and "ilan no" are different strings on
// both ends — and the server has already stripped its side, which is what lets
// a pack author write "motor gucu" once instead of enumerating every spelling.
//
// Deliberately NOT `toLocaleLowerCase("tr")`: Turkish casing maps "I" to "ı",
// the server's casefold maps it to "i", and the two ends must agree more than
// either needs to be locally correct.
function foldLabel(text) {
  return String(text)
    .toLowerCase()
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .normalize("NFC")
    .trim()
    .replace(/:$/, "")
    .trim();
}

function extractInfoListByLabelScan(knownLabels) {
  const details = {};
  const wanted = new Set((knownLabels || []).map(foldLabel));
  if (!wanted.size) return details;

  for (const node of document.querySelectorAll(
    "span, div, dt, th, td, strong, b, p, label"
  )) {
    const text = cleanText(node.textContent);
    if (!text || text.length > 32) continue;
    if (!wanted.has(foldLabel(text)) || details[text]) continue;

    // The value sits next to the label — as a sibling, or as the parent's other
    // half when both are wrapped (…<span>Yıl</span><span>2014</span>…).
    const sibling = node.nextElementSibling;
    const value = cleanText(sibling && sibling.textContent);
    if (value && value !== text) {
      details[text] = value;
    }
  }
  return details;
}

function extractInfoList(knownLabels) {
  const details = {};

  const liItems = document.querySelectorAll(
    "ul.classifiedInfoList li, ul[class*='InfoList'] li, .classified-info li, .classifiedInfo li"
  );
  for (const li of liItems) {
    const strong = li.querySelector("strong, span.label, .title, b");
    if (!strong) continue;
    const label = cleanText(strong.textContent);
    let valueText = li.textContent;
    if (strong.textContent) {
      valueText = valueText.replace(strong.textContent, "");
    }
    const value = cleanText(valueText);
    if (label && value) {
      details[label] = value;
    }
  }

  if (Object.keys(details).length > 0) {
    return details;
  }

  const trItems = document.querySelectorAll(
    "table.classifiedInfo tr, table.classified-info tr, table[class*='InfoList'] tr, .classified-properties tr"
  );
  for (const tr of trItems) {
    const th = tr.querySelector("th, td:first-child");
    const td = tr.querySelector("td:last-child");
    if (!th || !td || th === td) continue;
    const label = cleanText(th.textContent);
    const value = cleanText(td.textContent);
    if (label && value && !details[label]) {
      details[label] = value;
    }
  }

  const dts = document.querySelectorAll("dl dt");
  for (const dt of dts) {
    const dd = dt.nextElementSibling;
    if (!dd || dd.tagName !== "DD") continue;
    const label = cleanText(dt.textContent);
    const value = cleanText(dd.textContent);
    if (label && value && !details[label]) {
      details[label] = value;
    }
  }

  if (Object.keys(details).length === 0) {
    return extractInfoListByLabelScan(knownLabels);
  }

  return details;
}

function extractTechnicalDetails() {
  const root = document.querySelector("#technical-details, .classifiedTechDetails");
  if (!root) return {};

  const details = {};
  root.querySelectorAll("table tr").forEach(tr => {
    const title = cleanText(tr.querySelector("td.title")?.childNodes?.[0]?.textContent)
      || cleanText(tr.querySelector("td.title")?.textContent);
    const value = cleanText(tr.querySelector("td.value")?.textContent);
    if (title && value && !details[title]) {
      details[title] = value;
    }
  });
  return details;
}


// ── Sahibinden "Boya & Değişen" silhouette panel ──
// The page renders a car silhouette where each panel (kapı, çamurluk, tampon,
// kaput, etc.) carries one of four states: orijinal, boyalı, lokal boyalı,
// değişen. The DOM has been through a few redesigns; we try the explicit
// state classes first, then fall back to label-headed paragraphs.
function extractDamageInfo() {
  const states = {
    changed: new Set(),       // değişen — the "remove/insert" parts
    painted: new Set(),       // boyalı
    local_painted: new Set(), // lokal boyalı
    original: new Set(),
  };

  // Sahibinden's current layout: one `.car-damage-info-list` div per state.
  // Each block's first text node / heading reads "Boyalı Parçalar",
  // "Değişen Parçalar", "Lokal Boyalı Parçalar", or "Orijinal Parçalar", and
  // its parts are <li class="selected-damage">PartName</li> below.
  const STATE_HEADERS = [
    { state: "changed",       re: /de[ğg]i[şs]en/i },
    { state: "local_painted", re: /lokal\s*boyal[ıi]/i },
    { state: "painted",       re: /boyal[ıi]/i },
    { state: "original",      re: /orijinal/i },
  ];
  const damageBlocks = document.querySelectorAll(".car-damage-info-list");
  for (const block of damageBlocks) {
    // Read the block's heading. Prefer an explicit <hN>/title element; fall
    // back to the first non-empty line of textContent — split(/\n/)[0] hits
    // a blank leading line on the real DOM.
    const headEl = block.querySelector("h1, h2, h3, h4, h5, .title, .header");
    let headerText = cleanText(headEl?.textContent) || "";
    if (!headerText) {
      for (const line of (block.textContent || "").split(/\n+/)) {
        const t = line.trim();
        if (t) { headerText = t; break; }
      }
    }
    let stateKey = null;
    for (const { state, re } of STATE_HEADERS) {
      if (re.test(headerText)) { stateKey = state; break; }
    }
    if (!stateKey) continue;
    block.querySelectorAll("li.selected-damage").forEach(li => {
      const part = cleanText(li.textContent);
      if (part && part.length < 60) states[stateKey].add(part);
    });
  }

  // Legacy fallback: older sahibinden DOMs encoded state in CSS classes on
  // the silhouette nodes themselves. Only run when the modern selector above
  // produced nothing.
  if (
    states.changed.size === 0 && states.painted.size === 0 &&
    states.local_painted.size === 0 && states.original.size === 0
  ) {
    const CLASS_STATE = [
      ["changed",       /(^|\s)(bgChanged|degisen|changed|cgEdit)(\s|$)/i],
      ["local_painted", /(^|\s)(bgLocalPainted|lokal|localPainted|localPaint)(\s|$)/i],
      ["painted",       /(^|\s)(bgPainted|boyali|painted|cgPaint)(\s|$)/i],
      ["original",      /(^|\s)(bgOriginal|orijinal|original)(\s|$)/i],
    ];
    const panelNodes = document.querySelectorAll(
      "[class*='damageInfo'] *, [id*='damageInfo'] *, " +
      "[class*='Damage'] *, [id*='Damage'] *, " +
      "[class*='Boya'] *, [id*='Boya'] *"
    );
    for (const node of panelNodes) {
      const cls = node.className && typeof node.className === "string" ? node.className : "";
      if (!cls) continue;
      let matchedState = null;
      for (const [state, re] of CLASS_STATE) {
        if (re.test(cls)) { matchedState = state; break; }
      }
      if (!matchedState) continue;
      const partName = cleanText(
        node.getAttribute("title") ||
        node.getAttribute("data-title") ||
        node.getAttribute("aria-label") ||
        node.textContent
      );
      if (partName && partName.length < 80) {
        states[matchedState].add(partName);
      }
    }
  }

  // Tramer amount — try labeled field first, then scan the description text.
  let tramerAmount = null;
  let tramerCurrency = null;
  const tramerSources = [];
  document.querySelectorAll(
    "[id*='Tramer'], [class*='tramer'], [id*='Hasar'], [class*='hasar']"
  ).forEach(n => tramerSources.push(cleanText(n.textContent)));
  const descNode = document.querySelector(
    "#classifiedDescription, .classifiedDescription, [itemprop='description']"
  );
  if (descNode) tramerSources.push(cleanText(descNode.textContent));

  for (const txt of tramerSources) {
    if (!txt) continue;
    // "Tramer 9.500 TL" / "Tramer: 12,000 TL" / "Hasar Kaydı 2.000 TL"
    const m = txt.match(/(?:tramer|hasar\s*kayd[ıi])[\s:]*([\d.,]+)\s*(tl|try|usd|eur|\$|€)/i);
    if (m) {
      tramerAmount = Number(m[1].replace(/[.,]/g, ""));
      tramerCurrency = /tl|try/i.test(m[2]) ? "TRY" : m[2].toUpperCase();
      break;
    }
  }

  const toArr = s => Array.from(s).sort();
  return {
    changed: toArr(states.changed),
    painted: toArr(states.painted),
    local_painted: toArr(states.local_painted),
    original: toArr(states.original),
    tramer_amount: tramerAmount,
    tramer_currency: tramerCurrency,
  };
}

// ── Sahibinden "Donanım" (equipment) block ──
// Layout: a Donanım section split into subcategories (Güvenlik, İç Donanım,
// Dış Donanım, Multimedya, Aydınlatma) where included features carry a
// `selected` (or similar) class. We group features by their nearest preceding
// subcategory header so the panel can render them in buckets.
// Patterns match sahibinden's Turkish subheaders ("Güvenlik", "İç Donanım"…)
// but the key — what gets displayed in the panel — is the English name.
const EQUIPMENT_CATEGORY_PATTERNS = [
  { key: "Safety",     re: /g[üu]venlik|safety/i },
  { key: "Interior",   re: /i[çc]\s*donan[ıi]m|interior/i },
  { key: "Exterior",   re: /d[ıi][şs]\s*donan[ıi]m|exterior/i },
  { key: "Multimedia", re: /multimedya|multimedia|info\s*tainment/i },
  { key: "Lighting",   re: /ayd[ıi]nlatma|lighting/i },
];

function _classifyEquipmentHeader(text) {
  if (!text) return null;
  for (const { key, re } of EQUIPMENT_CATEGORY_PATTERNS) {
    if (re.test(text)) return key;
  }
  return null;
}

function _findEquipmentCategory(node) {
  // Walk up to the nearest container then back through previous siblings
  // looking for a header that names a known sahibinden subcategory.
  let walker = node;
  let hops = 0;
  while (walker && hops < 6) {
    let sib = walker.previousElementSibling;
    while (sib) {
      if (/^H[1-6]$/.test(sib.tagName) || /title|head|category|subhead/i.test(sib.className || "")) {
        const hit = _classifyEquipmentHeader(cleanText(sib.textContent));
        if (hit) return hit;
      }
      const inner = sib.querySelector?.("h2, h3, h4, h5, h6, .title, .head, .category");
      if (inner) {
        const hit = _classifyEquipmentHeader(cleanText(inner.textContent));
        if (hit) return hit;
      }
      sib = sib.previousElementSibling;
    }
    walker = walker.parentElement;
    hops += 1;
  }
  return null;
}

function extractEquipment() {
  const buckets = {};            // { category: Set<feature> }
  const ensure = (key) => (buckets[key] = buckets[key] || new Set());

  const blocks = document.querySelectorAll(
    "#classifiedProperties, .classifiedProperties, " +
    "[id*='Donanim'], [class*='Donanim'], " +
    "[id*='donanim'], [class*='donanim'], " +
    "[id*='Equipment'], [class*='Equipment']"
  );
  for (const block of blocks) {
    block.querySelectorAll("li, span, div").forEach(node => {
      // Skip nodes that are actually body-damage entries (sahibinden marks
      // those with class "selected-damage" inside ".car-damage-info-list" —
      // they get routed through extractDamageInfo() instead).
      const cls = (node.className && typeof node.className === "string") ? node.className : "";
      if (/selected\-damage/i.test(cls)) return;
      if (node.closest && node.closest(".car-damage-info-list")) return;
      if (!/selected/i.test(cls)) return;
      if (/unselected|deselected|not\-selected/i.test(cls)) return;
      const txt = cleanText(node.textContent);
      if (!txt || txt.length <= 1 || txt.length >= 60) return;
      const category = _findEquipmentCategory(node) || "Other";
      ensure(category).add(txt);
    });
  }

  // Fallback: header-walk for pages without [class*='donanim'] containers.
  if (Object.keys(buckets).length === 0) {
    const headers = Array.from(document.querySelectorAll("h2, h3, h4, .title")).filter(
      h => /donan[ıi]m/i.test(h.textContent || "") || _classifyEquipmentHeader(h.textContent || "")
    );
    for (const head of headers) {
      const category = _classifyEquipmentHeader(head.textContent) || "Other";
      let cursor = head.nextElementSibling;
      let hops = 0;
      while (cursor && hops < 4) {
        cursor.querySelectorAll("li.selected, li[class*='selected']").forEach(li => {
          const t = cleanText(li.textContent);
          if (t && t.length < 60) ensure(category).add(t);
        });
        if (ensure(category).size > 0) break;
        cursor = cursor.nextElementSibling;
        hops += 1;
      }
    }
  }

  const grouped = {};
  for (const [cat, set] of Object.entries(buckets)) {
    grouped[cat] = Array.from(set).sort();
  }
  return grouped;
}

// ── the scrape ──────────────────────────────────────────────────────────

const DESCRIPTION_SELECTORS = [
  "#classifiedDescription .classifiedDescriptionContent",
  "#classifiedDescription",
  ".classifiedDescription",
  "[itemprop='description']",
];

// `fields` is what goes on the wire: the page's own labels, its own values,
// no interpretation. `listing` is what stays here — the panel renders the
// damage and equipment panels locally, and the engine has no rule for them,
// so there is no reason to send them anywhere.
function buildScrape(knownLabels) {
  const infoList = extractInfoList(knownLabels);
  const technical = extractTechnicalDetails();

  // The info list wins a collision. Both tables label a row "Engine Capacity"
  // on the English page and they disagree; deciding which is believable is a
  // range question, and ranges are the adapter's.
  const fields = { ...technical, ...infoList };

  let description = null;
  for (const selector of DESCRIPTION_SELECTORS) {
    description = textBySelector(selector);
    if (description) break;
  }

  return {
    url: window.location.href,
    title: textBySelector("h1.classifiedTitle") || textBySelector("h1"),
    description,
    fields,
    listing: {
      damage_info: extractDamageInfo(),
      equipment: extractEquipment(),
    },
  };
}

// ── messages ────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "GET_SCRAPE") {
    sendResponse({ ok: true, payload: buildScrape(request.labels) });
    return;
  }

  if (request.type === "TRIGGER_ANALYSIS") {
    chrome.runtime.sendMessage(
      { type: "ANALYZE", payload: { url: window.location.href } },
      (response) => sendResponse(response)
    );
    return true; // async
  }
});

// ── auto-trigger ────────────────────────────────────────────────────────
//
// Which sites are worth scraping is the installed packs' answer, not this
// file's. The background worker holds the adapter list; here we only report
// that a page finished loading and let it decide.
(function autoTrigger() {
  setTimeout(() => {
    chrome.runtime.sendMessage({
      type: "PAGE_LOADED",
      payload: { url: window.location.href, host: window.location.hostname },
    });
  }, 1500);
})();
