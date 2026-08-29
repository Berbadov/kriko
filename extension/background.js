// The service worker: the only thing in the extension that talks to Kriko.
//
// Phase 6c rewired this end of the contract. It used to POST
// `{listing_url, ad_metadata}` — a metadata dict the content script had
// already interpreted — to `/analyze` on ports 8000/8765. Both the endpoint
// and the payload are gone. It now POSTs the page's own label/value pairs to
// `/api/analyze` on the local app's port, and the installed pack decides what
// they mean.
//
// Two consequences worth knowing before editing:
//
//   * The worker asks the app which sites are worth scraping (`/api/adapters`)
//     instead of testing the hostname itself. Installing a pack for a new
//     listing site therefore needs no extension change at all.
//   * Nothing here interprets a field. If you find yourself adding a branch on
//     what a label means, it belongs in the pack's adapter JSON.

const DEFAULT_API_BASE = "http://127.0.0.1:8787";
const STORAGE_KEY_PREFIX = "kriko_result_";
const LOCAL_CACHE_KEY_PREFIX = "kriko_cached_result_";
const RESULT_CACHE_TTL_MS = 6 * 60 * 60 * 1000;
const ADAPTERS_TTL_MS = 5 * 60 * 1000;

// Tiers whose word stands on its own. Anything else is corroboration: worth
// showing, worth counting, not worth presenting as settled.
const CONFIRMING_TIERS = new Set(["authoritative", "manufacturer"]);

const latestRunIdByStorageKey = new Map();
const inFlightByStorageKey = new Map();
let nextRunId = 1;
let adaptersCache = null;

// Expose chrome.storage.session to content scripts. The Hover Lite panel is a
// content script and relies on chrome.storage.onChanged (session area) to learn
// when a background analysis lands — runtime.sendMessage broadcasts never reach
// content scripts. Session storage is restricted to trusted contexts by
// default, so without this the hover panel silently misses results that arrive
// after it opens and stays stuck on the empty state (issue #28). Called at the
// service-worker top level so it re-applies on every worker startup.
function _ensureSessionAccessLevel() {
  try {
    chrome.storage.session
      .setAccessLevel({ accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS" })
      .catch(() => {});
  } catch (_) {
    // Older Chrome without setAccessLevel — ignore.
  }
}
_ensureSessionAccessLevel();

chrome.runtime.onInstalled.addListener(_ensureSessionAccessLevel);

// Hover Lite is the only in-page surface; the toolbar action toggles it.
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || !tab.id) return;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "TOGGLE_HOVER_LITE" });
  } catch (_) {
    // Content script not present (e.g. chrome:// or unsupported host) — ignore.
  }
});

// ── where the app is ────────────────────────────────────────────────────

function _normalizeBaseUrl(value) {
  if (!value || typeof value !== "string") return null;
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) return null;
  if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
    return `http://${trimmed}`;
  }
  return trimmed;
}

async function apiBase() {
  const stored = await chrome.storage.local.get(["krikoApiBaseUrl"]);
  return _normalizeBaseUrl(stored.krikoApiBaseUrl) || DEFAULT_API_BASE;
}

// ── which sites are worth scraping ──────────────────────────────────────

function globToRegExp(pattern) {
  const escaped = String(pattern).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp("^" + escaped.replace(/\\\*/g, ".*") + "$", "i");
}

function adapterFor(url, adapters) {
  for (const adapter of adapters || []) {
    if ((adapter.match || []).some((p) => globToRegExp(p).test(url))) {
      return adapter;
    }
  }
  return null;
}

async function fetchAdapters() {
  if (adaptersCache && Date.now() - adaptersCache.at < ADAPTERS_TTL_MS) {
    return adaptersCache.rows;
  }
  const response = await fetch(`${await apiBase()}/api/adapters`);
  if (!response.ok) {
    throw new Error(`Kriko is not reachable (${response.status}).`);
  }
  const rows = await response.json();
  adaptersCache = { at: Date.now(), rows };
  return rows;
}

// ── the answer, in the shape the panel renders ──────────────────────────

function _strengthOf(claim) {
  const sources = Array.isArray(claim.sources) ? claim.sources : [];
  return sources.some((s) => CONFIRMING_TIERS.has(s.tier))
    ? "confirmed"
    : "reported";
}

// The panel's vocabulary is older than the engine's and describes the card
// rather than the claim, so the two are translated here — in one place, rather
// than by teaching every renderer both. Nothing is invented: each field below
// is a rename or a count of something the server already said.
function toViewModel(payload) {
  const claims = Array.isArray(payload.claims) ? payload.claims : [];
  return {
    adapter: payload.adapter,
    identity: payload.identity || {},
    context: payload.context || {},
    coverage: payload.coverage,
    method: payload.method,
    flags: payload.flags || [],
    unmapped_labels: payload.unmapped_labels || [],
    risks: claims.map((claim) => {
      const strength = _strengthOf(claim);
      return {
        title: claim.title,
        rationale: claim.body,
        inspection_advice: claim.advice,
        severity: claim.severity,
        domain: claim.domain,
        subject: claim.subject,
        strength,
        // Only confirmed cards carry a number. On a "Reported" card a score
        // reads as trustworthy and quietly undoes the label.
        confidence: strength === "confirmed" ? claim.relevance : undefined,
        source_count: (claim.sources || []).length,
        why_shown: claim.why || [],
        disputed: Boolean(claim.disputed),
        pack_id: claim.pack_id,
        sources: claim.sources || [],
      };
    }),
  };
}

// ── caching ─────────────────────────────────────────────────────────────

function _now() {
  return typeof performance !== "undefined" && performance.now
    ? performance.now()
    : Date.now();
}

function _elapsed(startedAt) {
  return Math.round((_now() - startedAt) * 10) / 10;
}

function _stableHash(value) {
  const text = JSON.stringify(value || {});
  let hash = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

// Hashing the scrape itself, rather than a hand-listed set of fields, is what
// keeps this honest: a page gaining a field the pack has since learned to read
// changes the hash and re-asks, instead of serving a stale answer forever.
function _scrapeSignature(scrape) {
  return _stableHash({
    title: scrape?.title || "",
    fields: scrape?.fields || {},
  });
}

function _localCacheKey(url) {
  return LOCAL_CACHE_KEY_PREFIX + url;
}

function _isFreshCachedEntry(entry, signature) {
  if (!entry || entry.ok !== true || !entry.result) return false;
  if (entry.signature !== signature) return false;
  const ageMs = Date.now() - Number(entry.fetchedAt || 0);
  return ageMs >= 0 && ageMs <= RESULT_CACHE_TTL_MS;
}

async function _readCachedAnalysis(url, signature) {
  const cacheKey = _localCacheKey(url);
  const data = await chrome.storage.local.get(cacheKey);
  const entry = data[cacheKey];
  if (_isFreshCachedEntry(entry, signature)) return entry;
  if (entry) {
    try {
      await chrome.storage.local.remove(cacheKey);
    } catch (error) {
      console.warn("[kriko] local result cache cleanup failed", error?.message || error);
    }
  }
  return null;
}

async function _writeCachedAnalysis(url, entry) {
  if (!entry || entry.ok !== true) return;
  try {
    await chrome.storage.local.set({ [_localCacheKey(url)]: entry });
  } catch (error) {
    console.warn("[kriko] local result cache write failed", error?.message || error);
  }
}

async function _updateBadgeForResult(result, tabId) {
  const risks = Array.isArray(result?.risks) ? result.risks : [];
  const highCount = risks.filter((r) => r.severity === "high").length;

  let badgeText = "";
  let badgeColor = "#2d7b41"; // low green
  if (highCount > 0) {
    badgeText = String(highCount);
    badgeColor = "#b5392f"; // high red
  } else if (risks.length > 0) {
    badgeText = String(risks.length);
    badgeColor = "#a3641a"; // medium orange
  }

  await chrome.action.setBadgeText({ text: badgeText, tabId });
  await chrome.action.setBadgeBackgroundColor({ color: badgeColor, tabId });
}

// ── scraping ────────────────────────────────────────────────────────────

async function _requestScrape(tabId, labels) {
  const ask = { type: "GET_SCRAPE", labels };
  try {
    const reply = await chrome.tabs.sendMessage(tabId, ask);
    if (reply && reply.ok) return reply;
  } catch (_) {
    // Content script not responding — inject it below.
  }

  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
  } catch (_) {
    return null;   // chrome:// or otherwise restricted
  }

  await new Promise((resolve) => setTimeout(resolve, 300));
  try {
    return await chrome.tabs.sendMessage(tabId, ask);
  } catch (_) {
    return null;
  }
}

async function requestAnalysis(scrape, timings = {}) {
  const endpoint = `${await apiBase()}/api/analyze`;
  const startedAt = _now();
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // `listing` is deliberately absent: the damage and equipment panels are
    // rendered locally and the engine has no rule for them, so there is no
    // reason to put them on the wire.
    body: JSON.stringify({
      url: scrape.url,
      title: scrape.title || "",
      description: scrape.description || "",
      fields: scrape.fields || {},
    }),
  });
  timings.analyze_fetch_ms = _elapsed(startedAt);

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`${endpoint} -> ${message || `HTTP ${response.status}`}`);
  }
  return response.json();
}

// ── the run ─────────────────────────────────────────────────────────────

async function runAnalysisForTab(tabId, url) {
  const storageKey = STORAGE_KEY_PREFIX + url;
  const existingRun = inFlightByStorageKey.get(storageKey);
  if (existingRun) {
    const result = await existingRun;
    await _updateBadgeForResult(result, tabId);
    return result;
  }

  const runPromise = _runAnalysisForTab(tabId, url, storageKey);
  inFlightByStorageKey.set(storageKey, runPromise);
  try {
    return await runPromise;
  } finally {
    if (inFlightByStorageKey.get(storageKey) === runPromise) {
      inFlightByStorageKey.delete(storageKey);
    }
  }
}

async function _runAnalysisForTab(tabId, url, storageKey) {
  const timings = {};
  const totalStartedAt = _now();
  const runId = nextRunId++;
  latestRunIdByStorageKey.set(storageKey, runId);
  // Hoisted so the catch block can attach it: the listing header and the
  // damage panel come from the scrape, not from the analysis, so they should
  // still render when the analysis itself fails.
  let scrape = null;

  try {
    const adapters = await fetchAdapters();
    const adapter = adapterFor(url, adapters);
    if (!adapter) {
      // Not an error the reader can act on — most pages are not listings —
      // but not something to answer with an empty result either, which would
      // read as "nothing is known about this car". Coded so the panel can
      // fall quiet instead of showing a red banner on every ordinary page.
      const noAdapter = new Error("No installed pack can read this page.");
      noAdapter.code = "NO_ADAPTER";
      throw noAdapter;
    }

    const scrapeStartedAt = _now();
    const reply = await _requestScrape(tabId, adapter.labels || []);
    timings.scrape_ms = _elapsed(scrapeStartedAt);
    if (!reply || !reply.ok) {
      throw new Error("Unable to read this page.");
    }
    scrape = reply.payload;

    const signature = _scrapeSignature(scrape);
    const cachedEntry = await _readCachedAnalysis(url, signature);
    if (cachedEntry) {
      await chrome.storage.session.set({ [storageKey]: cachedEntry });
      await _updateBadgeForResult(cachedEntry.result, tabId);
      return cachedEntry.result;
    }

    const result = toViewModel(await requestAnalysis(scrape, timings));

    if (latestRunIdByStorageKey.get(storageKey) !== runId) {
      return result;    // a newer run has already answered for this listing
    }

    const entry = {
      ok: true,
      result,
      listing: scrape.listing || {},
      signature,
      fetchedAt: Date.now(),
    };

    await chrome.storage.session.set({ [storageKey]: entry });
    await _writeCachedAnalysis(url, entry);
    await _updateBadgeForResult(result, tabId);
    timings.total_ms = _elapsed(totalStartedAt);
    return result;
  } catch (error) {
    console.warn("[kriko] analysis failed", error?.message || error);
    if (latestRunIdByStorageKey.get(storageKey) !== runId) throw error;

    const errEntry = {
      ok: false,
      error: error.message || "Unknown error",
      fetchedAt: Date.now(),
    };
    if (scrape) errEntry.listing = scrape.listing || {};
    await chrome.storage.session.set({ [storageKey]: errEntry });
    await chrome.action.setBadgeText({ text: "!", tabId });
    await chrome.action.setBadgeBackgroundColor({ color: "#b5392f", tabId });
    throw error;
  }
}

// ── messages ────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "ANALYZE") {
    const url = request.payload?.url;
    if (!url) {
      sendResponse({ ok: false, error: "Missing URL" });
      return false;
    }

    const run = async () => {
      let tabId = sender.tab?.id;
      if (!tabId) {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        tabId = tabs[0]?.id;
      }
      if (!tabId) throw new Error("No active tab found.");
      return runAnalysisForTab(tabId, url);
    };

    run()
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));

    return true; // async
  }

  if (request.type === "PAGE_LOADED") {
    const tabId = sender.tab?.id;
    const url = request.payload?.url;
    if (!tabId || !url) {
      sendResponse({ ok: false, error: "Missing tab or URL" });
      return false;
    }

    // Every page reports in; whether it is worth analysing is the installed
    // packs' answer, resolved inside the run.
    runAnalysisForTab(tabId, url).catch(() => {});
    sendResponse({ ok: true, message: "Analysis triggered" });
    return false;
  }

  if (request.type === "GET_CACHED_RESULT") {
    const url = request.payload?.url;
    if (!url) {
      sendResponse({ ok: false, error: "Missing URL" });
      return false;
    }

    const storageKey = STORAGE_KEY_PREFIX + url;
    chrome.storage.session
      .get(storageKey)
      .then((data) => {
        const entry = data[storageKey];
        if (!entry) {
          sendResponse({ ok: false, error: "No cached result" });
          return;
        }
        sendResponse({ ok: true, payload: entry });
      })
      .catch((err) => sendResponse({ ok: false, error: err.message }));

    return true; // async
  }
});

// ── clear the badge on navigation ───────────────────────────────────────
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    chrome.action.setBadgeText({ text: "", tabId }).catch(() => {});
  }
});
