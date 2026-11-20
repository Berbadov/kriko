/* The offline catalog: what Kriko knows, when the desktop app is not running.
 *
 * The desktop engine's answer is the good one, and the extension keeps using
 * it whenever it is up. This file is the fallback: the same `.kpack` releases
 * the app installs, downloaded from the release index, verified by the same
 * sha256, read with `offline/sqlite.js`, and matched here.
 *
 * The match is deliberately smaller than the engine's. It finds the catalog
 * subject whose identity values appear on the page, and answers with that
 * subject's claims. It does not re-rank, it does not call an agent, and it
 * never makes a claim up: a page it cannot place gets `UNKNOWN_PRODUCT`, and a
 * subject with no claims says so.
 *
 * Storage is IndexedDB, one record per pack, because a catalog is megabytes of
 * JSON and `storage.local` is a few. The index of installed packs is a small
 * record in `storage.local`, so the options page can list what is there
 * without opening the database.
 *
 * No API key, no account, and no network except a press on "Update catalogs".
 */
(function (root) {
  "use strict";

  const RELEASE_INDEX = "https://github.com/Berbadov/kriko/releases/latest/download/packs.json";
  const CATALOG_KEY = "krikoOfflineCatalogs";
  const ENABLED_KEY = "krikoOfflineEnabled";
  const DB_NAME = "kriko-offline";
  const DB_VERSION = 1;
  const STORE = "packs";
  const MAX_PACK_BYTES = 32 * 1024 * 1024;
  //: A long claim body is worth keeping; a whole book is not.
  const CLAIM_BODY_CHARS = 1200;
  const CLAIMS_PER_ANSWER = 20;

  function fold(text) {
    return String(text == null ? "" : text)
      .replace(/\u0131/g, "i")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  async function sha256Hex(bytes) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  /* Turn the rows of one `.kpack` into the small catalog the lookup needs. */
  function buildCatalog(tables, meta) {
    const rows = (name) => (Array.isArray(tables[name]) ? tables[name] : []);
    const packs = rows("packs");
    const pack = packs[0] || {};
    const claimText = new Map();
    for (const row of rows("claim_text")) {
      // columns: claim_id, pack_id, lang, title, body, advice
      const key = `${row[0]}\u0000${row[1]}`;
      const lang = String(row[2] || "");
      if (!claimText.has(key) || lang === "en") {
        claimText.set(key, { title: String(row[3] || ""), body: String(row[4] || ""), advice: String(row[5] || "") });
      }
    }
    const sources = new Map(rows("sources").map((row) => [String(row[0]), row]));
    const evidence = new Map();
    for (const row of rows("evidence")) {
      // columns: evidence_id, pack_id, claim_id, source_id, quote, locator, stance, independent
      const key = `${row[2]}\u0000${row[1]}`;
      if (!evidence.has(key)) evidence.set(key, []);
      evidence.get(key).push(row);
    }
    return {
      pack_id: String(pack[0] || meta.pack_id || ""),
      name: String(pack[1] || meta.name || ""),
      version: String(pack[2] || meta.version || ""),
      content_digest: String(pack[8] || meta.content_digest || ""),
      sha256: meta.sha256 || "",
      installed_at: new Date().toISOString(),
      subjects: rows("subjects").map((row) => ({
        subject_id: String(row[0]), pack_id: String(row[1]), kind: String(row[2]), label: String(row[3]),
      })),
      attributes: rows("attributes").map((row) => ({
        pack_id: String(row[1]), subject_id: String(row[2]), key: String(row[3]),
        value: String(row[4] || ""), is_identity: Number(row[9] || 0) === 1,
      })),
      relations: rows("relations").map((row) => ({
        subject_id: String(row[2]), predicate: String(row[3]), object_id: String(row[4]),
      })),
      claims: rows("claims").map((row) => ({
        claim_id: String(row[0]), pack_id: String(row[1]), subject_id: String(row[2]),
        kind: String(row[3]), domain: String(row[4]), severity: String(row[5]),
        component: String(row[8] || ""),
      })),
      texts: Object.fromEntries([...claimText.entries()].map(([key, value]) => [key, {
        title: value.title,
        body: String(value.body || "").slice(0, CLAIM_BODY_CHARS),
        advice: String(value.advice || "").slice(0, CLAIM_BODY_CHARS),
      }])),
      sources: Object.fromEntries([...sources.entries()].map(([id, row]) => [id, {
        url: String(row[2] || ""), domain: String(row[3] || ""), title: String(row[5] || ""),
        tier: String(row[10] || "unknown"),
      }])),
      evidence: Object.fromEntries([...evidence.entries()].map(([key, list]) => [key, list.slice(0, 3).map((row) => ({
        source_id: String(row[3]), quote: String(row[4] || "").slice(0, 400), stance: String(row[6] || "supports"),
      }))])),
    };
  }

  /* How many of a subject's identity values the page itself shows. */
  function scoreSubject(subject, bySubject, pageText, claimCount) {
    const identity = bySubject.get(subject.subject_id) || [];
    if (!identity.length) return { score: 0, matched: [] };
    let matched = 0;
    const values = [];
    for (const attribute of identity) {
      const value = fold(attribute.value);
      if (value.length >= 3 && pageText.includes(value)) {
        matched += 1;
        values.push({ key: attribute.key, value: attribute.value });
      }
    }
    const label = fold(subject.label);
    const labelHit = label.length >= 4 && pageText.includes(label);
    // A subject that has claims is the one a reader asked about; a variant
    // with nothing to say is not a better answer for sharing a name.
    const score = Math.min(1, matched / Math.min(identity.length, 3)
      + (labelHit ? 0.2 : 0) + (claimCount ? 0.1 : 0));
    return { score, matched: values };
  }

  /* The catalog lookup: the best subject, its claims, and the reasons. */
  function match(catalogs, scrape) {
    const pageText = fold([
      scrape && scrape.url,
      scrape && scrape.title,
      scrape && scrape.description,
      scrape && scrape.product && scrape.product.name,
      ...Object.values((scrape && scrape.fields) || {}),
    ].filter(Boolean).join(" \u00b7 "));

    let best = null;
    for (const catalog of catalogs.length ? catalogs : []) {
      const related = relatedClaims(catalog);
      const claimCounts = new Map();
      for (const [subjectId, list] of related) claimCounts.set(subjectId, list.length);
      const bySubject = new Map();
      for (const attribute of catalog.attributes || []) {
        if (!attribute.is_identity) continue;
        if (!bySubject.has(attribute.subject_id)) bySubject.set(attribute.subject_id, []);
        bySubject.get(attribute.subject_id).push(attribute);
      }
      for (const subject of catalog.subjects || []) {
        const got = scoreSubject(subject, bySubject, pageText, claimCounts.get(subject.subject_id));
        if (got.score > 0 && (!best || got.score > best.score)) {
          best = { ...got, subject, catalog };
        }
      }
    }

    const answered = { packs: [] };
    if (!best || best.score < 0.34) {
      return {
        readable: false, reason: "unknown_product", coverage: "UNKNOWN_PRODUCT",
        claims: [], identity: {}, context: {}, subjects: [], packs: [],
      };
    }
    const catalog = best.catalog;
    const relatedIds = new Set([best.subject.subject_id]);
    for (const relation of catalog.relations || []) {
      if (relation.predicate !== "part_of") continue;
      if (relation.subject_id === best.subject.subject_id) relatedIds.add(relation.object_id);
      else if (relation.object_id === best.subject.subject_id) relatedIds.add(relation.subject_id);
    }
    const claims = (catalog.claims || [])
      .filter((claim) => relatedIds.has(claim.subject_id))
      .sort((a, b) => severityRank(b.severity) - severityRank(a.severity))
      .slice(0, CLAIMS_PER_ANSWER)
      .map((claim) => {
        const textKey = `${claim.claim_id}\u0000${claim.pack_id}`;
        const text = (catalog.texts || {})[textKey] || { title: "", body: "", advice: "" };
        const proofs = (catalog.evidence || {})[textKey] || [];
        return {
          claim_id: claim.claim_id,
          pack_id: claim.pack_id,
          subject_id: claim.subject_id,
          subject: best.subject.label,
          title: text.title,
          body: text.body,
          advice: text.advice,
          severity: claim.severity,
          domain: claim.domain,
          sources: proofs.map((proof) => {
            const source = (catalog.sources || {})[proof.source_id] || { url: "", domain: "", tier: "unknown" };
            return { url: source.url, domain: source.domain, quote: proof.quote, tier: source.tier };
          }).filter((source) => source.url || source.quote),
          relevance: null,
          disputed: proofs.some((proof) => proof.stance === "refutes"),
        };
      });

    answered.packs = [{ pack_id: catalog.pack_id, version: catalog.version }];
    return {
      readable: true,
      offline: true,
      coverage: claims.length ? "RISKS_FOUND" : "KNOWN_NO_CLAIMS",
      verdict: best.score >= 0.8 ? "exact" : "probably",
      score: Number(best.score.toFixed(2)),
      method: "offline_catalog",
      identity: Object.fromEntries(best.matched.map((one) => [one.key, one.value])),
      context: {},
      context_units: {},
      subjects: [{ subject_id: best.subject.subject_id, pack_id: best.subject.pack_id, label: best.subject.label, claims: claims.length }],
      claims,
      packs: answered.packs,
      notes: ["Answered from the catalog stored in this browser; the desktop engine was not running."],
    };
  }

  /* Claims on a subject and on the parts it is made of. A variant carries the
   * engine's findings; the body and electrics findings hang off part subjects
   * the variant is `part_of`, exactly as the pack built them. */
  function relatedClaims(catalog) {
    const direct = new Map();
    for (const claim of catalog.claims || []) {
      if (!direct.has(claim.subject_id)) direct.set(claim.subject_id, []);
      direct.get(claim.subject_id).push(claim);
    }
    for (const subject of catalog.subjects || []) {
      const list = [...(direct.get(subject.subject_id) || [])];
      for (const relation of catalog.relations || []) {
        if (relation.predicate !== "part_of") continue;
        if (relation.subject_id === subject.subject_id) {
          list.push(...(direct.get(relation.object_id) || []));
        } else if (relation.object_id === subject.subject_id) {
          list.push(...(direct.get(relation.subject_id) || []));
        }
      }
      direct.set(subject.subject_id, list);
    }
    return direct;
  }

  function severityRank(severity) {
    return ({ critical: 5, high: 4, medium: 3, low: 2, unrated: 1 })[String(severity || "").toLowerCase()] || 0;
  }

  /* ---- storage: IndexedDB for packs, local storage for the index ---- */

  function openDb() {
    return new Promise((resolve, reject) => {
      if (typeof indexedDB === "undefined") return reject(new Error("this browser has no IndexedDB"));
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "pack_id" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("could not open the catalog store"));
    });
  }

  async function transact(mode, run) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const store = tx.objectStore(STORE);
      let result;
      try { result = run(store); } catch (error) { reject(error); return; }
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error || new Error("catalog store failed"));
    });
  }

  async function putCatalog(catalog) {
    await transact("readwrite", (store) => store.put(catalog));
  }

  async function getCatalogs() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const request = tx.objectStore(STORE).getAll();
      request.onsuccess = () => resolve(request.result || []);
      request.onerror = () => reject(request.error || new Error("could not read the catalog store"));
    });
  }

  async function removeCatalog(packId) {
    await transact("readwrite", (store) => store.delete(packId));
  }

  async function index(api) {
    try {
      const got = await api.storage.local.get(CATALOG_KEY);
      return Array.isArray(got && got[CATALOG_KEY]) ? got[CATALOG_KEY] : [];
    } catch (_) {
      return [];
    }
  }

  async function writeIndex(api, rows) {
    await api.storage.local.set({ [CATALOG_KEY]: rows });
  }

  /* Download the release index, then every catalog named by it, verifying each
   * file before it is read. A pack already at the same sha256 is kept. */
  async function refresh(api, { fetchImpl = fetch, onProgress = () => {} } = {}) {
    const indexResponse = await fetchImpl(RELEASE_INDEX, { cache: "no-store" });
    if (!indexResponse.ok) throw new Error(`catalog index: HTTP ${indexResponse.status}`);
    const listing = await indexResponse.json();
    const wanted = Array.isArray(listing.packs) ? listing.packs : [];
    const installed = new Map((await index(api)).map((row) => [row.pack_id, row]));
    const results = [];
    for (const row of wanted) {
      const known = installed.get(row.pack_id);
      if (known && known.sha256 === row.sha256 && known.version === row.version) {
        results.push({ pack_id: row.pack_id, version: row.version, state: "current" });
        continue;
      }
      onProgress(`Reading ${row.name || row.pack_id}…`);
      const response = await fetchImpl(row.url, { cache: "no-store" });
      if (!response.ok) throw new Error(`${row.pack_id}: HTTP ${response.status}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length > MAX_PACK_BYTES) throw new Error(`${row.pack_id}: larger than ${MAX_PACK_BYTES} bytes`);
      const digest = await sha256Hex(bytes);
      if (row.sha256 && digest !== String(row.sha256).toLowerCase()) {
        throw new Error(`${row.pack_id}: sha256 does not match the index; discarded`);
      }
      const catalog = buildCatalog(root.KrikoSqlite.read(bytes, [
        "packs", "subjects", "attributes", "relations", "claims", "claim_text", "sources", "evidence",
      ]), { ...row, sha256: digest });
      await putCatalog(catalog);
      installed.set(row.pack_id, {
        pack_id: catalog.pack_id || row.pack_id,
        name: row.name || catalog.name,
        version: catalog.version || row.version,
        sha256: digest,
        size: bytes.length,
        installed_at: catalog.installed_at,
      });
      results.push({ pack_id: row.pack_id, version: catalog.version || row.version, state: "installed" });
    }
    await writeIndex(api, [...installed.values()]);
    return results;
  }

  async function lookup(api, scrape) {
    const enabled = await api.storage.local.get(ENABLED_KEY);
    if (enabled && enabled[ENABLED_KEY] === false) return null;
    let catalogs = [];
    try {
      catalogs = await getCatalogs();
    } catch (_) {
      // No readable store is the same as no catalog here: the engine's own
      // error stays on screen rather than being replaced by a guess.
      return null;
    }
    if (!catalogs.length) return null;
    return match(catalogs, scrape);
  }

  root.KrikoOffline = {
    RELEASE_INDEX, CATALOG_KEY, ENABLED_KEY,
    fold, sha256Hex, buildCatalog, match, index, refresh, lookup,
    getCatalogs, removeCatalog, putCatalog, writeIndex,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
