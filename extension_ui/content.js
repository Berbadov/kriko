function textBySelector(selector) {
  const node = document.querySelector(selector);
  return node ? node.textContent.trim() : null;
}

function numberFromText(value) {
  if (!value) {
    return null;
  }
  const normalized = value.replace(/[^\d]/g, "");
  return normalized ? Number(normalized) : null;
}

function cleanText(text) {
  if (!text) return null;
  return text.replace(/\s+/g, " ").trim();
}

// The field labels Sahibinden puts on a vasıta detail page, in BOTH locales it
// serves (Turkish and English). A closed vocabulary of FIELD names — not car
// data, so it does not grow as models are onboarded. Used by the
// layout-agnostic fallback below.
const KNOWN_INFO_LABELS = [
  // Turkish
  "İlan No", "İlan Tarihi", "Marka", "Seri", "Model", "Yıl", "Yakıt",
  "Yakıt Tipi", "Vites", "Kilometre", "Kasa Tipi", "Motor Gücü", "Motor Hacmi",
  "Çekiş", "Renk", "Garanti", "Durumu", "Durum", "Ağır Hasar Kayıtlı",
  "Takasa Uygun", "Kimden",
  // English
  "Listing No", "Listing Date", "Make", "Series", "Year", "Fuel Type", "Gear",
  "Vehicle Status", "KM", "Body Type", "Engine Power", "Engine Capacity",
  "Wheel Drive", "Color", "Warranty", "Salvage Record", "Plate", "From",
  "Exchange",
];

// Last resort when no known container selector matches: find the LABEL text
// itself anywhere in the document and read the value next to it. Sahibinden has
// redesigned this markup repeatedly, and every redesign silently zeroed every
// field — the extension kept "working" while the backend answered "Missing
// required fields". Anchoring on the label instead of the container survives a
// class rename.
function extractInfoListByLabelScan() {
  const details = {};
  const wanted = new Map(
    KNOWN_INFO_LABELS.map(l => [l.toLocaleLowerCase("tr"), l])
  );

  for (const node of document.querySelectorAll(
    "span, div, dt, th, td, strong, b, p, label"
  )) {
    const text = cleanText(node.textContent);
    if (!text || text.length > 24) continue;
    const canonical = wanted.get(text.toLocaleLowerCase("tr"));
    if (!canonical || details[canonical]) continue;

    // The value sits next to the label — as a sibling, or as the parent's other
    // half when both are wrapped (…<span>Yıl</span><span>2014</span>…).
    const sibling = node.nextElementSibling;
    const value = cleanText(sibling && sibling.textContent);
    if (value && value !== text) {
      details[canonical] = value;
    }
  }
  return details;
}

function extractInfoList() {
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
    return extractInfoListByLabelScan();
  }

  return details;
}

// Sahibinden's info list labels the fuel column "Yakıt" (TR) or "Fuel Type"
// (EN); the technical-details panel uses "Yakıt Tipi" / "Fuel". All are the fuel
// TYPE. "Yakıt Tüketimi" / "Fuel Consumption" and "Yakıt Deposu" / "Fuel
// Capacity" are not — without the exclusion a bare match hands the matcher
// "4,9 l" as a fuel.
const FUEL_LABEL_RE = /yak[ıi]t|fuel/;
const NOT_FUEL_TYPE_RE = /t[üu]ketim|depo|consumption|capacity/;

function isFuelTypeLabel(key) {
  return FUEL_LABEL_RE.test(key) && !NOT_FUEL_TYPE_RE.test(key);
}

function mapTurkishKeys(details) {
  // Sahibinden serves the same page in Turkish OR English depending on the
  // user's locale, with entirely different labels ("Marka"/"Make",
  // "Yıl"/"Year", "Vites"/"Gear", "Kilometre"/"KM"). The scraper knew only the
  // Turkish set, so an English listing read as an empty info list and the
  // backend rejected it with "Missing required fields". Both locales are
  // matched here; the label set is a fixed vocabulary, not car data.
  const mapping = {
    // Exact or partial label matches — Turkish first, then the English locale.
    yıl: "year",
    yil: "year",
    "üretim yılı": "year",
    "uretim yili": "year",
    year: "year",
    kilometre: "mileage_km",
    km: "mileage_km",
    vites: "transmission",
    gear: "transmission",
    "motor hacmi": "engine_volume_cc",
    "engine capacity": "engine_volume_cc",
    "motor gücü": "power_hp",
    "motor gucu": "power_hp",
    "beygir gücü": "power_hp",
    "beygir gucu": "power_hp",
    "engine power": "power_hp",
    "kasa tipi": "body_type",
    "body type": "body_type",
    renk: "color",
    color: "color",
    durum: "condition",
    "vehicle status": "condition",
    garanti: "warranty",
    warranty: "warranty",
    "çekiş": "drivetrain",
    "cekis": "drivetrain",
    "wheel drive": "drivetrain",
    marka: "make",
    make: "make",
    // Sahibinden uses "Model"/"Model" for trim/variant (e.g. "1.5 dCi Joy");
    // the model name itself lives in "Seri" / "Series" (e.g. "Clio").
    // "series".includes("seri") is true, so one entry covers both locales.
    seri: "model",
    model: "trim",
  };

  const mapped = {};
  for (const [rawLabel, rawValue] of Object.entries(details)) {
    const key = rawLabel.toLowerCase().trim();
    if (isFuelTypeLabel(key)) {
      mapped.fuel_type = rawValue;
      continue;
    }
    for (const [turkish, english] of Object.entries(mapping)) {
      if (key.includes(turkish)) {
        mapped[english] = rawValue;
        break;
      }
    }
  }
  return mapped;
}

// The listing title leads with the model year ("2014 Volkswagen Golf 1.6 TDI").
// make/model already fall back to the title when the info list can't be read;
// year did not, so a markup change left it null and the backend rejected the
// listing outright. Bounded to plausible model years so a price or a mileage
// figure can never be mistaken for one.
function yearFromTitle(title) {
  const match = (title || "").match(/\b(19\d{2}|20\d{2})\b/);
  if (!match) return null;
  const year = Number(match[1]);
  const maxYear = new Date().getFullYear() + 1;
  return year >= 1980 && year <= maxYear ? year : null;
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

function mapTechnicalDetails(details) {
  const mapped = {};
  for (const [rawLabel, rawValue] of Object.entries(details)) {
    const key = rawLabel.toLowerCase().trim();
    const value = cleanText(rawValue);
    if (!value) continue;

    if (key.includes("şanzıman / çekiş") || key.includes("sanziman / cekis")
        || key.includes("transmission / drive type")) {
      // TR: "Otomatik / Önden Çekiş". EN: "DSG / 7 Gear / Front Wheel Drive" —
      // the drive type is the LAST segment, not the second.
      const segments = value.split("/").map(v => cleanText(v)).filter(Boolean);
      if (segments.length) {
        mapped.transmission = segments[0];
        if (segments.length > 1) mapped.drivetrain = segments[segments.length - 1];
      }
      continue;
    }
    if (isFuelTypeLabel(key)) {
      // EN "Fuel" reads "Gasoline / EURO 6"; TR "Yakıt Tipi" reads "Dizel".
      mapped.fuel_type = cleanText(value.split("/")[0]);
      continue;
    }
    if (key.includes("motor hacmi") || key.includes("engine capacity")) {
      // Sahibinden's own bug: the English "Overview" table labels the POWER row
      // "Engine Capacity" (110 hp), while the real capacity (1197 cc) sits under
      // the same label in "Engine and Performance". Accept a capacity only when
      // it is actually expressed in cc, so "110 hp" can never become 110 cc.
      if (/\d\s*cc\b/i.test(value)) {
        mapped.engine_volume_cc = value;
      }
      continue;
    }
    if (key.includes("motor gücü") || key.includes("motor gucu")
        || key.includes("engine power")) {
      // Clean single value (e.g. "140 hp") — always wins over the composite
      // "Maksimum Güç" / "Maximum Power" field below, which also carries kW/rpm.
      mapped.power_hp = value;
      continue;
    }
    if (key.includes("maksimum güç") || key.includes("maksimum guc")
        || key.includes("maximum power")) {
      if (!mapped.power_hp) {
        // Composite (e.g. "110 hp (81 kw) / 4,600 rpm"). Extracting the raw
        // string and letting numberFromText() strip all non-digits later
        // concatenates hp+kW+rpm into garbage like "110814600" — pull out just
        // the hp figure instead.
        const hpMatch = value.match(/(\d+)\s*hp/i);
        mapped.power_hp = hpMatch ? hpMatch[1] : value;
      }
      continue;
    }
    if (key.includes("kasa tipi") || key.includes("body type")) {
      mapped.body_type = cleanText(value.split("/")[0]);
      continue;
    }
    // TR "Motor Tipi" / EN "Engine Type" reads "Gasoline / 4 cylinders" — the
    // fuel, but only as a fallback if the explicit fuel row was absent.
    if ((key.includes("motor tipi") || key.includes("engine type"))
        && !mapped.fuel_type) {
      mapped.fuel_type = cleanText(value.split("/")[0]);
    }
  }
  return mapped;
}

function parseMakeModelFromTitle(title) {
  if (!title) return [null, null];
  const cleaned = title.replace(/^\d{4}\s*/i, "").trim();
  const knownMakes = [
    "Renault", "Volkswagen", "VW", "Toyota", "Mini", "BMW", "Mercedes",
    "Mercedes-Benz", "Audi", "Opel", "Ford", "Fiat", "Hyundai", "Kia",
    "Peugeot", "Citroën", "Nissan", "Honda", "Mazda", "Skoda", "Seat",
    "Volvo", "Dacia", "Suzuki", "Mitsubishi", "Subaru", "Jeep", "Land Rover",
    "Porsche", "Ferrari",
  ];
  const cleanLower = cleaned.toLowerCase();
  for (const make of knownMakes) {
    const makeLower = make.toLowerCase();
    if (cleanLower.startsWith(makeLower) || cleanLower.includes(" " + makeLower + " ")) {
      const afterMake = cleaned.slice(cleaned.toLowerCase().indexOf(makeLower) + makeLower.length).trim();
      // Model is next word(s) until engine/spec info
      const modelMatch = afterMake.match(/^([a-zA-Z0-9\s]+?)(?:\s+\d|$)/);
      const model = modelMatch ? modelMatch[1].trim() : afterMake.split(" ")[0];
      return [make, model || null];
    }
  }
  return [null, null];
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

function computeAnnualKm(year, mileageKm) {
  if (!year || !mileageKm) return null;
  const currentYear = new Date().getFullYear();
  const age = Math.max(1, currentYear - Number(year));
  return Math.round(Number(mileageKm) / age);
}

function extractSahibindenMetadata() {
  const title = textBySelector("h1") || textBySelector("h1.classifiedTitle");
  const priceText = textBySelector(".classified-price-wrapper, .classifiedInfo h3, .classified-price");
  const description =
    textBySelector("#classifiedDescription .classifiedDescriptionContent") ||
    textBySelector("#classifiedDescription") ||
    textBySelector(".classifiedDescription") ||
    textBySelector("[itemprop='description']");

  const infoList = extractInfoList();
  const mapped = mapTurkishKeys(infoList);
  const technicalDetails = extractTechnicalDetails();
  const technicalMapped = mapTechnicalDetails(technicalDetails);
  const damage = extractDamageInfo();
  const equipment = extractEquipment();

  // Extract make/model: prefer info list, fall back to title parsing
  let make = mapped.make || null;
  let model = mapped.model || null;
  if (!make || !model) {
    const [titleMake, titleModel] = parseMakeModelFromTitle(title);
    if (!make) make = titleMake;
    if (!model) model = titleModel;
  }

  const yearNum = numberFromText(mapped.year) || yearFromTitle(title);
  const mileageNum = numberFromText(mapped.mileage_km);
  const annualKm = computeAnnualKm(yearNum, mileageNum);

  // Build retrieval_text in the format the vector pipeline expects
  const parts = [];
  if (title) parts.push(title);
  if (make) parts.push(`Make: ${make}`);
  if (model) parts.push(`Model: ${model}`);
  if (mapped.year) parts.push(`Year: ${mapped.year}`);
  if (mapped.mileage_km) parts.push(`KM: ${mapped.mileage_km}`);
  if (annualKm) parts.push(`Annual KM: ~${annualKm.toLocaleString()} km/year`);
  const fuelType = technicalMapped.fuel_type || mapped.fuel_type || null;
  const transmission = technicalMapped.transmission || mapped.transmission || null;
  const engineVolume = technicalMapped.engine_volume_cc || mapped.engine_volume_cc || null;
  const powerHp = technicalMapped.power_hp || mapped.power_hp || null;
  const bodyType = technicalMapped.body_type || mapped.body_type || null;

  if (powerHp) parts.push(`Engine Power: ${powerHp}`);
  if (fuelType) parts.push(`Fuel: ${fuelType}`);
  if (transmission) parts.push(`Transmission: ${transmission}`);
  if (engineVolume) parts.push(`Engine: ${engineVolume}`);
  if (damage.changed.length) parts.push(`Replaced parts: ${damage.changed.join(", ")}`);
  if (damage.painted.length) parts.push(`Painted parts: ${damage.painted.join(", ")}`);
  if (damage.local_painted.length) parts.push(`Local paint: ${damage.local_painted.join(", ")}`);
  if (damage.tramer_amount) {
    parts.push(`Damage claim: ${damage.tramer_amount.toLocaleString()} ${damage.tramer_currency || "TRY"}`);
  }
  const equipmentLines = Object.entries(equipment)
    .filter(([, items]) => items && items.length)
    .map(([cat, items]) => `${cat}: ${items.join(", ")}`);
  if (equipmentLines.length) parts.push(`Equipment — ${equipmentLines.join(" | ")}`);
  if (description) parts.push(description);

  const retrievalText = parts.join("\n");

  return {
    source: "sahibinden.com",
    url: window.location.href,
    title,
    make,
    model,
    price_amount: numberFromText(priceText),
    currency: priceText && priceText.includes("TL") ? "TRY" : null,
    description,
    // Enriched fields
    year: yearNum,
    mileage_km: mileageNum,
    annual_km: annualKm,
    fuel_type: fuelType,
    transmission,
    trim: mapped.trim || null,
    engine_volume_cc: numberFromText(engineVolume),
    power_hp: numberFromText(powerHp),
    body_type: bodyType,
    // Was computed but never sent — Variant carries a drivetrain column and
    // sync.py gates claims on it (_drivetrain_compatible).
    drivetrain: technicalMapped.drivetrain || mapped.drivetrain || null,
    condition: mapped.condition || null,
    // Structured replaced/painted/tramer info
    damage_info: damage,
    // Equipment / Donanım: { category: [feature, ...] }
    equipment,
    technical_details: technicalDetails,
    // Structured text for the RAG pipeline
    retrieval_text: retrievalText,
    // Raw technical details for debugging
    _raw_details: infoList,
    _raw_technical_details: technicalDetails,
  };
}

function extractGenericMetadata() {
  const title = document.title || textBySelector("h1");
  const description =
    document.querySelector("meta[name='description']")?.getAttribute("content") || null;

  return {
    source: window.location.hostname,
    url: window.location.href,
    title,
    description,
    retrieval_text: [title, description].filter(Boolean).join("\n"),
  };
}

function buildMetadata() {
  const host = window.location.hostname;
  if (host.includes("sahibinden.com")) {
    return extractSahibindenMetadata();
  }
  return extractGenericMetadata();
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "GET_AD_METADATA") {
    sendResponse({ ok: true, payload: buildMetadata() });
    return;
  }

  if (request.type === "TRIGGER_ANALYSIS") {
    const metadata = buildMetadata();
    chrome.runtime.sendMessage({ type: "ANALYZE_AD", payload: metadata }, (response) => {
      sendResponse(response);
    });
    return true; // async
  }
});

// ── Background-driven auto-trigger ──
// When the page is fully loaded, notify the background script.
(function autoTrigger() {
  const host = window.location.hostname;
  if (!host.includes("sahibinden.com")) return;

  // Only trigger on listing detail pages (URLs containing /detail or /ilan/)
  if (!window.location.pathname.includes("/detail") && !window.location.pathname.includes("/ilan/")) {
    return;
  }

  // Wait a short moment for dynamic content to settle
  setTimeout(() => {
    chrome.runtime.sendMessage({
      type: "PAGE_LOADED",
      payload: { url: window.location.href, host },
    });
  }, 1500);
})();
