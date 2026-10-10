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

    // The value sits next to the label. The comment here has always said "as a
    // sibling, or as the parent's other half when both are wrapped", but only
    // the first of those was ever written, so a row shaped
    // `<div><span>Yıl</span></div><div>2014</div>` — the label wrapped one
    // level deeper than the value — read as nothing at all. Three shapes, in
    // the order of how directly they answer:
    const candidates = [
      // 1. The plain sibling element: …<span>Yıl</span><span>2014</span>…
      node.nextElementSibling && node.nextElementSibling.textContent,
      // 2. Loose text right after the label, with no element around it:
      //    …<span>Yıl</span> 2014… — common wherever the value was never
      //    meant to be styled separately.
      node.nextSibling && node.nextSibling.nodeType === 3
        ? node.nextSibling.textContent
        : "",
      // 3. The parent's other half, which is what the comment promised: the
      //    label is wrapped and the value is the rest of the row. Taking the
      //    parent's text and subtracting the label leaves the value, so long
      //    as the parent holds this label and nothing else of its own.
      node.parentElement && node.parentElement.nextElementSibling
        ? node.parentElement.nextElementSibling.textContent
        : "",
    ];

    for (const candidate of candidates) {
      const value = cleanText(candidate);
      // A candidate equal to the label is the same node read twice, and one
      // that *contains* it is a wrapper we have climbed into rather than a
      // value — both mean this shape was the wrong guess, not that the row is
      // empty. Length-capped for the same reason `text` is: a whole column
      // caught by rule 3 is not a value.
      if (!value || value === text || value.length > 200) continue;
      if (foldLabel(value).includes(foldLabel(text))) continue;
      details[text] = value;
      break;
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

  // The label scan runs every time, and what the selectors above found wins
  // where both spoke.
  //
  // It used to run only when `details` was still empty, and that is why a
  // newly added site read almost nothing. The selectors above name one site's
  // own class names — `classifiedInfoList`, `classifiedInfo`,
  // `.classified-properties`. On any other site none of them match, so the
  // whole of `details` came down to the one generic branch, `dl dt`; and a
  // page with a single stray `<dl>` in a footer or a cookie notice filled
  // `details` with one junk pair, which counted as success and suppressed the
  // only scan that reads the labels the *pack* declared. One wrong row, and
  // the real ones never looked for.
  //
  // Merging rather than choosing also drops the premise that a page has
  // exactly one shape. A listing carrying half its facts in a table and half
  // in labelled spans used to yield whichever half was found first.
  const scanned = extractInfoListByLabelScan(knownLabels);
  for (const [label, value] of Object.entries(scanned)) {
    if (!details[label]) details[label] = value;
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


// ── The reader's own page, read by rules the pack declared ───────────────
//
// The damage silhouette and the equipment block are the two things the panel
// renders from the page itself rather than from the engine's answer, and until
// now they were the last site knowledge left in this file: the Turkish words
// that name a damage state, the CSS selectors that find one, the map from a
// Turkish subheading to an English bucket. Every one of them had the same
// failure mode the label lists had before Phase 6c — a site redesign, or a
// second listing site, or a category that is not cars, meant an extension
// release.
//
// They are now `local_panel` in the adapter, and everything below is an
// interpreter for it: it can count, match declared terms, and read declared
// selectors, and it cannot do anything a pack did not ask for. A pack ships no
// code here, which is the boundary `kriko/adapters.py` exists to hold — an
// installed pack must never be able to run script on a page the extension can
// see.

// Term matching folds both sides so a pack author writes one spelling rather
// than every spelling: case, accents, and the dotless i all collapse.
//
// Deliberately not `foldLabel`, which is one character-class away and must
// stay that way. `foldLabel` has to agree with the *server's* casefold, and
// that casefold leaves "ı" alone; a term here is only ever compared against
// text on the page, both ends folded by this function, so it can be kinder.
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

// A declared term matches when it appears in the folded haystack. Substring
// rather than word-boundary on purpose: "Motor Kaputu" has to match "kaput",
// and an agglutinative language's suffixes are exactly what a word boundary
// would refuse.
function matchesAnyTerm(haystack, terms) {
  const folded = foldTerm(haystack);
  if (!folded) return false;
  return (terms || []).some((term) => {
    const needle = foldTerm(term);
    return needle && folded.includes(needle);
  });
}

function _stateOfHeader(headerText, states) {
  // Array order is precedence, and it has to be: "lokal boyalı" contains
  // "boyalı", so a narrower heading is only reachable if it is tested first.
  for (const state of states || []) {
    if (matchesAnyTerm(headerText, state.header_terms)) return state.key;
  }
  return null;
}

function _headerTextOf(block, headerSelector) {
  const headEl = headerSelector ? block.querySelector(headerSelector) : null;
  const explicit = cleanText(headEl?.textContent);
  if (explicit) return explicit;
  // Fall back to the first non-empty line of textContent — splitting on the
  // first newline hits a blank leading line on the real DOM.
  for (const line of (block.textContent || "").split(/\n+/)) {
    const trimmed = line.trim();
    if (trimmed) return trimmed;
  }
  return "";
}

function _readMeasures(panel) {
  const out = {};
  for (const measure of panel.measures || []) {
    if (!measure || !measure.key) continue;
    const sources = [];
    for (const selector of measure.selectors || []) {
      document.querySelectorAll(selector).forEach((n) => sources.push(cleanText(n.textContent)));
    }
    for (const selector of measure.text_selectors || []) {
      const node = document.querySelector(selector);
      if (node) sources.push(cleanText(node.textContent));
    }
    const currencies = measure.currencies || {};
    // Built from the declared table rather than hardcoded, so a pack for a
    // market that writes its prices differently needs no edit here. The
    // symbols are escaped because "$" is a declared key and a regex operator.
    const symbols = Object.keys(currencies)
      .sort((a, b) => b.length - a.length)
      .map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|");
    const terms = (measure.terms || [])
      .map((t) => foldTerm(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "\\s*"))
      .join("|");
    if (!terms || !symbols) continue;
    const pattern = new RegExp(`(?:${terms})[\\s:]*([\\d.,]+)\\s*(${symbols})`, "i");
    for (const text of sources) {
      if (!text) continue;
      const hit = foldTerm(text).match(pattern);
      if (!hit) continue;
      out[measure.key] = Number(hit[1].replace(/[.,]/g, ""));
      if (measure.currency_key) {
        out[measure.currency_key] =
          currencies[hit[2].toLowerCase()] || measure.default_currency || null;
      }
      break;
    }
    if (!(measure.key in out)) {
      out[measure.key] = null;
      if (measure.currency_key) out[measure.currency_key] = null;
    }
  }
  return out;
}

function extractDamageInfo(panel) {
  const spec = panel || {};
  const states = spec.states || [];
  if (!states.length) return null;

  const found = {};
  for (const state of states) found[state.key] = new Set();
  const limit = spec.max_item_length || 60;

  for (const block of document.querySelectorAll(spec.block_selector || "")) {
    const stateKey = _stateOfHeader(_headerTextOf(block, spec.header_selector), states);
    if (!stateKey) continue;
    block.querySelectorAll(spec.item_selector || "").forEach((node) => {
      const name = cleanText(node.textContent);
      if (name && name.length < limit) found[stateKey].add(name);
    });
  }

  // Legacy fallback: only when the declared selectors above produced nothing,
  // because a page that answers the modern markup must not also be read
  // through a looser one.
  const legacy = spec.legacy || {};
  const empty = Object.values(found).every((set) => set.size === 0);
  if (empty && legacy.node_selector) {
    const legacyLimit = legacy.max_item_length || limit;
    for (const node of document.querySelectorAll(legacy.node_selector)) {
      const cls = node.className && typeof node.className === "string" ? node.className : "";
      if (!cls) continue;
      let stateKey = null;
      for (const state of states) {
        if (matchesAnyTerm(cls, state.legacy_class_terms)) { stateKey = state.key; break; }
      }
      if (!stateKey) continue;
      let name = null;
      for (const attribute of legacy.name_attributes || []) {
        name = cleanText(node.getAttribute(attribute));
        if (name) break;
      }
      if (!name) name = cleanText(node.textContent);
      if (name && name.length < legacyLimit) found[stateKey].add(name);
    }
  }

  const damage = {};
  for (const state of states) damage[state.key] = Array.from(found[state.key]).sort();
  return { ...damage, ..._readMeasures(spec) };
}

function _categoryOfHeader(text, categories) {
  for (const category of categories || []) {
    if (matchesAnyTerm(text, category.terms)) return category.key;
  }
  return null;
}

function _findEquipmentCategory(node, spec) {
  // Walk up to the nearest container then back through previous siblings
  // looking for a heading that names one of the declared buckets.
  let walker = node;
  let hops = 0;
  while (walker && hops < 6) {
    let sib = walker.previousElementSibling;
    while (sib) {
      if (/^H[1-6]$/.test(sib.tagName) || /title|head|category|subhead/i.test(sib.className || "")) {
        const hit = _categoryOfHeader(cleanText(sib.textContent), spec.categories);
        if (hit) return hit;
      }
      const inner = sib.querySelector?.("h2, h3, h4, h5, h6, .title, .head, .category");
      if (inner) {
        const hit = _categoryOfHeader(cleanText(inner.textContent), spec.categories);
        if (hit) return hit;
      }
      sib = sib.previousElementSibling;
    }
    walker = walker.parentElement;
    hops += 1;
  }
  return null;
}

function extractEquipment(panel) {
  const spec = (panel && panel.equipment) || {};
  if (!spec.block_selector) return {};
  const damageSpec = panel || {};
  const buckets = {};
  const ensure = (key) => (buckets[key] = buckets[key] || new Set());
  const fallback = spec.fallback_category || "Other";
  const limit = spec.max_item_length || 60;

  const isSelected = (cls) =>
    matchesAnyTerm(cls, spec.selected_class_terms) &&
    !matchesAnyTerm(cls, spec.unselected_class_terms);

  for (const block of document.querySelectorAll(spec.block_selector)) {
    block.querySelectorAll(spec.item_selector || "li").forEach((node) => {
      // Skip nodes that are actually damage entries — they belong to the
      // silhouette above and are read there instead.
      if (damageSpec.item_selector && node.matches?.(damageSpec.item_selector)) return;
      if (damageSpec.block_selector && node.closest?.(damageSpec.block_selector)) return;
      const cls = node.className && typeof node.className === "string" ? node.className : "";
      if (!isSelected(cls)) return;
      const text = cleanText(node.textContent);
      if (!text || text.length <= 1 || text.length >= limit) return;
      ensure(_findEquipmentCategory(node, spec) || fallback).add(text);
    });
  }

  // Fallback: header-walk for pages with no recognised container.
  if (Object.keys(buckets).length === 0 && spec.header_selector) {
    const headers = Array.from(document.querySelectorAll(spec.header_selector)).filter(
      (h) =>
        matchesAnyTerm(h.textContent || "", spec.section_terms) ||
        _categoryOfHeader(h.textContent || "", spec.categories)
    );
    for (const head of headers) {
      const category = _categoryOfHeader(cleanText(head.textContent), spec.categories) || fallback;
      let cursor = head.nextElementSibling;
      let hops = 0;
      while (cursor && hops < 4) {
        cursor.querySelectorAll(spec.item_selector || "li").forEach((node) => {
          const cls = node.className && typeof node.className === "string" ? node.className : "";
          if (!isSelected(cls)) return;
          const text = cleanText(node.textContent);
          if (text && text.length < limit) ensure(category).add(text);
        });
        if (ensure(category).size > 0) break;
        cursor = cursor.nextElementSibling;
        hops += 1;
      }
    }
  }

  const grouped = {};
  for (const [category, set] of Object.entries(buckets)) {
    grouped[category] = Array.from(set).sort();
  }
  return grouped;
}

// ── the page's own account of its product ───────────────────────────────
//
// B149. On a site no pack has an adapter for, the label scan above has nothing
// to look for, and the reader saw it as "Panel, but empty" or "Wrong product
// read". Most product pages already say what they sell, in a vocabulary no
// site owns: schema.org JSON-LD, written for search engines. AutoScout24's
// listing carries a `Car` with its manufacturer, model, production date,
// gearbox and odometer; MediaMarkt's a `Product` with its brand and GTIN.
//
// So this reads that, and only that — no site's class names, no site's words.
// The properties go on the wire as `ld:<property>` fields, flattened one level
// (`ld:vehicleEngine.fuelType`), and what they *mean* for a category is the
// pack's any-site adapter's business, exactly as the page's labels are.

// schema.org types that name a thing someone buys. A closed vocabulary of the
// standard, not data that grows with coverage.
const LD_PRODUCT_TYPES = new Set([
  "product", "individualproduct", "productmodel",
  "vehicle", "car", "motorcycle", "busorcoach", "motorizedbicycle",
]);
// The more specific of the two when a page nests one in the other, as
// AutoScout24 does (a `Product` whose offer's `itemOffered` is the `Car`).
const LD_VEHICLE_TYPES = new Set(["vehicle", "car", "motorcycle", "busorcoach", "motorizedbicycle"]);

function _ldTypes(node) {
  const raw = node && node["@type"];
  return (Array.isArray(raw) ? raw : [raw])
    .filter((one) => typeof one === "string")
    .map((one) => one.replace(/^.*[/#:]/, "").toLowerCase());
}

// Every object in the JSON-LD blocks, depth-first. Pages wrap the product in
// `@graph`, in an `Offer`'s `itemOffered`, in a `BuyAction`'s `object`; walking
// everything finds it wherever it is put.
function _ldNodes() {
  const out = [];
  const walk = (value, depth) => {
    if (depth > 8 || value === null || typeof value !== "object") return;
    if (Array.isArray(value)) { value.forEach((one) => walk(one, depth + 1)); return; }
    out.push(value);
    Object.values(value).forEach((one) => walk(one, depth + 1));
  };
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { walk(JSON.parse(script.textContent || ""), 0); } catch (_) { /* a broken block is skipped */ }
  }
  // Microdata is the same standard in DOM form. Read only properties owned
  // by this scope, so a recommendation's SKU cannot leak into the product.
  const readScope = (root, depth = 0) => {
    if (depth > 8) return {};
    const node = { "@type": root.getAttribute("itemtype") || "" };
    for (const field of root.querySelectorAll("[itemprop]")) {
      if (field.parentElement?.closest("[itemscope]") !== root) continue;
      const value = field.hasAttribute("itemscope") ? readScope(field, depth + 1)
        : field.getAttribute("content") ?? field.getAttribute("href")
          ?? field.getAttribute("datetime") ?? cleanText(field.textContent);
      for (const key of (field.getAttribute("itemprop") || "").split(/\s+/)) {
        if (!key) continue;
        if (node[key] === undefined) node[key] = value;
        else node[key] = [...(Array.isArray(node[key]) ? node[key] : [node[key]]), value];
      }
    }
    return node;
  };
  for (const scope of document.querySelectorAll("[itemscope][itemtype]")) {
    if (!scope.parentElement?.closest("[itemscope]")) walk(readScope(scope), 0);
  }
  return out;
}

// A property's value as page text: a string as it is, a number as digits, a
// `Brand` or `Organization` by its name, a `QuantitativeValue` by its value.
function _ldText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return cleanText(value) || "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return [...new Set(value.map(_ldText).filter(Boolean))].join("; ");
  if (typeof value === "object") {
    if (value.value !== undefined) {
      const figure = _ldText(value.value);
      const unit = _ldText(value.unitText || value.unitCode);
      return `${figure}${unit ? ` ${unit}` : ""}`;
    }
    if (value.name !== undefined) return _ldText(value.name);
  }
  return "";
}

const LD_SKIP = new Set(["@context", "@id", "image", "url", "offers", "review",
  "aggregaterating", "description", "logo", "potentialaction", "sameas"]);

function _ldFlatten(node, fields, resolve = (value) => value, prefix = "ld:", depth = 0, seen = new Set()) {
  node = resolve(node);
  if (!node || typeof node !== "object" || depth > 4 || seen.has(node)) return;
  const visited = new Set(seen).add(node);
  for (const [key, value] of Object.entries(node)) {
    if (Object.keys(fields).length >= 120) break;
    if (LD_SKIP.has(key.toLowerCase()) ||
        ["isvariantof", "hasvariant", "issimilarto", "isrelatedto"].includes(key.toLowerCase())) continue;
    if (key.toLowerCase() === "additionalproperty") {
      for (const entry of (Array.isArray(value) ? value : [value])) {
        if (Object.keys(fields).length >= 120) break;
        const property = resolve(entry);
        if (!property || typeof property !== "object") continue;
        const label = _ldText(property.name || property.propertyID);
        const figure = _ldText(property.value);
        const unit = _ldText(property.unitText || property.unitCode);
        if (label && figure && label.length <= 80) {
          fields[`${prefix}additionalProperty.${label}`] = `${figure}${unit ? ` ${unit}` : ""}`.slice(0, 500);
        }
      }
      continue;
    }
    const values = (Array.isArray(value) ? value : [value]).map(resolve);
    const text = _ldText(values);
    const name = `${prefix}${key}`;
    if (text && !fields[name]) fields[name] = text.slice(0, 500);
    // Keep separately labelled components rather than combining their codes.
    // Variants, recommendations and parent groups are different products.
    for (const [index, inner] of values.entries()) {
      if (inner && typeof inner === "object") {
        const nested = values.length > 1 ? `${name}[${index + 1}].` : `${name}.`;
        _ldFlatten(inner, fields, resolve, nested, depth + 1, visited);
      }
    }
  }
}

function _metaContent(name) {
  const node = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
  return cleanText(node && node.getAttribute("content")) || "";
}

function productHeading() {
  const node = document.querySelector("main h1, [role='main'] h1") || document.querySelector("h1");
  if (!node) return "";
  const copy = node.cloneNode(true);
  copy.querySelectorAll("a, button, nav, [aria-hidden='true']").forEach((child) => child.remove());
  return cleanText(copy.textContent) || "";
}

// What the page says it sells: `fields` of `ld:*` values, the product's name,
// and whether the page declared a product at all (`typed`) — which is what
// lets an every-site script stay silent on every page that is not one.
function readStructuredProduct() {
  const nodes = _ldNodes();
  const products = nodes.filter((n) => _ldTypes(n).some((t) => LD_PRODUCT_TYPES.has(t)));
  const heading = productHeading();
  const pageUrl = (value) => {
    try {
      const url = new window.URL(value, window.location.href);
      // Tracking does not identify a variant; query parameters such as SKU
      // and variant do. Dropping every query merges distinct configurations.
      for (const key of [...url.searchParams.keys()]) {
        if (/^(utm_.+|gclid|fbclid|msclkid)$/i.test(key)) url.searchParams.delete(key);
      }
      url.searchParams.sort();
      return `${url.origin}${url.pathname.replace(/\/$/, "")}${url.search}`;
    } catch (_) { return ""; }
  };
  const current = pageUrl(window.location.href);
  const canonical = pageUrl(document.querySelector('link[rel="canonical"]')?.getAttribute("href"));
  const idKey = (value) => {
    try { return new window.URL(value, window.location.href).href; }
    catch (_) { return String(value || ""); }
  };
  const ids = new Map();
  for (const node of nodes.filter((one) => one["@id"])) {
    const key = idKey(node["@id"]);
    const previous = ids.get(key);
    // An @id-only reference must never replace the complete graph node.
    if (!previous || Object.keys(node).length > Object.keys(previous).length) ids.set(key, node);
  }
  const resolve = (node) => node && (ids.get(idKey(node["@id"])) || node);
  const mainEntities = nodes.filter((node) => _ldTypes(node).some((type) =>
    ["webpage", "itempage"].includes(type)) &&
    (!node.url && !node["@id"] || [node.url, node["@id"]].some((url) =>
      url && (pageUrl(url) === current || (canonical && pageUrl(url) === canonical))))).flatMap((node) =>
      (Array.isArray(node.mainEntity) ? node.mainEntity : [node.mainEntity]).map(resolve));
  const offeredItems = new Set(products.flatMap((node) =>
    (Array.isArray(node.offers) ? node.offers : [node.offers])
      .map(resolve).map((offer) => resolve(offer?.itemOffered)).filter(Boolean)));
  // A product's component may itself be a Product graph node. It is evidence
  // about the primary product, not another candidate listing.
  const components = new Set(products.flatMap((node) =>
    (Array.isArray(node.hasPart) ? node.hasPart : [node.hasPart]).map(resolve).filter(Boolean)));
  const roots = products.filter((node) => !offeredItems.has(node) && !components.has(node));
  const tokenSet = (value) => new Set((cleanText(value) || "").toLowerCase().match(/[\p{L}\p{N}]+(?:[-./][\p{L}\p{N}]+)*/gu) || []);
  const headingTokens = tokenSet(heading);
  const listed = nodes.some((node) => _ldTypes(node).includes("itemlist"));
  const nonProductPage = nodes.some((node) => _ldTypes(node).some((type) =>
    ["collectionpage", "searchresultspage", "article", "newsarticle", "blogposting"].includes(type)));
  const candidateScore = (node) => {
    const urls = [node.url, node.mainEntityOfPage?.["@id"], node.mainEntityOfPage];
    const urlMatch = urls.some((url) => typeof url === "string" &&
      (pageUrl(url) === current || (canonical && pageUrl(url) === canonical)));
    const main = mainEntities.includes(node);
    const nameTokens = tokenSet(_ldText(node.name));
    const nameMatch = nameTokens.size >= 2 && [...nameTokens].every((word) => headingTokens.has(word));
    return { node, score: (main ? 100 : 0) + (urlMatch ? 80 : 0) + (nameMatch ? 40 : 0),
      signals: [...(main ? ["main-entity"] : []), ...(urlMatch ? ["page-url"] : []), ...(nameMatch ? ["heading"] : [])] };
  };
  const ranked = roots.map(candidateScore).sort((a, b) => b.score - a.score);
  const first = ranked[0];
  const identityKey = (node) => [node.name, node.sku, node.mpn, node.gtin,
    node.gtin8, node.gtin12, node.gtin13, node.gtin14, node.productID].map(_ldText).join("|");
  const tied = first && ranked[1] && first.score === ranked[1].score &&
    identityKey(first.node) !== identityKey(ranked[1].node);
  const primary = first && !tied && (first.score > 0 || (roots.length === 1 && !listed && !nonProductPage))
    && (!nonProductPage || first.signals.includes("main-entity"))
    && (!listed || first.score >= 80) ? first.node : null;
  // Only merge a more specific item actually offered by this primary
  // product. Unrelated Product/Vehicle nodes never form one identity.
  const offers = primary && (Array.isArray(primary.offers) ? primary.offers : [primary.offers]);
  const offered = (offers || []).map(resolve).map((offer) => resolve(offer?.itemOffered));
  const vehicle = offered.find((node) => node && _ldTypes(node).some((type) => LD_VEHICLE_TYPES.has(type)))
    || (primary && _ldTypes(primary).some((type) => LD_VEHICLE_TYPES.has(type)) ? primary : null);
  const outer = primary === vehicle ? null : primary;
  const chosen = [vehicle, outer].filter(Boolean);

  const fields = {};
  for (const node of chosen) _ldFlatten(node, fields, resolve);
  if (chosen.length) {
    fields["ld:@type"] = _ldTypes(chosen[0]).find((type) => LD_PRODUCT_TYPES.has(type)) || "";
    const crumbs = nodes.find((n) => _ldTypes(n).includes("breadcrumblist"));
    const names = ((crumbs && crumbs.itemListElement) || [])
      .map((item) => _ldText(item && (item.name !== undefined ? item.name : item.item)))
      .filter(Boolean);
    if (names.length) fields["ld:breadcrumb"] = names.join(" > ").slice(0, 300);
  }

  const ogTitle = _metaContent("og:title");
  // A vehicle's own name before the listing's: AutoScout24's outer `Product`
  // is named "Mercedes-Benz for € 18,000". The heading before the share title,
  // which carries the shop's suffix ("… | MediaMarkt").
  const name = [
    vehicle && _ldText(vehicle.name),
    outer && _ldText(outer.name),
    heading.length <= 160 ? heading : "",
    ogTitle.split(" | ")[0],
    (cleanText(document.title) || "").split(" | ")[0],
  ].find((one) => one && one.length >= 3) || "";

  const ogProduct = /^(?:og:)?product(?::item)?$/i.test(_metaContent("og:type"));
  const typed = chosen.length > 0 || (!products.length && !nonProductPage && !listed && ogProduct);
  if (typed) {
    for (const meta of document.querySelectorAll('meta[property^="product:"], meta[name^="product:"]')) {
      const key = meta.getAttribute("property") || meta.getAttribute("name");
      const value = cleanText(meta.getAttribute("content"));
      if (key && value) fields[`meta:${key}`] = value.slice(0, 500);
    }
  }
  const description = chosen.map((node) => _ldText(node.description)).find(Boolean)
    || (typed ? _metaContent("og:description") || _metaContent("description") : "");
  return { fields, name: name.slice(0, 240), typed, description,
    recognition: { status: chosen.length ? "product" : products.length && !nonProductPage ? "ambiguous" : typed ? "product" : "untyped",
      source: chosen.length ? "structured-data" : ogProduct ? "open-graph" : "heading",
      signals: chosen.length ? first.signals : [], candidates: products.length } };
}

// ── the scrape ──────────────────────────────────────────────────────────

const DESCRIPTION_SELECTORS = [
  "#classifiedDescription .classifiedDescriptionContent",
  "#classifiedDescription",
  ".classifiedDescription",
  "[itemprop='description']",
  "#product-description", ".product-description", "[data-product-description]",
];

function extractProductSpecs() {
  const fields = {};
  const root = document.querySelector("main, [role='main']") || document.body;
  // Scope generic reading to labelled specifications, so cart summaries and
  // comparison/recommendation tables do not become this product's facts.
  for (const section of root.querySelectorAll(
    "#specifications, #technical-details, .specifications, .product-specifications, " +
    ".technical-details, [data-product-specs], [itemprop='additionalProperty']"
  )) {
    if (section.closest("aside, nav, footer, [hidden], [aria-hidden='true']")) continue;
    const put = (label, value) => {
      label = cleanText(label); value = cleanText(value);
      if (label && value && label.length <= 120 && value.length <= 500 && Object.keys(fields).length < 120) {
        if (!fields[label]) fields[label] = value;
      }
    };
    for (const row of section.querySelectorAll("tr")) {
      const cells = row.querySelectorAll("th, td");
      if (cells.length === 2) put(cells[0].textContent, cells[1].textContent);
    }
    for (const dt of section.querySelectorAll("dt")) {
      if (dt.nextElementSibling?.tagName === "DD") put(dt.textContent, dt.nextElementSibling.textContent);
    }
    if (section.matches("[itemprop='additionalProperty']")) {
      const valueOf = (prop) => {
        const el = section.querySelector(`[itemprop='${prop}']`);
        return el && (el.getAttribute("content") || el.textContent);
      };
      const unit = cleanText(valueOf("unitText") || valueOf("unitCode"));
      put(valueOf("name") || valueOf("propertyID"), `${valueOf("value") || ""}${unit ? ` ${unit}` : ""}`);
    }
  }
  return fields;
}

// `fields` is what goes on the wire: the page's own labels, its own values,
// no interpretation. `listing` is what stays here — the panel renders the
// damage and equipment panels locally, and the engine has no rule for them,
// so there is no reason to send them anywhere.
function buildScrape(knownLabels, panel) {
  const infoList = extractInfoList(knownLabels);
  const technical = extractTechnicalDetails();

  // The info list wins a collision. Both tables label a row "Engine Capacity"
  // on the English page and they disagree; deciding which is believable is a
  // range question, and ranges are the adapter's.
  // The page's structured data rides beside its labels, never over them: a
  // label the pack declared is the better evidence where both speak (B149).
  const structured = readStructuredProduct();
  const fields = { ...structured.fields, ...extractProductSpecs(), ...technical, ...infoList };

  let description = null;
  for (const selector of DESCRIPTION_SELECTORS) {
    const node = document.querySelector(selector);
    if (node?.closest("aside, nav, footer, [hidden], [aria-hidden='true']")) continue;
    description = cleanText(node?.textContent);
    if (description) break;
  }
  description = description || structured.description || null;

  return {
    url: window.location.href,
    title: textBySelector("h1.classifiedTitle") || textBySelector("h1"),
    description,
    fields,
    // What the page says it sells, for the panel to name a product no pack
    // recognises, and `typed` for the worker to leave a non-product page alone.
    product: { name: structured.name, typed: structured.typed,
               recognition: structured.recognition },
    listing: {
      damage_info: extractDamageInfo(panel),
      equipment: extractEquipment(panel),
      // The titles, tones, hints and alert rules the panel prints for the two
      // blocks above. They ride with the data they describe, and `listing` is
      // the half of the scrape that never goes on the wire — so the pack's
      // presentation rules reach the renderer without reaching the engine,
      // which has no rule for any of this and should not acquire one.
      panel: presentationOf(panel),
    },
  };
}

// What the renderer needs and nothing else. Selectors are markup knowledge
// that has already been spent by the time the scrape returns, and passing them
// on would invite a second reader of the DOM in the panel.
function presentationOf(panel) {
  const spec = panel || {};
  return {
    states: (spec.states || []).map((state) => ({
      key: state.key,
      title: state.title || null,
      tone: state.tone || "neutral",
      hint: state.hint || null,
    })),
    measures: (spec.measures || []).map((measure) => ({
      key: measure.key,
      currency_key: measure.currency_key || null,
      default_currency: measure.default_currency || null,
      title: measure.title || null,
      tone: measure.tone || "neutral",
      hint: measure.hint || null,
    })),
    sides: spec.sides || [],
    alerts: spec.alerts || [],
    // Only the bucket name, not the equipment selectors: the renderer needs a
    // label for a legacy cached entry that arrived as a bare list, and has no
    // business reading the page again.
    equipment: { fallback_category: (spec.equipment || {}).fallback_category || null },
  };
}

// ── messages ────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "GET_SCRAPE") {
    sendResponse({ ok: true, payload: buildScrape(request.labels, request.panel) });
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
  // extension-13 (B145 audit): this file only runs at document_idle, so the
  // page is already settled by the time we get here — the 1.5s wait on top
  // of that was pure added latency, pushing the automatic answer past the
  // "under 2s" promise the panel makes. A short tick (not zero) still lets
  // the DOM finish painting before content.js starts reading it.
  setTimeout(() => {
    chrome.runtime.sendMessage({
      type: "PAGE_LOADED",
      payload: { url: window.location.href, host: window.location.hostname },
    });
  }, 150);
})();
