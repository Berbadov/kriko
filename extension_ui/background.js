const DEFAULT_API_BASES = ["http://127.0.0.1:8000", "http://127.0.0.1:8765"];
const STORAGE_KEY_PREFIX = "kriko_result_";
const LOCAL_CACHE_KEY_PREFIX = "kriko_cached_result_";
const RESULT_CACHE_TTL_MS = 6 * 60 * 60 * 1000;
const latestRunIdByStorageKey = new Map();
const inFlightByStorageKey = new Map();
let nextRunId = 1;

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

// Hover Lite is the only in-page surface; the toolbar action toggles it.
chrome.runtime.onInstalled.addListener(_ensureSessionAccessLevel);

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || !tab.id) return;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "TOGGLE_HOVER_LITE" });
  } catch (_) {
    // Content script not present (e.g. chrome:// or unsupported host) — ignore.
  }
});

function _normalizeBaseUrl(value) {
  if (!value || typeof value !== "string") {
    return null;
  }

  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) {
    return null;
  }

  if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
    return `http://${trimmed}`;
  }

  return trimmed;
}

async function _getApiCandidates() {
  const fromStorage = await chrome.storage.local.get(["lemonaidApiBaseUrl"]);
  const customBase = _normalizeBaseUrl(fromStorage.lemonaidApiBaseUrl);

  const candidates = [];
  if (customBase) {
    candidates.push(`${customBase}/analyze`);
  }

  for (const base of DEFAULT_API_BASES) {
    candidates.push(`${base}/analyze`);
  }

  return [...new Set(candidates)];
}

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

function _metadataSignature(adMetadata) {
  return _stableHash({
    title: adMetadata?.title || "",
    make: adMetadata?.make || "",
    model: adMetadata?.model || "",
    trim: adMetadata?.trim || "",
    year: adMetadata?.year || "",
    mileage_km: adMetadata?.mileage_km || "",
    fuel_type: adMetadata?.fuel_type || "",
    transmission: adMetadata?.transmission || "",
    engine_volume_cc: adMetadata?.engine_volume_cc || "",
    power_hp: adMetadata?.power_hp || "",
    price_amount: adMetadata?.price_amount || "",
    damage_info: adMetadata?.damage_info || null,
    equipment: adMetadata?.equipment || null,
    technical_details: adMetadata?.technical_details || null,
  });
}

function _localCacheKey(url) {
  return LOCAL_CACHE_KEY_PREFIX + url;
}

function _isFreshCachedEntry(entry, metadataSignature) {
  if (!entry || entry.ok !== true || !entry.result) return false;
  if (entry.metadataSignature !== metadataSignature) return false;
  const ageMs = Date.now() - Number(entry.fetchedAt || 0);
  return ageMs >= 0 && ageMs <= RESULT_CACHE_TTL_MS;
}

async function _readCachedAnalysis(url, metadataSignature) {
  const cacheKey = _localCacheKey(url);
  const data = await chrome.storage.local.get(cacheKey);
  const entry = data[cacheKey];
  if (_isFreshCachedEntry(entry, metadataSignature)) {
    return entry;
  }
  if (entry) {
    try {
      await chrome.storage.local.remove(cacheKey);
    } catch (error) {
      console.warn("[lemonaid] local result cache cleanup failed", error?.message || error);
    }
  }
  return null;
}

async function _writeCachedAnalysis(url, entry) {
  if (!entry || entry.ok !== true) return;
  try {
    await chrome.storage.local.set({ [_localCacheKey(url)]: entry });
  } catch (error) {
    console.warn("[lemonaid] local result cache write failed", error?.message || error);
  }
}

async function _updateBadgeForResult(result, tabId) {
  const riskCount = Array.isArray(result?.risks) ? result.risks.length : 0;
  const highCount = Array.isArray(result?.risks)
    ? result.risks.filter((r) => r.severity === "high").length
    : 0;

  let badgeText = "";
  let badgeColor = "#2d7b41"; // low green
  if (highCount > 0) {
    badgeText = String(highCount);
    badgeColor = "#b5392f"; // high red
  } else if (riskCount > 0) {
    badgeText = String(riskCount);
    badgeColor = "#a3641a"; // medium orange
  }

  await chrome.action.setBadgeText({ text: badgeText, tabId });
  await chrome.action.setBadgeBackgroundColor({ color: badgeColor, tabId });
}

async function requestAnalysis(adMetadata, timings = {}) {
  const { lemonaidDebugMode = false } = await chrome.storage.local.get([
    "lemonaidDebugMode",
  ]);
  const payload = {
    listing_url: adMetadata.url,
    ad_metadata: adMetadata,
    debug: Boolean(lemonaidDebugMode),
  };

  const endpoints = await _getApiCandidates();
  const errors = [];

  for (const endpoint of endpoints) {
    try {
      const fetchStartedAt = _now();
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      timings.analyze_fetch_ms = _elapsed(fetchStartedAt);
      timings.analyze_endpoint = endpoint;

      if (!response.ok) {
        const message = await response.text();
        errors.push(`${endpoint} -> ${message || "HTTP error"}`);
        continue;
      }

      const jsonStartedAt = _now();
      const data = await response.json();
      timings.analyze_json_ms = _elapsed(jsonStartedAt);

      return {
        endpoint,
        debugRequested: payload.debug,
        data,
      };
    } catch (error) {
      const message = error?.message || "Network error";
      errors.push(`${endpoint} -> ${message}`);
    }
  }

  throw new Error(
    `Analyzer API request failed on all endpoints. Tried: ${errors.join(" | ")}`
  );
}

async function _ensureContentScript(tabId) {
  // Try a quick ping first
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { type: "GET_AD_METADATA" });
    if (pong && pong.ok) {
      return pong;
    }
  } catch (_) {
    // Content script not responding — inject it
  }

  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content.js"],
    });
  } catch (_) {
    // Cannot inject (e.g., chrome:// pages or restricted URLs)
    return null;
  }

  // Wait for content script to initialize
  await new Promise((resolve) => setTimeout(resolve, 300));

  try {
    return await chrome.tabs.sendMessage(tabId, { type: "GET_AD_METADATA" });
  } catch (_) {
    return null;
  }
}

async function runAnalysisForTab(tabId, url) {
  const storageKey = STORAGE_KEY_PREFIX + url;
  const existingRun = inFlightByStorageKey.get(storageKey);
  if (existingRun) {
    console.log("[lemonaid] joining in-flight analysis", { tabId, url });
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
  // Hoisted so the catch block can attach it to the error entry — critical
  // alerts and the listing header are derived from metadata, not the LLM, so
  // they should still render even when the analysis itself fails.
  let adMetadata = null;

  try {
    console.log("[lemonaid] runAnalysisForTab start", { tabId, url, runId });
    const metadataStartedAt = _now();
    const metaResponse = await _ensureContentScript(tabId);
    timings.metadata_ms = _elapsed(metadataStartedAt);
    console.log("[lemonaid] metaResponse", metaResponse?.ok ? "ok" : "fail");
    if (!metaResponse || !metaResponse.ok) {
      throw new Error("Unable to read ad metadata from this page.");
    }

    adMetadata = metaResponse.payload;
    const metadataSignature = _metadataSignature(adMetadata);
    const cacheStartedAt = _now();
    const cachedEntry = await _readCachedAnalysis(url, metadataSignature);
    timings.cache_lookup_ms = _elapsed(cacheStartedAt);
    if (cachedEntry) {
      console.log("[lemonaid] using cached analysis", {
        title: adMetadata.title,
        url,
        ageMs: Date.now() - Number(cachedEntry.fetchedAt || 0),
      });
      await chrome.storage.session.set({ [storageKey]: cachedEntry });
      const badgeStartedAt = _now();
      await _updateBadgeForResult(cachedEntry.result, tabId);
      timings.badge_ms = _elapsed(badgeStartedAt);
      timings.total_ms = _elapsed(totalStartedAt);
      console.log("[lemonaid] timings", timings);
      return cachedEntry.result;
    }

    console.log("[lemonaid] POST /analyze", { title: adMetadata.title, url });
    const response = await requestAnalysis(adMetadata, timings);
    const result = response.data;
    console.log("[lemonaid] /analyze returned", {
      runId,
      endpoint: response.endpoint,
      debugRequested: response.debugRequested,
      risks: result?.risks?.length,
      hasDebugTrace: Boolean(result?.debug_trace),
    });

    if (latestRunIdByStorageKey.get(storageKey) !== runId) {
      console.log("[lemonaid] stale analysis result ignored", { tabId, url, runId });
      return result;
    }

    const entry = {
      ok: true,
      result,
      adMetadata,
      metadataSignature,
      fetchedAt: Date.now(),
    };

    const sessionStartedAt = _now();
    await chrome.storage.session.set({ [storageKey]: entry });
    timings.session_write_ms = _elapsed(sessionStartedAt);
    const localCacheStartedAt = _now();
    await _writeCachedAnalysis(url, entry);
    timings.local_cache_write_ms = _elapsed(localCacheStartedAt);

    const badgeStartedAt = _now();
    await _updateBadgeForResult(result, tabId);
    timings.badge_ms = _elapsed(badgeStartedAt);
    timings.total_ms = _elapsed(totalStartedAt);
    console.log("[lemonaid] timings", timings);

    return result;
  } catch (error) {
    console.warn("[lemonaid] analysis failed", error?.message || error);
    if (latestRunIdByStorageKey.get(storageKey) !== runId) {
      console.log("[lemonaid] stale analysis error ignored", { tabId, url, runId });
      throw error;
    }
    const errEntry = {
      ok: false,
      error: error.message || "Unknown error",
      fetchedAt: Date.now(),
    };
    if (adMetadata) errEntry.adMetadata = adMetadata;
    await chrome.storage.session.set({ [storageKey]: errEntry });
    await chrome.action.setBadgeText({ text: "!", tabId });
    await chrome.action.setBadgeBackgroundColor({ color: "#b5392f", tabId });
    timings.total_ms = _elapsed(totalStartedAt);
    console.log("[lemonaid] timings", timings);
    throw error;
  }
}

// ── Message listeners ──

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "ANALYZE_AD") {
    const url = request.payload?.url;
    if (!url) {
      sendResponse({ ok: false, error: "Missing URL" });
      return false;
    }

    // If triggered from popup (no sender.tab), resolve active tab first
    const run = async () => {
      let tabId = sender.tab?.id;
      if (!tabId) {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        tabId = tabs[0]?.id;
      }
      if (!tabId) {
        throw new Error("No active tab found.");
      }
      return runAnalysisForTab(tabId, url);
    };

    run()
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));

    return true; // async
  }

  if (request.type === "PAGE_LOADED") {
    const tabId = sender.tab?.id;
    const url = request.payload?.url;

    if (!tabId || !url) {
      sendResponse({ ok: false, error: "Missing tab or URL" });
      return false;
    }

    // Kick off analysis in the background without waiting
    runAnalysisForTab(tabId, url).catch(() => {
      // Silently fail; popup will show error state
    });

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

// ── Clear badge on tab navigation ──
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "loading") {
    chrome.action.setBadgeText({ text: "", tabId }).catch(() => {});
  }
});
