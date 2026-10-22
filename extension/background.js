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

// Firefox exposes Promise APIs on browser; Chromium uses extensionApi.
const extensionApi = typeof browser !== "undefined" ? browser : chrome;
const IS_FIREFOX = typeof extensionApi.runtime.getBrowserInfo === "function";

const DEFAULT_API_BASE = "http://127.0.0.1:8787";
const LOADED_CONTENT_DIGEST = "";
const CONNECTION_ALARM = "kriko-connection";
const CONNECTION_PERIOD_MINUTES = 1;
// A watched page is re-read by the app; this asks it to, and says so when a
// price crossed what the reader asked for (see `checkBuyerAlerts`).
const PRICE_ALARM = "kriko-prices";
const PRICE_PERIOD_MINUTES = 30;
const BUYER_KEY_PREFIX = "kriko_buyer_";
const GUARD_KEY_PREFIX = "kriko_guard_";
// A purchase is asked about at most this often, however many pages are opened.
const DUE_NUDGE_QUIET_MS = 20 * 60 * 60 * 1000;
// What a cart or payment page's address says. The same words as
// `app/checkout.py`'s CHECKOUT_PATH, which a test holds equal.
const CHECKOUT_PATH = /\/(?:cart|basket|bag|checkout|payment|pay|order|sepet|sepetim|odeme|siparis|warenkorb|kasse|panier|paiement|carrito|pagar|carrello|winkelwagen|zamowienie|koszyk)(?:\/|\.|$|\?)/i;
const ACTION_ICONS = {
  online: { 16: "assets/icons/icon-16.png", 32: "assets/icons/icon-32.png",
            48: "assets/icons/icon-48.png" },
  offline: { 16: "assets/icons/icon-offline-16.png",
             32: "assets/icons/icon-offline-32.png",
             48: "assets/icons/icon-offline-48.png" },
};

//: How many rows one search may return to the panel. The engine allows up to
//: 50; a floating panel beside a listing is a list somebody scans, and the
//: right answer to "I cannot see it" is a better query rather than more rows.
const SEARCH_LIMIT = 12;
const STORAGE_KEY_PREFIX = "kriko_result_";

/* Where a run says what it is doing, while it is doing it.
 *
 * Separate from the result key on purpose: the result is written once, at the
 * end, and the panel's whole complaint was that the several seconds before
 * that were a spinner and an invented sentence. A stage is written as each
 * step begins, so the panel can say which step it is on rather than guessing.
 *
 * Session storage rather than a message, for the reason the result uses it: a
 * `runtime.sendMessage` broadcast does not reach a content script, and the
 * panel is one.
 */
const STAGE_KEY_PREFIX = "kriko_stage_";

/** Record which step a run has reached. Never throws: a run must not fail
 *  because the thing narrating it did. */
async function _stage(url, name, detail = "") {
  try {
    await extensionApi.storage.session.set({
      [STAGE_KEY_PREFIX + url]: { name, detail, at: Date.now() },
    });
  } catch (_) {
    // Storage full, or the worker torn down mid-write. The run continues.
  }
}
const LOCAL_CACHE_KEY_PREFIX = "kriko_cached_result_";
const RESULT_CACHE_TTL_MS = 6 * 60 * 60 * 1000;
const ADAPTERS_TTL_MS = 5 * 60 * 1000;

// The handshake's two names, matched in `app/extension.py`. The header is
// what we tell the app; `COMPAT_KEY` is where the verdict it gives back is
// kept, because the options page has to be able to show it without the app
// running — a reader whose extension is too old to talk to the app is
// precisely the reader who needs to read the sentence.
const VERSION_HEADER = "X-Kriko-Extension";
const MINIMUM_HEADER = "X-Kriko-Minimum-Extension";
const COMPAT_KEY = "krikoCompat";

// The three steps of the information-sensitivity setting, as the app names
// them: show everything, hide thin evidence, show only what is solid.
const INFO_SENSITIVITIES = ["all", "hide_thin", "strict"];
function _sensitivityOf(settings) {
  const value = settings && settings.info_sensitivity;
  return INFO_SENSITIVITIES.includes(value) ? value : "all";
}

// Tiers whose word stands on its own. Anything else is corroboration: worth
// showing, worth counting, not worth presenting as settled.
const CONFIRMING_TIERS = new Set(["authoritative", "manufacturer"]);

const latestRunIdByStorageKey = new Map();
const inFlightByStorageKey = new Map();
let nextRunId = 1;
let adaptersCache = null;

// Expose extensionApi.storage.session to content scripts. The Hover Lite panel is a
// content script and relies on extensionApi.storage.onChanged (session area) to learn
// when a background analysis lands — runtime.sendMessage broadcasts never reach
// content scripts. Session storage is restricted to trusted contexts by
// default, so without this the hover panel silently misses results that arrive
// after it opens and stays stuck on the empty state (issue #28). Called at the
// service-worker top level so it re-applies on every worker startup.
function _ensureSessionAccessLevel() {
  try {
    extensionApi.storage.session
      .setAccessLevel({ accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS" })
      .catch(() => {});
  } catch (_) {
    // Older Chrome without setAccessLevel — ignore.
  }
}
_ensureSessionAccessLevel();

extensionApi.runtime.onInstalled.addListener(_ensureSessionAccessLevel);

// Firefox keeps session storage private to extension pages and has no
// setAccessLevel API. Deliver only this tab's result/stage through messaging.
// This is the delivery path, not a storage policy: the live result and the
// stage stay in session memory, while the six-hour answer cache below is
// storage.local on every browser and is keyed by a digest of the address
// rather than by the address itself.
if (IS_FIREFOX) {
  extensionApi.storage.onChanged.addListener((changes, area) => {
    if (area !== "session") return;
    void (async () => {
      const tabs = await extensionApi.tabs.query({});
      for (const tab of tabs) {
        if (!tab.url || tab.id === undefined) continue;
        const result = changes[STORAGE_KEY_PREFIX + tab.url]?.newValue;
        const stage = changes[STAGE_KEY_PREFIX + tab.url]?.newValue;
        if (result === undefined && stage === undefined) continue;
        try {
          await extensionApi.tabs.sendMessage(tab.id, {
            type: "KRIKO_SESSION_UPDATE", url: tab.url, result, stage,
          });
        } catch (_) { /* A permitted tab may not have a panel loaded yet. */ }
      }
    })().catch(() => {});
  });
}

// Hover Lite is the only in-page surface, and there are two ways to reach it.
//
// One function rather than a listener each, because a keyboard shortcut whose
// behaviour has drifted from the toolbar button's is worse than no shortcut:
// the reader learns the key, and then one day it does something else.
async function toggleHoverLite(tab) {
  if (!tab || !tab.id) return false;
  try {
    await extensionApi.tabs.sendMessage(tab.id, { type: "TOGGLE_HOVER_LITE" });
    return true;
  } catch (_) {
    // Content script not present (e.g. chrome:// or unsupported host) — ignore.
    return false;
  }
}

// The toolbar click, on any page.
//
// It used to toggle the panel and give up silently where no content script is
// running — which is every site no pack has an adapter for, and which the
// reader experienced as "I cannot open the extension on pages that aren't
// registered, so basically it opens on one site only". Nothing was broken;
// the site was simply unknown, and the extension had no way to say so.
//
// So a click that finds no panel now *reports the page* to the app. The app
// answers whether it can read the site, and when it cannot it records the ask
// — which is the only honest input to "which site should Kriko learn next",
// and the list the Sites screen offers a Register button on.
//
// `activeTab` is what makes this legitimate: the click is the grant, for that
// tab, at that moment. No new host permission is requested, nothing is read
// from the page, and the URL leaves the browser only because the reader
// pressed a button meaning "tell Kriko about this page".
extensionApi.action.onClicked.addListener((tab) => { void onToolbarClick(tab); });

async function onToolbarClick(tab) {
  // Asked before anything is awaited: Chrome accepts `permissions.request`
  // only inside the click's own gesture, and one `await` can spend it.
  const asking = _askEverySiteOnce(tab);
  if (await toggleHoverLite(tab)) return true;
  if (await _openPanelHere(tab)) {
    void asking;
    return true;
  }
  return reportUnreadableSite(tab);
}

// ── any product page (B149) ─────────────────────────────────────────────
//
// The reader's words: *"new products aren't recognised, in new sites products
// can't be grabbed"*, and their choice: grant once, and Kriko reads any
// product page itself. One grant — `https://*/*`, already the manifest's
// optional permission — asked for on the first toolbar click anywhere Kriko
// does not already run. Once given, one registration puts the panel on every
// https page; the page's own schema.org data and product name are what the
// app reads, and a page that publishes no product stays silent.

const EVERY_SITE = "https://*/*";
const ANY_SITE_SCRIPT_ID = "kriko-anysite";
let everySiteGranted = null;   // unknown until asked; the worker restarts often

if (extensionApi.permissions && extensionApi.permissions.contains) {
  extensionApi.permissions.contains({ origins: [EVERY_SITE] })
    .then((yes) => { everySiteGranted = Boolean(yes); })
    .catch(() => {});
}

function _askEverySiteOnce(tab) {
  const url = String((tab && tab.url) || "");
  if (everySiteGranted === true || !/^https:/i.test(url)) return null;
  if (!extensionApi.permissions || !extensionApi.permissions.request) return null;
  // Not on a site the package already runs on: the panel works there, and a
  // prompt on the reader's usual site would be asking for nothing they need.
  if (staticSiteHosts().has(_hostOf(url))) return null;
  try {
    return Promise.resolve(extensionApi.permissions.request({ origins: [EVERY_SITE] }))
      .then((yes) => { everySiteGranted = Boolean(yes); return yes; })
      .catch(() => false);
  } catch (_) {
    return null;
  }
}

// Put the panel on this one tab, now. `activeTab` makes the click itself the
// grant for this tab, so this works whether or not the every-site ask was
// accepted — declining costs the automatic answer, never the button.
async function _openPanelHere(tab) {
  const url = String((tab && tab.url) || "");
  if (!tab || !tab.id || !/^https:/i.test(url) || !extensionApi.scripting) return false;
  try {
    await extensionApi.scripting.executeScript({ target: { tabId: tab.id }, files: SITE_SCRIPTS });
  } catch (_) {
    return false;    // a page Chrome keeps extensions out of (the web store, say)
  }
  return toggleHoverLite(tab);
}

async function reportUnreadableSite(tab) {
  const url = tab && tab.url;
  if (!url || !/^https?:/i.test(url)) return false;
  try {
    // Read the page once, through the content script this click just injected.
    // This is the snapshot an agent needs in order to write an adapter without
    // fetching the page: the browser is already past whatever bot check the
    // site runs, and it can see label/value shapes a plain fetch never renders.
    // Best-effort — a page that refuses to be read still becomes an ask.
    const scraped = await _requestScrape(tab.id, [], null, true).catch(() => null);
    const page = (scraped && scraped.payload) || null;
    const body = { url, title: (tab && tab.title) || "" };
    if (page && typeof page === "object") {
      body.fields = page.fields || {};
      body.description = String(page.description || "").slice(0, 5000);
      body.product = page.product || {};
      body.page_title = String(page.title || "").slice(0, 500);
    }
    const response = await _fetchApp(`${await apiBase()}/api/sites/seen`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const answer = response && response.ok ? await response.json() : null;
    // A site the app *can* read, with no panel on it, is a different bug —
    // and for six versions this branch guessed at which one and guessed
    // wrong. It said "reloading the page should show the panel", the reader
    // reloaded, nothing happened, and the message came back unchanged, because
    // the actual blocker was a host permission Chrome will only grant from a
    // gesture inside this extension. No number of reloads can supply that.
    //
    // So: re-sync, then read what the sync actually concluded about *this*
    // host, and say that. A reload is only offered where a reload is genuinely
    // what is missing.
    if (answer && answer.readable) {
      const record = await syncSites({ fresh: true });
      const host = _hostOf(url);
      const row = (record.sites || []).find((one) => one.site === host);
      if (row && row.state === "pending") {
        await notify(
          tab,
          "Kriko reads this site, but your browser has not granted it "
          + "permission yet. Open Kriko's extension options and press Grant: "
          + "only the extension can ask.",
        );
        if (extensionApi.runtime.openOptionsPage) extensionApi.runtime.openOptionsPage();
        return true;
      }
      if (row && row.state === "refused") {
        await notify(tab, `Kriko cannot register this site: ${row.detail || "the browser refused it"}`);
        return true;
      }
      // Registered and permitted. A content script only starts on a load, so
      // here — and only here — a reload really is the missing step, and we do
      // it rather than asking for it.
      await notify(tab, "Kriko reads this site. Reloading to show the panel…");
      if (extensionApi.tabs && extensionApi.tabs.reload) await extensionApi.tabs.reload(tab.id);
      return true;
    }
    await notify(
      tab,
      "Kriko cannot read this site yet. It has been added to Sites in the app, where you can ask an agent to learn it.",
    );
    return true;
  } catch (_) {
    await notify(tab, "Kriko is not running. Open the app and press this again.");
    return false;
  }
}

// One line of feedback, in the page, with no content script required.
// `extensionApi.scripting.executeScript` under `activeTab` is granted by the click
// itself; a toast that needs a permission the reader has not given would be a
// message they never see.
async function notify(tab, text) {
  if (!tab || !tab.id || !extensionApi.scripting) return;
  try {
    await extensionApi.scripting.executeScript({
      target: { tabId: tab.id },
      func: (message) => {
        const box = document.createElement("div");
        box.textContent = message;
        box.style.cssText =
          "position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:320px;" +
          "padding:12px 14px;border-radius:8px;font:13px/1.4 system-ui,sans-serif;" +
          "background:#15171c;color:#e7e9ed;border:1px solid #2c313a;box-shadow:0 8px 24px rgba(0,0,0,.4)";
        document.documentElement.appendChild(box);
        setTimeout(() => box.remove(), 6000);
      },
      args: [text],
    });
  } catch (_) {
    // A page that refuses injection (a store page, a PDF viewer) is not an
    // error worth surfacing: the ask was still recorded.
  }
}

// The keyboard door. `commands` is declared in the manifest with a *suggested*
// key, not a claimed one — Chrome drops a suggestion that collides with
// something the browser or another extension already owns, and the command
// still exists with no key bound. So this listener must not assume it will
// ever fire, and the panel must stay reachable without it; the shortcut is an
// accelerator for a reader whose hands are on the keyboard reading a listing,
// never the only way in.
//
// Unlike the toolbar click there is no tab argument: a command fires at the
// browser, so the active tab has to be asked for.
if (extensionApi.commands && extensionApi.commands.onCommand) {
  extensionApi.commands.onCommand.addListener(async (command) => {
    if (command !== "toggle-panel") return;
    const tabs = await extensionApi.tabs.query({ active: true, currentWindow: true });
    await onToolbarClick(tabs[0]);
  });
}

// ── where the app is ────────────────────────────────────────────────────

function _normalizeBaseUrl(value) {
  if (!value || typeof value !== "string") return null;
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) return null;
  const candidate = /^https?:\/\//.test(trimmed) ? trimmed : `http://${trimmed}`;
  // A prefix and a trim are not validation: "not a url" becomes a syntactically
  // fine-looking "http://not a url" that then fails every request silently.
  // Parsing it is the only way to tell "typo" from "an address Kriko can reach".
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }
  if (!/^https?:$/.test(parsed.protocol) || !parsed.hostname) return null;
  return parsed.origin;
}

async function apiBase() {
  const stored = await extensionApi.storage.local.get(["krikoApiBaseUrl"]);
  return _normalizeBaseUrl(stored.krikoApiBaseUrl) || DEFAULT_API_BASE;
}

// ── which sites are worth scraping ──────────────────────────────────────

function globToRegExp(pattern) {
  const escaped = String(pattern).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const body = escaped
    // Chrome's own host rule, which this hand-rolled matcher never had: in a
    // match pattern `*.example.com` means "example.com **or** any subdomain
    // of it". Read as a plain glob it means "a subdomain of it", and the bare
    // host then matches nothing.
    //
    // That is why a newly added site read nothing at all. `sites.py` writes
    // `*://*.<site>/*` for every adapter it generates, and Chrome — which
    // applies the real semantics — duly injected the content script on
    // `https://<site>/...`. The page was scraped and handed here, where
    // `adapterFor` found no adapter for the very URL Chrome had matched, and
    // the panel opened knowing nothing. Two matchers disagreeing is the whole
    // bug; this is the side that was wrong.
    .replace(/:\/\/\\\*\\\./g, "://(?:[^/]+\\.)?")
    .replace(/\\\*/g, ".*");
  // A pack writes `*shop.example/urun/*`: the star stands for the scheme and an optional
  // `www.`-style prefix, not for any text at all. As `.*` it matched `evilshop.example` and a
  // search URL that merely carried the address in its query.
  const leading = /^\\\*[a-z0-9]/i.test(escaped)
    ? body.replace(/^\.\*/, "[a-z][a-z0-9+.-]*://(?:[^/]*\\.)?")
    : body;
  return new RegExp("^" + leading + "$", "i");
}

// Every adapter claiming this page, folded into one scrape request (B150).
// Several packs may claim one site — a marketplace sells everything — and
// which of them reads the page is the app's decision, made with the page in
// hand. So the scrape asks for the union of their labels, and the page's own
// panel comes from the first adapter that declares one: taking the first
// match alone let an agent-written phone pack's reader decide what a car
// listing's scrape looked for.
function adapterFor(url, adapters) {
  const matching = (adapters || []).filter((adapter) =>
    (adapter.match || []).some((p) => globToRegExp(p).test(url)));
  if (!matching.length) return null;
  if (matching.length === 1) return matching[0];
  const labels = [...new Set(matching.flatMap((one) => one.labels || []))];
  const withPanel = matching.find((one) =>
    one.local_panel && Object.keys(one.local_panel).length);
  return { ...matching[0], labels, local_panel: (withPanel || matching[0]).local_panel || {} };
}

// Whether *some* installed adapter reads this site at all, even though none
// of its patterns matched this exact page. A pack's match pattern is a glob
// like `*example.com/listing/*` — the domain fragment before the first `/` is
// as much "which site" as this extension can read without hardcoding a
// site's own shape (the scalability principle: no site vocabulary here).
// Distinguishing this from "no pack reads this site" is extension-5/6 (B145
// audit): a site Kriko does read should never say "nothing installed knows
// how to read this site".
function hostHasAnyAdapter(url, adapters) {
  let hostname;
  try {
    hostname = new URL(url).hostname;
  } catch {
    return false;
  }
  return (adapters || []).some((adapter) =>
    (adapter.match || []).some((pattern) => {
      const domainFragment = pattern.split("/")[0].replace(/\*/g, "");
      return domainFragment && hostname.includes(domainFragment);
    })
  );
}

// A refused connection and a 500 are different problems with different fixes,
// and until now both arrived as one red banner. `fetch` rejects rather than
// resolving when nothing is listening, so the two are only distinguishable
// here, at the call — by the time an error reaches the panel it is a string.
// The version rides on every request, on purpose. A check-in on a timer is a
// second clock to keep wound and goes stale between winds; a header on work
// the worker was going to do anyway cannot be forgotten and cannot be true
// while the extension is broken. Read off the manifest rather than written
// here, because two places that both state the version eventually disagree
// and the disagreement is invisible.
//
// Safe from a CORS preflight: `http://127.0.0.1/*` is in `host_permissions`,
// which exempts the worker's own fetches — and the worker is the only thing
// in this extension that fetches. A content script adding this header would
// turn every lookup into an OPTIONS the app does not answer.
function _ownVersion() {
  try {
    return String(extensionApi.runtime.getManifest().version || "");
  } catch (_) {
    return "";
  }
}

// An app that is up but wedged used to hold a request — and the panel's
// spinner — forever: `fetch` has no timeout of its own. Every call the
// worker makes is local and answers in well under a second, and long work is
// a job the app answers for at once, so a request still open after this is a
// hung app, not a slow one. It says so, rather than "not running".
const APP_TIMEOUT_MS = 30000;

async function _fetchApp(url, init) {
  const stamped = { ...(init || {}) };
  stamped.headers = { ...(stamped.headers || {}), [VERSION_HEADER]: _ownVersion() };
  if (LOADED_CONTENT_DIGEST) stamped.headers["X-Kriko-Extension-Digest"] = LOADED_CONTENT_DIGEST;
  const clock = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    clock.abort();
  }, APP_TIMEOUT_MS);
  if (stamped.signal) stamped.signal.addEventListener("abort", () => clock.abort(), { once: true });
  stamped.signal = clock.signal;
  try {
    const response = await fetch(url, stamped);
    void _noteMinimum(response);
    void _noteStaged(response);
    return response;
  } catch (cause) {
    // Our own clock, and nothing else: a transport failure that happens to
    // land after the timer is still "not running".
    const hung = timedOut && cause && cause.name === "AbortError";
    const down = hung
      ? new Error("Kriko is open but did not answer in 30 seconds. Try again; "
          + "if it keeps happening, quit Kriko from its tray icon and open it again.")
      : new Error("Kriko is not running. Open the Kriko app, then try again.");
    down.code = hung ? "APP_NOT_RESPONDING" : "APP_NOT_RUNNING";
    down.cause = cause;
    throw down;
  } finally {
    clearTimeout(timer);
  }
}

// Chrome suspends this worker while it is idle. The toolbar icon is browser
// state, not worker memory, so refresh it on browser startup and a short alarm.
// A separate icon leaves the per-tab risk count and question/error badges alone.
let connectionProbe = null;
async function refreshConnectionIcon() {
  if (connectionProbe) return connectionProbe;
  connectionProbe = (async () => {
    let connected = false;
    let version = "";
    try {
      const response = await _fetchApp(`${await apiBase()}/api/health`);
      if (response.ok) {
        const health = await response.json();
        connected = health?.ok === true;
        version = String(health?.version || "");
      }
    } catch (_) {
      // No listener is the ordinary state before Kriko starts.
    }
    await extensionApi.action.setIcon({ path: connected ? ACTION_ICONS.online : ACTION_ICONS.offline });
    await extensionApi.action.setTitle({ title: connected
      ? `Kriko ${version}: connected. Click to open the panel.`
      : "Kriko: app is not running. Open Kriko to connect." });
    return connected;
  })();
  try {
    return await connectionProbe;
  } finally {
    connectionProbe = null;
  }
}

// ── the other half of the handshake ─────────────────────────────────────
//
// The app answers with the oldest extension it can talk to, on every
// response. So the check is a read of an answer we already have — not a
// second endpoint, not a poll, and not a version table in here that would
// have to be edited in step with the app's. `parseVersion` and the states
// match `app/extension.py`; the *floor* lives there, which is the point.
//
// Stored rather than held in a variable: a service worker is killed after
// about thirty seconds idle, and the options page a reader opens minutes
// later is a fresh worker with no memory of any of this.
// ── files on disk newer than the files running (B151) ───────────────────
//
// An unpacked extension runs what it read when it loaded, and an app update
// rewrites the folder under it without telling Chrome. The reader's browser
// ran a background.js two releases old — one that sent a listing's name and
// none of its facts — while both ends said 0.3.0. The app now answers every
// request with the digest of the files on disk; when that is not this
// worker's own stamp, the worker reloads itself from them. Once per digest
// per ten minutes, so a folder that cannot be read cannot loop.
const STAGED_HEADER = "x-kriko-staged-digest";
const SELF_RELOAD_KEY = "krikoSelfReload";
const SELF_RELOAD_QUIET_MS = 10 * 60 * 1000;

async function _noteStaged(response) {
  let staged = "";
  try {
    staged = response.headers.get(STAGED_HEADER) || "";
  } catch (_) {
    return;
  }
  if (!staged || !LOADED_CONTENT_DIGEST || staged === LOADED_CONTENT_DIGEST) return;
  try {
    const got = await extensionApi.storage.local.get(SELF_RELOAD_KEY);
    const last = got && got[SELF_RELOAD_KEY];
    if (last && last.digest === staged && Date.now() - last.at < SELF_RELOAD_QUIET_MS) return;
    await extensionApi.storage.local.set({
      [SELF_RELOAD_KEY]: { digest: staged, at: Date.now(), pending: true },
    });
    extensionApi.runtime.reload();
  } catch (_) {
    // A worker that cannot reload keeps working on the files it has.
  }
}

// After a self-reload the listing tabs still hold the old content script,
// cut off from this worker. Refresh them so the panel on screen is the new one.
extensionApi.runtime.onInstalled.addListener(async (details) => {
  if (!details || details.reason !== "update") return;
  try {
    const got = await extensionApi.storage.local.get(SELF_RELOAD_KEY);
    const last = got && got[SELF_RELOAD_KEY];
    if (!last || !last.pending) return;
    await extensionApi.storage.local.set({ [SELF_RELOAD_KEY]: { ...last, pending: false } });
    // Every site the panel is injected on: the manifest's own blocks (none
    // are shipped today) and the per-site registrations, which persist across
    // the reload. Not the every-site one: `https://*/*` would reload every
    // tab the reader has open to refresh a panel most of them never showed.
    const patterns = [];
    const blocks = [
      ...(extensionApi.runtime.getManifest().content_scripts || []),
      ...(await _registeredSiteScripts()),
    ];
    for (const entry of blocks) {
      for (const one of entry.matches || []) if (!patterns.includes(one)) patterns.push(one);
    }
    if (!patterns.length) return;
    for (const tab of await extensionApi.tabs.query({ url: patterns })) {
      if (tab && tab.id !== undefined) extensionApi.tabs.reload(tab.id);
    }
  } catch (_) {
    // Nothing to refresh is the common case.
  }
});

function parseVersion(text) {
  const parts = [];
  for (const piece of String(text || "").split(".")) {
    const digits = /^\d+/.exec(piece);
    if (!digits) break;
    parts.push(Number(digits[0]));
  }
  return parts;
}

function _olderThan(have, floor) {
  const length = Math.max(have.length, floor.length);
  for (let i = 0; i < length; i += 1) {
    const a = have[i] || 0;
    const b = floor[i] || 0;
    if (a !== b) return a < b;
  }
  return false;
}

async function _noteMinimum(response) {
  // A response with no such header is an app too old to have the handshake,
  // which is not a problem this extension has: an older app answers this
  // extension's requests fine, and inventing a complaint about it would put
  // a warning on the one reader who has nothing to fix.
  let floor = "";
  try {
    floor = response.headers.get(MINIMUM_HEADER) || "";
  } catch (_) {
    return;
  }
  if (!floor) return;
  const mine = _ownVersion();
  const record = {
    at: Date.now(),
    minimum: floor,
    running: mine,
    stale: _olderThan(parseVersion(mine), parseVersion(floor)),
  };
  try {
    await extensionApi.storage.local.set({ [COMPAT_KEY]: record });
  } catch (_) {
    // Nothing to do and nothing lost: the next response says it again.
  }
}

async function readCompat() {
  try {
    const stored = await extensionApi.storage.local.get([COMPAT_KEY]);
    return stored[COMPAT_KEY] || null;
  } catch (_) {
    return null;
  }
}

async function fetchAdapters() {
  if (adaptersCache && Date.now() - adaptersCache.at < ADAPTERS_TTL_MS) {
    return adaptersCache.rows;
  }
  const response = await _fetchApp(`${await apiBase()}/api/adapters`);
  if (!response.ok) {
    throw new Error(`Kriko is not reachable (${response.status}).`);
  }
  const rows = await response.json();
  adaptersCache = { at: Date.now(), rows };
  return rows;
}

// ── the extension learning a new site by itself ─────────────────────────
//
// The header above has promised since Phase 6c that "installing a pack for a
// new listing site needs no extension change at all". That was half true: the
// *server* learned a site the moment its adapter file existed, and the
// extension learned it when somebody remembered to edit `manifest.json`'s
// `content_scripts` by hand. Nothing failed when they forgot — the pack
// installed, `/api/adapters` listed the site, and the reader opened a listing
// to no panel at all, which is indistinguishable from "nothing known about
// this car".
//
// This closes it. The four pieces the seam needs:
//
// *Detection.* The app already knows; it is the only thing that can. So the
// worker asks — `/api/adapters` is the same endpoint a run already uses, and
// an adapter's `site` is a bare registrable host (`example.com`), which
// becomes exactly one match pattern. No hostname list lives in this file, and
// none should ever be added to it.
//
// *Synchronisation.* `extensionApi.scripting` holds the registration, not this
// worker's memory — an MV3 worker is stopped and restarted constantly, and a
// registration that lived in a variable would evaporate with it. So every
// sync reads back what Chrome currently has (`getRegisteredContentScripts`)
// and reconciles towards what the adapters ask for. Convergent, not
// incremental: running it twice changes nothing the second time, which is
// what lets it run from four unrelated triggers.
//
// *Conflicts.* Script ids are derived — `kriko-site-<host>` — so the same
// site can never be registered twice, and a stale registration for a pack
// that was uninstalled is recognisable by its id rather than by remembering
// we made it. Sites the static manifest already covers are skipped
// deliberately: registering them again would inject every content script
// twice on the one site that works today.
//
// *Failure recovery.* The app is usually not running — that is the ordinary
// state of a browser. So a failed sync is not an error state: it leaves every
// existing registration exactly as it was, records why, and waits for the
// next trigger (a 30-minute alarm, browser startup, install, or the reader
// pressing the button in the options page). The registration outlives the
// failure, so a reader whose app is closed keeps the panel on the sites they
// have already granted.
//
// One thing is deliberately *not* automatic: the host permission. Chrome
// requires `permissions.request` to come from a user gesture, and it is right
// to — "this extension may now read every page on a site" is the reader's
// decision, not a pack author's. That is not a human in the data path; it is
// consent for reading a third party's pages, and the options page is where it
// is asked for. Until it is granted the site sits in the status as `pending`,
// visible, with a button.

const SITE_SCRIPT_PREFIX = "kriko-site-";
const SITE_SYNC_KEY = "krikoSiteSync";
const SITE_SYNC_ALARM = "kriko-site-sync";
const SITE_SYNC_PERIOD_MINUTES = 30;

// The same files, in the same order, as `manifest.json`'s two static blocks.
// A dynamic registration is one entry rather than two because order inside
// the array is what matters: `icons.js`, `claim_card.js`, `buyer_card.js` and `run_progress.js` define what
// `hover_lite.js` calls.
const SITE_SCRIPTS = [
  "content.js",
  "hover_lite/icons.js",
  "hover_lite/claim_card.js",
  "hover_lite/buyer_card.js",
  "hover_lite/run_progress.js",
  "hover_lite/hover_lite.js",
];

// An adapter's `site` becomes a host permission and an injection target, so
// it is the one pack-supplied string in this file with teeth. A registrable
// hostname and nothing else: no wildcard, no path, no port, no scheme, no
// credentials. A pack that wants to inject Kriko into a bank by writing
// `site: "*"` gets nothing, and a typo becomes a visibly missing site rather
// than a permission prompt for the whole web.
const HOSTNAME = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/;

function _hostOf(url) {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, "");
  } catch (_) {
    return "";
  }
}

function siteToPattern(site) {
  const host = String(site || "").trim().toLowerCase();
  if (!HOSTNAME.test(host)) return null;
  // `*.example.com` matches the bare host too, in Chrome's dialect — so one
  // pattern covers both `example.com/…` and `www.example.com/…`.
  return `https://*.${host}/*`;
}

// Hosts the packaged manifest already injects on. Read off the manifest at
// runtime rather than repeated here, so trimming a static block cannot leave
// a site silently uncovered by both mechanisms.
function staticSiteHosts() {
  const manifest = extensionApi.runtime.getManifest ? extensionApi.runtime.getManifest() : {};
  const hosts = new Set();
  for (const block of manifest.content_scripts || []) {
    for (const pattern of block.matches || []) {
      const text = String(pattern);
      const tail = text.includes("://") ? text.split("://")[1] : text;
      const host = tail.split("/")[0].replace(/^\*\./, "").toLowerCase();
      if (host) hosts.add(host);
    }
  }
  return hosts;
}

// What the installed packs want, minus what the package already does. Bad
// `site` values are carried as rejects rather than dropped: a pack shipping an
// adapter this worker refuses is worth seeing in the options page, because
// from the reader's side it looks exactly like a site that does not work.
function wantedSites(rows) {
  const isStatic = staticSiteHosts();
  const wanted = new Map();
  for (const adapter of rows || []) {
    const host = String(adapter && adapter.site || "").trim().toLowerCase();
    if (!host || isStatic.has(host)) continue;
    const pattern = siteToPattern(host);
    if (!wanted.has(host)) {
      wanted.set(host, { site: host, pattern, id: SITE_SCRIPT_PREFIX + host });
    }
  }
  return [...wanted.values()];
}

async function _granted(pattern) {
  if (!extensionApi.permissions || !extensionApi.permissions.contains) return false;
  try {
    return await extensionApi.permissions.contains({ origins: [pattern] });
  } catch (_) {
    return false;
  }
}

async function _registeredSiteScripts() {
  if (!extensionApi.scripting || !extensionApi.scripting.getRegisteredContentScripts) return [];
  try {
    const all = await extensionApi.scripting.getRegisteredContentScripts();
    return (all || []).filter((s) => String(s.id).startsWith(SITE_SCRIPT_PREFIX));
  } catch (_) {
    return [];
  }
}

async function _writeSiteStatus(record) {
  try {
    await extensionApi.storage.local.set({ [SITE_SYNC_KEY]: record });
  } catch (_) {
    // A status nobody can read is not a reason to undo a registration.
  }
}

async function readSiteStatus() {
  try {
    const stored = await extensionApi.storage.local.get([SITE_SYNC_KEY]);
    return stored[SITE_SYNC_KEY] || null;
  } catch (_) {
    return null;
  }
}

// The reconciliation. Returns the status it wrote, so the options page can
// use the answer to its own request rather than reading storage back.
async function syncSites({ fresh = false } = {}) {
  if (fresh) adaptersCache = null;

  let rows;
  try {
    rows = await fetchAdapters();
  } catch (error) {
    // The app is closed. Every existing registration stays exactly as it is —
    // the reader keeps the panel on sites they already granted — and the
    // previous list stays visible so the options page shows what it knows
    // rather than an empty one.
    const previous = await readSiteStatus();
    const record = {
      at: Date.now(),
      sites: (previous && previous.sites) || [],
      error: error.message,
      code: error.code || "",
      // Whether the app answered at all: a sync that registered nothing
      // because the app was closed and one that registered nothing because
      // there was nothing to register look alike without it.
      reached: false,
    };
    await _writeSiteStatus(record);
    await _syncAnySite();     // needs no app: the grant is the browser's
    return record;
  }

  const wanted = wantedSites(rows);
  const sites = [];
  const keep = new Set();

  for (const entry of wanted) {
    if (!entry.pattern) {
      sites.push({ site: entry.site, state: "refused",
                   detail: "not a hostname the extension will inject on" });
      continue;
    }
    if (!(await _granted(entry.pattern))) {
      sites.push({ site: entry.site, pattern: entry.pattern, state: "pending" });
      continue;
    }
    keep.add(entry.id);
    sites.push({ site: entry.site, pattern: entry.pattern, state: "active",
                 id: entry.id });
  }

  const existing = await _registeredSiteScripts();
  const byId = new Map(existing.map((s) => [s.id, s]));

  // Drop first, then add. A registration whose site is gone (the pack was
  // uninstalled, or its permission revoked) must not survive, and an id that
  // exists cannot be registered over — `registerContentScripts` rejects the
  // whole call on a duplicate, which would take the new sites down with it.
  const stale = existing.map((s) => s.id).filter((id) => !keep.has(id));
  if (stale.length && extensionApi.scripting.unregisterContentScripts) {
    try {
      await extensionApi.scripting.unregisterContentScripts({ ids: stale });
    } catch (_) {
      // Already gone, or never there. Either way the desired end state is
      // what the next block establishes.
    }
  }

  const missing = [...keep].filter((id) => !byId.has(id));
  const failures = [];
  for (const entry of wanted) {
    if (!missing.includes(entry.id)) continue;
    try {
      await extensionApi.scripting.registerContentScripts([{
        id: entry.id,
        matches: [entry.pattern],
        js: SITE_SCRIPTS,
        runAt: "document_idle",
        allFrames: false,
        persistAcrossSessions: true,
      }]);
    } catch (error) {
      // One at a time, and one failure does not cost the others: a site
      // Chrome refuses is one line in the status, not a dead sync.
      failures.push(`${entry.site}: ${error.message}`);
      for (const row of sites) {
        if (row.site === entry.site) {
          row.state = "refused";
          row.detail = error.message;
        }
      }
    }
  }

  const record = {
    at: Date.now(),
    sites,
    error: failures.length ? failures.join("; ") : "",
    code: "",
    reached: true,
  };
  await _writeSiteStatus(record);
  await _reportActivation(sites);
  await _syncAnySite();
  return record;
}

// The every-site registration (B149), reconciled like the others. It skips
// every host something else already injects on — the manifest's and each
// `kriko-site-` registration's — so no page ever runs the panel twice.
async function _syncAnySite() {
  if (!extensionApi.scripting || !extensionApi.scripting.getRegisteredContentScripts) return;
  const granted = await _granted(EVERY_SITE);
  everySiteGranted = granted;
  let all = [];
  try {
    all = (await extensionApi.scripting.getRegisteredContentScripts()) || [];
  } catch (_) {
    return;
  }
  const current = all.find((s) => s.id === ANY_SITE_SCRIPT_ID);
  const exclude = [
    ...[...staticSiteHosts()].map((host) => `https://*.${host}/*`),
    ...all.filter((s) => String(s.id).startsWith(SITE_SCRIPT_PREFIX))
      .flatMap((s) => s.matches || []),
  ].sort();
  const same = current
    && JSON.stringify([...(current.excludeMatches || [])].sort()) === JSON.stringify(exclude);
  if (current && (!granted || !same)) {
    try {
      await extensionApi.scripting.unregisterContentScripts({ ids: [ANY_SITE_SCRIPT_ID] });
    } catch (_) {
      // Already gone.
    }
  }
  if (!granted || same) return;
  try {
    await extensionApi.scripting.registerContentScripts([{
      id: ANY_SITE_SCRIPT_ID,
      matches: [EVERY_SITE],
      excludeMatches: exclude,
      js: SITE_SCRIPTS,
      runAt: "document_idle",
      allFrames: false,
      persistAcrossSessions: true,
    }]);
  } catch (_) {
    // The next sync tries again; the toolbar button works without it.
  }
}

// Tell the app what the browser made of its sites.
//
// The app can see that an adapter exists. Only this worker can see whether
// Chrome ever granted the host permission that turns one into an injected
// content script, and until it said so the Sites screen showed "readable" for
// a site the panel would never appear on. The reader registered a site, was
// told Kriko recognised it, reloaded, and nothing happened — with the screen
// insisting nothing was wrong.
//
// Best effort, and silent on failure: the app being closed is the ordinary
// state of a browser, and a status nobody could deliver is not a reason to
// undo a registration that succeeded.
async function _reportActivation(sites) {
  try {
    await _fetchApp(`${await apiBase()}/api/sites/activation`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        sites: sites.map((one) => ({
          site: one.site,
          state: one.state || "",
          detail: one.detail || "",
          pattern: one.pattern || "",
        })),
      }),
    });
  } catch (_) {
    // The app is not running. It will ask again on its next sync.
  }
}

// Four triggers, one function, because the sync is convergent — none of these
// needs to know what the others did.
//
// The alarm is the one that matters: the app is started and stopped
// independently of the browser, so the first sync after install almost always
// fails, and something has to try again without the reader doing anything.
extensionApi.runtime.onInstalled.addListener((details) => {
  void syncThenGuide((details && details.reason) || "install");
  void refreshConnectionIcon();
});
if (extensionApi.runtime.onStartup) {
  extensionApi.runtime.onStartup.addListener(() => {
    void syncThenGuide("startup");
    void refreshConnectionIcon();
  });
}

// ── the options page, opened once, at the step that is missing (#260) ───
//
// The reader's words: "automatically open kriko option in settings". The two
// things only that page can settle are the host permission for a site a pack
// reads (Chrome takes it from a gesture inside the extension, so nothing here
// can grant it) and the address of an app that has never answered. Until now
// both waited to be found in the browser's extension manager.
//
// The rules that keep this from becoming a nag, each one a thing the reader
// said they did not want:
//   * once per step, ever: what was opened for is remembered, and a step is
//     forgotten only when it is done (a granted site, an app that answered),
//     so a reader who closes the page is not shown it again;
//   * never on every browser start: a start that finds the same pending sites
//     finds them already remembered;
//   * at most once in a browser session, so two steps at once open one tab;
//   * an update never opens it for what was already pending: the first run
//     after an upgrade only learns what is pending, so a reader who said no
//     last month is not asked again by a version bump.
// The page learns which step to put in front of the reader from
// `krikoOptionsFocus`, because `openOptionsPage` takes no address.

const OPTIONS_MEMORY_KEY = "krikoOptionsMemory";
const OPTIONS_FOCUS_KEY = "krikoOptionsFocus";
const OPTIONS_SESSION_KEY = "krikoOptionsOpenedThisSession";
const OPTIONS_OPENING_REASONS = new Set(["install", "startup", "alarm"]);

// Pure. `record` is the site sync's status, `memory` what was remembered (or
// null on a first run), `reason` what woke the worker. Answers which step, if
// any, deserves the reader's attention now, and the memory to keep.
function planOptionsOpen(record, memory, reason) {
  const known = Boolean(memory && typeof memory === "object");
  const kept = {
    appSeen: known && Boolean(memory.appSeen),
    address: known && Boolean(memory.address),
    sites: known && Array.isArray(memory.sites) ? [...memory.sites] : [],
  };
  // The first run with no memory only learns, except an install: an empty
  // memory is exactly what a fresh install has.
  const learning = !known && reason !== "install";
  const mayOpen = OPTIONS_OPENING_REASONS.has(reason) && !learning;

  if (!record || !record.reached) {
    if (learning) kept.address = true;
    const step = mayOpen && !kept.appSeen && !kept.address ? "address" : null;
    return { step, patterns: [], memory: step ? { ...kept, address: true } : kept };
  }

  const pending = (record.sites || [])
    .filter((row) => row.state === "pending" && row.pattern)
    .map((row) => row.pattern);
  kept.appSeen = true;
  // A step that is done is forgotten, so the next time it is missing it is a
  // new step and may be shown once more.
  kept.sites = kept.sites.filter((pattern) => pending.includes(pattern));
  if (learning) return { step: null, patterns: [], memory: { ...kept, sites: pending } };
  const fresh = pending.filter((pattern) => !kept.sites.includes(pattern));
  if (mayOpen && fresh.length) {
    return {
      step: "sites", patterns: fresh,
      memory: { ...kept, sites: [...kept.sites, ...fresh] },
    };
  }
  return { step: null, patterns: [], memory: kept };
}

async function _sessionOptionsOpened() {
  try {
    const got = await extensionApi.storage.session.get(OPTIONS_SESSION_KEY);
    return Boolean(got && got[OPTIONS_SESSION_KEY]);
  } catch (_) {
    return false;
  }
}

async function guideToOptions(record, reason) {
  if (!record || !extensionApi.runtime.openOptionsPage) return null;
  let memory = null;
  try {
    const got = await extensionApi.storage.local.get(OPTIONS_MEMORY_KEY);
    memory = (got && got[OPTIONS_MEMORY_KEY]) || null;
  } catch (_) {
    return null;     // no way to remember means no way to promise "once"
  }
  const plan = planOptionsOpen(record, memory, reason);
  // The session cap: a step skipped for it is not marked as shown, so it
  // still gets its one turn in a later session.
  const capped = Boolean(plan.step) && await _sessionOptionsOpened();
  const opening = capped ? null : plan.step;
  const next = capped
    ? planOptionsOpen(record, memory || {}, "permission").memory
    : plan.memory;
  try {
    await extensionApi.storage.local.set({ [OPTIONS_MEMORY_KEY]: next });
    if (opening) {
      await extensionApi.storage.local.set({ [OPTIONS_FOCUS_KEY]: opening });
      try {
        await extensionApi.storage.session.set({ [OPTIONS_SESSION_KEY]: Date.now() });
      } catch (_) { /* no session storage: the memory above still says once */ }
      extensionApi.runtime.openOptionsPage();
    }
  } catch (_) {
    return null;
  }
  return opening;
}

async function syncThenGuide(reason) {
  const record = await syncSites({ fresh: true });
  await guideToOptions(record, reason);
  return record;
}
/* An alarm is Chrome's, and this block runs again on every worker start.
 *
 * That combination was a bug with no symptom of its own. `alarms.create` with
 * the name of an existing alarm *replaces* it, and a replacement starts its
 * clock again — so an alarm recreated at every top-level run is an alarm whose
 * countdown restarts every time the worker wakes. An MV3 worker is stopped
 * after about thirty seconds idle and started again by the next message, the
 * next storage change, the next alarm; on any browser in ordinary use that
 * happens more often than once in thirty minutes, so the 30-minute site sync
 * never came due and a reader whose sync had failed waited for a retry that
 * never arrived. The connection icon, on a one-minute period, was one restart
 * away from the same fate.
 *
 * So: create only what is missing and leave a live alarm's clock alone. The
 * question is asked of Chrome rather than of a variable here, because a
 * variable is exactly what a restart loses. */
function _ensureAlarm(name, info) {
  const alarms = extensionApi.alarms;
  if (!alarms || !alarms.create) return;
  let made = false;
  const make = () => {
    if (made) return;
    made = true;
    try {
      alarms.create(name, info);
    } catch (_) {
      // Nothing to do: the next worker start asks again.
    }
  };
  if (!alarms.get) {
    // No way to ask, so creating is the only move. Old enough to be rare.
    make();
    return;
  }
  try {
    const asked = alarms.get(name, (existing) => {
      void extensionApi.runtime.lastError;
      if (!existing) make();
    });
    // Firefox answers the promise and may ignore the callback; `made` keeps
    // the two paths from creating the alarm twice.
    if (asked && typeof asked.then === "function") {
      asked.then((existing) => { if (!existing) make(); }).catch(() => {});
    }
  } catch (_) {
    make();
  }
}

if (extensionApi.alarms) {
  _ensureAlarm(SITE_SYNC_ALARM, {
    periodInMinutes: SITE_SYNC_PERIOD_MINUTES,
    delayInMinutes: 1,
  });
  _ensureAlarm(CONNECTION_ALARM, {
    periodInMinutes: CONNECTION_PERIOD_MINUTES,
    delayInMinutes: 1,
  });
  _ensureAlarm(PRICE_ALARM, {
    periodInMinutes: PRICE_PERIOD_MINUTES,
    delayInMinutes: 2,
  });
  extensionApi.alarms.onAlarm.addListener((alarm) => {
    if (alarm && alarm.name === SITE_SYNC_ALARM) void syncThenGuide("alarm");
    if (alarm && alarm.name === CONNECTION_ALARM) void refreshConnectionIcon();
    if (alarm && alarm.name === PRICE_ALARM) void checkBuyerAlerts();
  });
}
// A price notification opens the page it is about and marks the alert read.
// `notifications` is an optional permission, asked for on the options page when
// the reader turns it on: a required one would have Chrome switch the extension
// off at the next update until they approved it. Without it a drop still shows
// as a mark on the toolbar button and a card in the panel.
let _notificationsWired = false;
function wireNotifications() {
  if (_notificationsWired || !extensionApi.notifications || !extensionApi.notifications.onClicked) return;
  _notificationsWired = true;
  extensionApi.notifications.onClicked.addListener(async (id) => {
    try {
      if (String(id).startsWith("kriko-alert:")) {
        const alertId = String(id).slice("kriko-alert:".length);
        const { items } = await _getApp("/api/prices/alerts");
        const one = (items || []).find((row) => row.alert_id === alertId);
        if (one && /^https?:/i.test(one.url)) await extensionApi.tabs.create({ url: one.url });
        await _postApp("/api/prices/alerts/read", { ids: [alertId] });
      }
      extensionApi.notifications.clear(id);
    } catch (_) {
      // The app is not running; the alert is still there next time.
    }
  });
}
wireNotifications();
// A grant is the event the pending list was waiting for, and a revocation has
// to take the injection with it — an extension still running on a site the
// reader took back is the worst failure available here.
if (extensionApi.permissions && extensionApi.permissions.onAdded) {
  // `permission` never opens the page: the reader is the one who just moved,
  // and it only lets the memory forget a step that is now done.
  extensionApi.permissions.onAdded.addListener(() => { wireNotifications(); void syncThenGuide("permission"); });
  extensionApi.permissions.onRemoved.addListener(() => { void syncThenGuide("permission"); });
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
function toViewModel(payload, appBase) {
  const claims = Array.isArray(payload.claims) ? payload.claims : [];
  return {
    adapter: payload.adapter,
    identity: payload.identity || {},
    context: payload.context || {},
    coverage: payload.coverage,
    method: payload.method,
    flags: payload.flags || [],
    unmapped_labels: payload.unmapped_labels || [],
    // How sure the engine is that this page *is* this product, and what it
    // weighed to decide. Carried since 0.10.0 because the panel had exactly
    // two states — a match, or a blank — for four different situations, and
    // the reader who met the blank had a good pack installed for that exact
    // product with no way to find out which had happened.
    //
    // `next_step` is the engine's own sentence and action word, not a status
    // code for the panel to write copy from: a client writing its own copy
    // stops agreeing with the engine the first time a method is added.
    verdict: payload.verdict || "",
    score: typeof payload.score === "number" ? payload.score : null,
    considered: Array.isArray(payload.considered) ? payload.considered : [],
    next_step: payload.next_step || null,
    // Which packs answered, and the units their context values are in. Both
    // are sent by /api/analyze and both were dropped here, silently: the
    // footer printed "unknown" on every result since the byline was added,
    // and every context fact rendered without its unit. Neither had a test,
    // because a test for this shape would have been written against this
    // function rather than against the payload it is supposed to carry.
    packs: Array.isArray(payload.packs) ? payload.packs : [],
    context_units: payload.context_units || {},
    // The app stores every analysis and already renders one at this route, so
    // "see the whole thing" needs no new endpoint — only the id it handed back.
    //
    // Two forms of the same destination, and both are needed. `app_route` is
    // what gets posted to `/api/focus`, which raises the *desktop window* —
    // the thing the reader means by "open in Kriko". `app_url` is the
    // fallback for when no shell is listening (someone running the server in
    // a terminal), and opening a browser tab is then the honest best effort.
    // Sending the reader to a second browser tab while their app sits behind
    // the window was the bug; keeping the tab as a fallback is not.
    // Which saved answer this is, so the panel can ask for it again when the
    // knowledge under it moves (B152.4).
    lookup_id: payload.lookup_id || "",
    app_route: payload.lookup_id ? `result/${payload.lookup_id}` : undefined,
    app_url: payload.lookup_id && appBase
      ? `${appBase}/#/result/${payload.lookup_id}`
      : undefined,
    // The two things a reader does next, once they have decided this listing
    // is worth pursuing: take questions to the seller, and hold it against
    // the others they are considering. Both were app-only, which meant the
    // panel could inform a decision and then had nowhere to send it.
    //
    // Built here beside `app_route` rather than in the panel because a route
    // is part of the app contract — the app's own screens accept an id as a
    // path segment precisely so this handoff needs no query string, which the
    // focus endpoint deliberately refuses.
    app_routes: payload.lookup_id
      ? {
          result: `result/${payload.lookup_id}`,
          questions: `questions/${payload.lookup_id}`,
          // Compare's own empty state already says "needs two saved checks",
          // so offering the button before there are two is a button that
          // opens straight into that dead end (extension-16).
          ...(payload.compare_ready ? { compare: `compare/${payload.lookup_id}` } : {}),
        }
      : undefined,
    // Same, as browser URLs, for the same reason `app_url` exists: when no
    // desktop shell is listening there is nothing to raise, and a tab is the
    // honest best effort rather than a button that does nothing.
    app_urls: payload.lookup_id && appBase
      ? {
          result: `${appBase}/#/result/${payload.lookup_id}`,
          questions: `${appBase}/#/questions?id=${payload.lookup_id}`,
          ...(payload.compare_ready
            ? { compare: `${appBase}/#/compare?left=${payload.lookup_id}` }
            : {}),
        }
      : undefined,
    // Subjects the listing resolved to, claims or not. The rows with zero
    // claims are the interesting ones: the packs recognise this car and have
    // nothing to say about it, which is a gap the panel can offer to fill
    // rather than an emptiness it has to apologise for.
    subjects: Array.isArray(payload.subjects) ? payload.subjects : [],
    claims: claims.map((claim) => {
      const strength = _strengthOf(claim);
      return {
        // Identity, so a card can be pointed at rather than only described:
        // marking a claim wrong, or asking for it again, both need this.
        claim_id: claim.claim_id,
        subject_id: claim.subject_id,
        title: claim.title,
        body: claim.body,
        advice: claim.advice,
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
//
// The adapters' own identity — pack_id and version, already fetched to find
// this adapter — goes in alongside the scrape (extension-3, B145 audit): a
// pack update ships new claims for the same listing, and a signature built
// from the scrape alone can't see that anything changed, so the 6-hour local
// cache kept serving the pre-update answer regardless.
function _scrapeSignature(scrape, adapters) {
  return _stableHash({
    // Invalidate answers cached before sold-product/host scope was enforced.
    productScope: 1,
    // Do not keep answers from before complete field reads and label priority.
    readingRevision: 2,
    product: scrape?.product || {},
    title: scrape?.title || "",
    fields: scrape?.fields || {},
    packs: (adapters || []).map((a) => `${a.pack_id}@${a.version || ""}`).sort(),
  });
}

/* The local cache is keyed by a digest of the page's address, not by the
 * address.
 *
 * A storage key is a durable record of the reader's browsing like any other,
 * and this one used to be the listing's full URL in plain text: every page
 * Kriko had been asked about, spelled out, sitting in the extension's own
 * storage until something happened to read it again. Kriko's premise is that
 * what somebody is shopping for is nobody else's business, and that has to
 * hold for the file it writes on their machine as much as for the wire. The
 * digest matches an entry to its page exactly as the address did; it just
 * cannot be read off the disk as a history.
 *
 * `_digest` is the same one the research intents are keyed by, so the two
 * cannot drift into two ideas of what a stable key is. */
async function _localCacheKey(url) {
  return LOCAL_CACHE_KEY_PREFIX + await _digest(String(url));
}

function _isFreshCachedEntry(entry, signature) {
  if (!entry || entry.ok !== true || !entry.result) return false;
  if (entry.signature !== signature) return false;
  const ageMs = Date.now() - Number(entry.fetchedAt || 0);
  return ageMs >= 0 && ageMs <= RESULT_CACHE_TTL_MS;
}

async function _readCachedAnalysis(url, signature) {
  const cacheKey = await _localCacheKey(url);
  const data = await extensionApi.storage.local.get(cacheKey);
  const entry = data[cacheKey];
  if (_isFreshCachedEntry(entry, signature)) return entry;
  if (entry) {
    try {
      await extensionApi.storage.local.remove(cacheKey);
    } catch (error) {
      console.warn("[kriko] local result cache cleanup failed", error?.message || error);
    }
  }
  return null;
}

async function _writeCachedAnalysis(url, entry) {
  if (!entry || entry.ok !== true) return;
  try {
    await extensionApi.storage.local.set({ [await _localCacheKey(url)]: entry });
  } catch (error) {
    console.warn("[kriko] local result cache write failed", error?.message || error);
  }
}

async function _updateBadgeForResult(result, tabId) {
  const claims = Array.isArray(result?.claims) ? result.claims : [];
  const highCount = claims.filter((r) => r.severity === "high").length;

  let badgeText = "";
  let badgeColor = "#2d7b41"; // low green
  if (highCount > 0) {
    badgeText = String(highCount);
    badgeColor = "#b5392f"; // high red
  } else if (claims.length > 0) {
    badgeText = String(claims.length);
    badgeColor = "#a3641a"; // medium orange
  }

  await extensionApi.action.setBadgeText({ text: badgeText, tabId });
  await extensionApi.action.setBadgeBackgroundColor({ color: badgeColor, tabId });
}

// ── scraping ────────────────────────────────────────────────────────────

async function _requestScrape(tabId, labels, panel, explore = false) {
  // `panel` is the adapter's `local_panel` block: the words, selectors and
  // rules the content script needs to read the damage and equipment blocks.
  // It travels per-request rather than being cached in the content script,
  // because the adapter list is refreshed here and a scrape reading last
  // week's rules would be invisible.
  // `explore` asks for the page's own label/value shapes as well, which is
  // what a site nothing can read yet has to offer.
  const ask = { type: "GET_SCRAPE", labels, panel, explore };
  try {
    const reply = await extensionApi.tabs.sendMessage(tabId, ask);
    if (reply && reply.ok) return reply;
  } catch (_) {
    // Content script not responding — inject it below.
  }

  try {
    await extensionApi.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
  } catch (_) {
    return null;   // chrome:// or otherwise restricted
  }

  await new Promise((resolve) => setTimeout(resolve, 300));
  try {
    return await extensionApi.tabs.sendMessage(tabId, ask);
  } catch (_) {
    return null;
  }
}

async function requestAnalysis(scrape, timings = {}) {
  const endpoint = `${await apiBase()}/api/analyze`;
  const startedAt = _now();
  const response = await _fetchApp(endpoint, {
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
      // The product's own name (B149): what a page on a site no adapter
      // covers is recognised by, and what the panel offers to research.
      product_name: String((scrape.product && scrape.product.name) || "").slice(0, 300),
      // Which door this came in by. The app's history shows it, so a reader
      // can tell an answer their browser produced from one they asked for.
      origin: "extension",
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

async function runAnalysisForTab(tabId, url, { fresh = false, auto = false } = {}) {
  const storageKey = STORAGE_KEY_PREFIX + url;
  // A press of Refresh while another run for this same URL is already in
  // flight still waits for that run rather than starting a second one —
  // `fresh` only means "don't hand back what's already stored", not "don't
  // share an in-flight request".
  const existingRun = inFlightByStorageKey.get(storageKey);
  if (existingRun && !fresh) {
    const result = await existingRun;
    await _updateBadgeForResult(result, tabId);
    return result;
  }

  const runPromise = _runAnalysisForTab(tabId, url, storageKey, { fresh, auto });
  inFlightByStorageKey.set(storageKey, runPromise);
  try {
    return await runPromise;
  } finally {
    if (inFlightByStorageKey.get(storageKey) === runPromise) {
      inFlightByStorageKey.delete(storageKey);
    }
  }
}

// B150: "figure it out which more information agents needs by its own from
// the product page — i may not know which engine code is this". The page's own
// labelled facts are kept per listing so "Research this product" can send
// them; the agent settles the exact version from them instead of asking.
// Trimmed here as well as on the server: session storage is small.
const PAGE_FACTS_PREFIX = "krikoFacts:";
const PAGE_FACTS_MAX = 40;

async function _keepPageFacts(url, scrape) {
  try {
    const facts = {};
    for (const [label, value] of Object.entries((scrape && scrape.fields) || {})) {
      if (Object.keys(facts).length >= PAGE_FACTS_MAX) break;
      const k = String(label || "").slice(0, 80);
      const v = String(value == null ? "" : value).slice(0, 200);
      if (k && v) facts[k] = v;
    }
    const description = String((scrape && scrape.description) || "").slice(0, 1500);
    await extensionApi.storage.session.set({ [PAGE_FACTS_PREFIX + url]: { facts, description } });
  } catch (_) {
    // A listing whose facts could not be kept still gets researched by name.
  }
}

async function _pageFacts(url) {
  try {
    const key = PAGE_FACTS_PREFIX + url;
    const got = await extensionApi.storage.session.get(key);
    return (got && got[key]) || null;
  } catch (_) {
    return null;
  }
}

// What makes a page on an unread site worth offering to learn: the page says it
// is a product (schema.org, or a product heading with a price beside it), or it
// prints several label/value pairs, which is what a listing's specification is.
const LEARNABLE_MIN_FIELDS = 4;

function _looksLearnable(scrape) {
  if (!scrape || typeof scrape !== "object") return false;
  const product = scrape.product || {};
  if (product.name && product.typed) return true;
  const labels = Object.keys(scrape.fields || {}).filter((key) => !key.startsWith("ld:"));
  return Boolean(product.name) && labels.length >= LEARNABLE_MIN_FIELDS;
}

// Bring the panel up on a page Kriko already reads, once per site per browser
// session. The reader's report: "the web extension pops up in every page, not
// only learned hosts." It used to open by itself on a page worth *learning*,
// on a site nothing read — so every shop with a labelled product page put a
// panel over it, while the sites Kriko does read stayed quiet. It is the other
// way round now: a site Kriko knows opens its own answer; an unknown site is
// opened from the toolbar (every site is registered for exactly that), where
// the Learn card is waiting.
const SHOWN_KEY = "kriko_panel_shown";

async function _nudgePanel(tabId, url) {
  const host = _hostOf(url);
  if (!tabId || !host) return;
  try {
    const got = await extensionApi.storage.session.get(SHOWN_KEY);
    const seen = new Set((got && got[SHOWN_KEY]) || []);
    if (seen.has(host)) return;
    seen.add(host);
    await extensionApi.storage.session.set({ [SHOWN_KEY]: [...seen].slice(-200) });
    await extensionApi.tabs.sendMessage(tabId, { type: "KRIKO_SHOW_PANEL" });
  } catch (_) {
    // No panel script on this tab, or no session storage: the toolbar button
    // still opens the same panel.
  }
}

async function _runAnalysisForTab(tabId, url, storageKey, { fresh = false, auto = false } = {}) {
  const timings = {};
  const totalStartedAt = _now();
  const runId = nextRunId++;
  latestRunIdByStorageKey.set(storageKey, runId);
  // Hoisted so the catch block can attach it: the listing header and the
  // damage panel come from the scrape, not from the analysis, so they should
  // still render when the analysis itself fails.
  let scrape = null;
  // Whether an installed pack reads this host at all. Hoisted for the same
  // reason: whether the panel may open by itself is decided in the catch too.
  let hostRead = false;

  try {
    await _stage(url, "adapters", "");
    const adapters = await fetchAdapters();
    const adapter = adapterFor(url, adapters);
    hostRead = Boolean(adapter) || hostHasAnyAdapter(url, adapters);
    // Not an error the reader can act on — most pages are not listings —
    // but not something to answer with an empty result either, which would
    // read as "nothing is known about this car". Coded so the panel can
    // fall quiet instead of showing a red banner on every ordinary page.
    const noAdapter = () => {
      const quiet = new Error("No installed pack can read this page.");
      quiet.code = "NO_ADAPTER";
      quiet.hostKnown = hostHasAnyAdapter(url, adapters);
      // A page worth offering to learn: on a site nothing reads, and either
      // publishing a product of its own or showing enough label/value pairs
      // to be one. Most of the web is neither, and is left alone.
      quiet.learnable = !quiet.hostKnown && _looksLearnable(scrape);
      return quiet;
    };

    // Named after the pack that will read it, not after the mechanism: the
    // reader knows which site they are on, and "reading this page" is the
    // step they can see happening in front of them.
    await _stage(url, "reading", (adapter && adapter.pack_id) || "");
    const scrapeStartedAt = _now();
    // No site adapter is no longer the end (B149): every page is read for
    // the product it publishes, and the app decides whether a pack knows it.
    //
    // `explore` rides along exactly when nothing installed claims this page.
    // That is the one case where the page's own label/value shapes are the
    // whole evidence: a model is asked to work out which of them mean what
    // (`app/siteinfer.py`), and it can only map what it is shown. A page an
    // adapter claims keeps the scrape it always had — its labels are the
    // pack's, already asked for, and the explore scan would put every other
    // short string on the page on the wire for nothing.
    const reply = await _requestScrape(
      tabId, (adapter && adapter.labels) || [], (adapter && adapter.local_panel) || {},
      !adapter
    );
    timings.scrape_ms = _elapsed(scrapeStartedAt);
    if (!reply || !reply.ok) {
      if (!adapter) throw noAdapter();
      // A site Kriko has an adapter for, and a page it cannot read: the adapter
      // is out of date for it, or the page is not what it was written for. That
      // is exactly what Learn this page is for, so it is offered, with the
      // reason the page gave instead of a bare sentence.
      const failed = new Error(
        "Kriko could not read this page" + (reply && reply.error ? ` (${reply.error})` : "."));
      failed.code = "SCRAPE_FAILED";
      failed.learnable = true;
      throw failed;
    }
    scrape = reply.payload;
    await _keepPageFacts(url, scrape);
    if (!adapter) {
      const product = scrape.product || {};
      // A page load on a site nobody reads is quiet unless the page itself
      // says it is a product; the reader pressing the button is asking, so
      // a named page is worth asking about.
      if (!product.name || (auto && !product.typed)) throw noAdapter();
    }
    // The page is a product: remember its price and judge the listing, beside
    // the analysis and not behind it.
    void _noteBuyer(url, scrape);
    if (auto) void nudgeDue(tabId);

    const signature = _scrapeSignature(scrape, adapters);
    // extension-3 (B145 audit): "Refresh analysis" re-asked nothing — every
    // press with the same scrape and packs served the 6-hour cache entry, so
    // there was no way to re-ask the engine short of waiting it out. `fresh`
    // is the one bit that says "no, actually ask", and it skips only the
    // cache read; the write below still happens, so the new answer becomes
    // the cache for the *next*, non-fresh, request.
    const cachedEntry = fresh ? null : await _readCachedAnalysis(url, signature);
    if (cachedEntry) {
      // Worth saying. An answer that arrives in 30 ms looks like nothing
      // happened, and a reader who pressed Refresh wants to know whether
      // they got a fresh answer or the one they already had.
      await _stage(url, "cached", "");
      await extensionApi.storage.session.set({ [storageKey]: cachedEntry });
      await _updateBadgeForResult(cachedEntry.result, tabId);
      if (auto && hostRead) await _nudgePanel(tabId, url);
      return cachedEntry.result;
    }

    await _stage(url, "asking", "");
    const raw = await requestAnalysis(scrape, timings);
    if (raw && raw.readable === false) {
      if (raw.reason === "unknown_product") {
        const unknown = new Error("Kriko doesn't know this product yet.");
        unknown.code = "UNKNOWN_PRODUCT";
        unknown.productName = (raw.product && raw.product.name) || "";
        // A product the packs do not hold, on a site nothing reads: learning
        // the site is what lets the next page of it be read at all.
        unknown.learnable = !adapter && !hostHasAnyAdapter(url, adapters);
        throw unknown;
      }
      if (!adapter) throw noAdapter();
    }
    const result = toViewModel(raw, await apiBase());

    if (latestRunIdByStorageKey.get(storageKey) !== runId) {
      return result;    // a newer run has already answered for this listing
    }

    const entry = {
      ok: true,
      result,
      // extension-8/extension-11 (B145 audit): the scrape's own title
      // (content.js reads it straight off the page, `scrape.title`) never
      // reached the panel's `listing` object, which is why the header fell
      // back to joining raw identity values or, with the engine down, to
      // "Untitled listing" — the page's own h1 was sitting right there in
      // the same scrape.
      listing: { ...(scrape.listing || {}), title: scrape.title || "" },
      signature,
      fetchedAt: Date.now(),
    };

    // The terminal stage, written before the result so the panel never sees
    // an answer while the narration still claims to be asking for it.
    await _stage(url, "done",
      String(Array.isArray(result.claims) ? result.claims.length : 0));
    await extensionApi.storage.session.set({ [storageKey]: entry });
    await _writeCachedAnalysis(url, entry);
    await _updateBadgeForResult(result, tabId);
    if (auto && hostRead) await _nudgePanel(tabId, url);
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
    await _stage(url, "failed", error.message || "");
    if (error.code) errEntry.code = error.code;
    if (error.hostKnown) errEntry.hostKnown = true;
    if (error.learnable) errEntry.learnable = true;
    if (error.productName) errEntry.productName = error.productName;
    if (scrape) errEntry.listing = { ...(scrape.listing || {}), title: scrape.title || "" };
    await extensionApi.storage.session.set({ [storageKey]: errEntry });
    // NO_ADAPTER is not a failure — it's most pages on the internet, which is
    // exactly why the badge used to paint a red "!" on every non-listing page
    // of the one site Kriko *does* read (extension-5, B145 audit). A page
    // this extension was never going to have an opinion on gets no badge.
    if (error.code === "NO_ADAPTER") {
      await extensionApi.action.setBadgeText({ text: "", tabId });
      // Nothing opens by itself on a site Kriko does not read. The toolbar
      // opens the panel there, and the Learn card is on it.
    } else if (error.code === "SCRAPE_FAILED") {
      // This page, not Kriko, is what went wrong, and the panel offers the
      // way out. A red "!" would say the extension is broken.
      await extensionApi.action.setBadgeText({ text: "?", tabId });
      await extensionApi.action.setBadgeBackgroundColor({ color: "#5b6472", tabId });
    } else if (error.code === "UNKNOWN_PRODUCT") {
      // Not a failure either: a product nothing installed covers yet, one
      // click from being researched. A question, not an alarm.
      await extensionApi.action.setBadgeText({ text: "?", tabId });
      await extensionApi.action.setBadgeBackgroundColor({ color: "#5b6472", tabId });
      if (auto && hostRead) await _nudgePanel(tabId, url);
    } else {
      await extensionApi.action.setBadgeText({ text: "!", tabId });
      await extensionApi.action.setBadgeBackgroundColor({ color: "#b5392f", tabId });
    }
    throw error;
  }
}


// ── the reader as a buyer ───────────────────────────────────────────────
//
// Price memory, the audit of a listing, how it fits what the reader said they
// need, and whether they already watch it. Asked of the app separately from the
// analysis and stored under its own key: the analysis is cached for hours and a
// price verdict, a profile or a watch must not be.

async function _noteBuyer(url, scrape) {
  const key = BUYER_KEY_PREFIX + url;
  try {
    const buyer = await _postApp("/api/buyer/page", {
      url,
      title: scrape.title || "",
      description: scrape.description || "",
      fields: scrape.fields || {},
      product_name: String((scrape.product && scrape.product.name) || "").slice(0, 300),
    });
    await extensionApi.storage.session.set({ [key]: { ok: true, buyer, fetchedAt: Date.now() } });
  } catch (error) {
    // The app is not running or is older than this extension: no card, no noise.
    await extensionApi.storage.session.set({ [key]: { ok: false, error: error.message, fetchedAt: Date.now() } });
  }
}

async function _freshBuyer(url) {
  const got = await extensionApi.storage.session.get(BUYER_KEY_PREFIX + url);
  return got[BUYER_KEY_PREFIX + url] || null;
}

// The look before paying. Only on a page whose address says it is a cart or a
// payment step, and only when the reader has not turned it off.
async function guardCheckout(tabId, url) {
  try {
    // Absent means on: only an explicit "off" from the options page stops it.
    const stored = await extensionApi.storage.local.get("buyerGuard");
    if (stored.buyerGuard === false) return;
    let cart = { items: [], text: "" };
    try {
      const reply = await extensionApi.tabs.sendMessage(tabId, { type: "GET_CART" });
      if (reply && reply.ok) cart = reply;
    } catch (_) {
      // No content script here: the engine falls back to what the reader viewed.
    }
    const result = await _postApp("/api/prices/checkout", {
      url, items: (cart.items || []).slice(0, 12), text: String(cart.text || "").slice(0, 20000),
    });
    await extensionApi.storage.session.set({ [GUARD_KEY_PREFIX + url]: { ok: true, result, fetchedAt: Date.now() } });
    if (result && result.verdict !== "go") {
      await extensionApi.tabs.sendMessage(tabId, { type: "SHOW_GUARD", result }).catch(() => {});
    }
  } catch (error) {
    console.warn("[kriko] checkout look failed", error?.message || error);
  }
}

// "Did it hold up?", put to the reader on a page Kriko reads, which is where they
// are already looking at things to buy. One purchase per page load, and the same
// one at most once a day, so a question is an invitation and not a nag.
async function nudgeDue(tabId) {
  try {
    const bought = await _getApp("/api/buyer/purchases");
    const due = bought.due || [];
    if (!due.length) return;
    const told = (await extensionApi.storage.local.get("krikoNudged")).krikoNudged || {};
    const now = Date.now();
    const one = due.find((row) => now - Number(told[row.purchase_id] || 0) > DUE_NUDGE_QUIET_MS);
    if (!one) return;
    told[one.purchase_id] = now;
    for (const id of Object.keys(told)) if (now - told[id] > 30 * 24 * 60 * 60 * 1000) delete told[id];
    await extensionApi.storage.local.set({ krikoNudged: told });
    await extensionApi.tabs.sendMessage(tabId, { type: "KRIKO_DUE_NUDGE", purchase: one, count: due.length });
  } catch (_) {
    // No app, or no panel on this tab: the question is still there next time.
  }
}

// A price crossed what the reader asked for, or a purchase is due its question.
// Asked on a timer: the app re-reads the pages that are due (it decides which),
// then says what it found.
async function checkBuyerAlerts() {
  try {
    await _postApp("/api/prices/sweep", {}).catch(() => null);
    const [alerts, bought] = await Promise.all([
      _getApp("/api/prices/alerts").catch(() => ({ items: [] })),
      _getApp("/api/buyer/purchases").catch(() => ({ due: [] })),
    ]);
    const items = alerts.items || [];
    const due = bought.due || [];
    const count = items.length + due.length;
    await extensionApi.action.setBadgeText({ text: count ? "↓" : "" });
    if (count) await extensionApi.action.setBadgeBackgroundColor({ color: "#1f4fff" });
    if (!extensionApi.notifications || !extensionApi.notifications.create) return;
    const told = new Set((await extensionApi.storage.local.get("krikoToldAbout")).krikoToldAbout || []);
    for (const one of items) {
      if (told.has(one.alert_id)) continue;
      told.add(one.alert_id);
      const was = one.was_price ? ` (was ${one.was_price})` : "";
      extensionApi.notifications.create(`kriko-alert:${one.alert_id}`, {
        type: "basic", iconUrl: "assets/icons/icon-128.png",
        title: "Price dropped",
        message: `${one.name || "A page you watch"}: ${one.price} ${one.currency || ""}${was}`.trim(),
      });
    }
    for (const one of due) {
      const id = `due:${one.purchase_id}`;
      if (told.has(id)) continue;
      told.add(id);
      extensionApi.notifications.create(`kriko-due:${one.purchase_id}`, {
        type: "basic", iconUrl: "assets/icons/icon-128.png",
        title: "Did it hold up?",
        message: `How is your ${one.name}? Tell Kriko so it can learn what you regret.`,
      });
    }
    await extensionApi.storage.local.set({ krikoToldAbout: [...told].slice(-200) });
  } catch (error) {
    console.warn("[kriko] alert check failed", error?.message || error);
  }
}

/** The answer this listing already has, asked again of the knowledge as it
 * is now (B152.4). The app answers the saved question in place — no new
 * history row — and the entry in session storage is replaced, which is what
 * repaints an open panel (its `storage.onChanged` listener). `null` when the
 * app kept the old answer. */
async function refreshAnswer(tabId, url, lookupId) {
  const row = await _postApp(`/api/lookup/${encodeURIComponent(lookupId)}/refresh`, {});
  if (!row || !row.refreshed || !row.response) return null;
  const result = toViewModel(row.response, await apiBase());
  const storageKey = STORAGE_KEY_PREFIX + url;
  const got = await extensionApi.storage.session.get(storageKey);
  const entry = got && got[storageKey];
  if (entry && entry.ok) {
    const next = { ...entry, result, fetchedAt: Date.now() };
    await extensionApi.storage.session.set({ [storageKey]: next });
    await _writeCachedAnalysis(url, next);
  }
  if (tabId) await _updateBadgeForResult(result, tabId);
  return result;
}

// ── acting on the app, rather than only asking it ───────────────────────
//
// Everything above this line reads: the worker sends a page's labels and gets
// an answer. These three write, and they are what turns the panel from a
// display into a place work starts.
//
// All three go through the app's own HTTP API — the same endpoints the app's
// own UI uses. The extension gets no privileged door, and nothing here
// interprets a claim; it forwards the reader's decision and reports what the
// app said.

async function _postApp(path, body) {
  const response = await _fetchApp(`${await apiBase()}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      detail = (await response.json()).detail || detail;
    } catch (_) {
      // A body that is not JSON tells us nothing the status has not.
    }
    // The status rides along, because "the app said no" and "there is no
    // app" are different situations and the caller has to tell them apart —
    // conflating them is what turned a rejected route into a browser tab.
    const refusal = new Error(`Kriko refused that (${detail}).`);
    refusal.status = response.status;
    throw refusal;
  }
  return response.json();
}

// A service worker can be stopped between the app accepting a write and the
// extension receiving its response. Keep a small durable record of each
// research intent until a job receipt arrives; another click/retry then sends
// the exact same request ID and body, letting the app return the original job.
const RESEARCH_INTENTS_KEY = "krikoResearchIntentsV1";
const RESEARCH_INTENT_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const RESEARCH_INTENTS_LIMIT = 32;
const RESEARCH_INTENT_BODY_LIMIT = 64 * 1024;
const _intentInFlight = new Map();
let _researchIntentLock = Promise.resolve();
let _researchIdCounter = 0;

/* A stable, unreadable key for a string. SHA-256 where the runtime has it —
 * every MV3 service worker does — and a deterministic FNV pair where it does
 * not, because a cache key that changes between two runs is worse than a weak
 * one. The output is the same on every call for the same input, which is the
 * only property either caller needs. */
async function _digest(value) {
  try {
    if (typeof crypto !== "undefined" && crypto.subtle && typeof TextEncoder !== "undefined") {
      const bytes = new TextEncoder().encode(value);
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    }
  } catch (_) { /* an older runtime can still use the deterministic fallback */ }
  let a = 2166136261;
  let b = 2246822519;
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    a = Math.imul(a ^ code, 16777619) >>> 0;
    b = Math.imul(b ^ code, 3266489917) >>> 0;
  }
  return `${a.toString(16)}${b.toString(16)}-${value.length.toString(16)}`;
}

async function _intentKey(path, body) {
  // Persist a digest rather than the user's query a second time as an index.
  return _digest(`${path}\n${JSON.stringify(body)}`);
}

function _newClientRequestId() {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch (_) { /* older extension runtimes */ }
  _researchIdCounter += 1;
  return `kriko-${Date.now().toString(36)}-${_researchIdCounter.toString(36)}-${Math.random().toString(36).slice(2)}`;
}

async function _withResearchIntentLock(fn) {
  const previous = _researchIntentLock;
  let release;
  _researchIntentLock = new Promise((resolve) => { release = resolve; });
  await previous;
  try { return await fn(); }
  finally { release(); }
}

async function _readResearchIntents() {
  const stored = await extensionApi.storage.local.get(RESEARCH_INTENTS_KEY);
  const now = Date.now();
  const rows = stored[RESEARCH_INTENTS_KEY];
  return Array.isArray(rows) ? rows.filter((row) => row && typeof row.key === "string" &&
    typeof row.client_request_id === "string" && row.body &&
    Number.isFinite(row.created_at) && now - row.created_at < RESEARCH_INTENT_TTL_MS)
    .slice(-RESEARCH_INTENTS_LIMIT) : [];
}

async function _writeResearchIntents(rows) {
  const bounded = rows.slice(-RESEARCH_INTENTS_LIMIT);
  if (bounded.some((row) => JSON.stringify(row.body).length > RESEARCH_INTENT_BODY_LIMIT)) {
    throw new Error("The research request is too large to save safely for retry.");
  }
  await extensionApi.storage.local.set({
    [RESEARCH_INTENTS_KEY]: bounded,
  });
}

async function _postIdempotentIntent(path, baseBody, prepareBody = null) {
  const key = await _intentKey(path, baseBody);
  let record = await _withResearchIntentLock(async () => {
    const rows = await _readResearchIntents();
    const existing = rows.find((row) => row.key === key);
    if (existing) {
      await _writeResearchIntents(rows);
      return existing;
    }
    const clientRequestId = _newClientRequestId();
    const created = {
      key,
      path,
      client_request_id: clientRequestId,
      body: { ...baseBody, client_request_id: clientRequestId },
      prepared: !prepareBody,
      created_at: Date.now(),
    };
    await _writeResearchIntents([...rows, created]);
    return created;
  });

  // The first request captures page facts in the durable body too. On a later
  // invocation after a lost response, do not refetch changing page content.
  if (!record.prepared && prepareBody) {
    const body = { ...record.body };
    await prepareBody(body);
    body.client_request_id = record.client_request_id;
    record = await _withResearchIntentLock(async () => {
      const rows = await _readResearchIntents();
      const index = rows.findIndex((row) => row.key === key);
      if (index < 0) return record;
      const prepared = { ...rows[index], body, prepared: true };
      rows[index] = prepared;
      await _writeResearchIntents(rows);
      return prepared;
    });
  }

  let job;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      job = await _postApp(path, record.body);
      break;
    } catch (error) {
      const transient = error.status === undefined || error.status >= 500;
      if (!transient || attempt === 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, 100 * (2 ** attempt)));
    }
  }
  // The receipt is the only evidence that the server response made it back.
  // If storage cleanup itself fails, replaying the same ID remains safe.
  try {
    await _withResearchIntentLock(async () => {
      const rows = await _readResearchIntents();
      await _writeResearchIntents(rows.filter((row) => row.key !== key ||
        row.client_request_id !== record.client_request_id));
    });
  } catch (_) {
    // A receipt still means success. Retaining the ID after a storage failure
    // is safe: another click asks the server for the same accepted job.
  }
  return job;
}

async function _postIdempotent(path, baseBody, prepareBody = null) {
  const key = await _intentKey(path, baseBody);
  const existing = _intentInFlight.get(key);
  if (existing) return existing;
  const operation = _postIdempotentIntent(path, baseBody, prepareBody).finally(() => {
    if (_intentInFlight.get(key) === operation) _intentInFlight.delete(key);
  });
  _intentInFlight.set(key, operation);
  return operation;
}

/** Read something from the app. No body, and never used to change anything —
 * `_postApp` is the write door, this is the read one, and keeping them
 * separate means a caller cannot accidentally fire a mutation while asking a
 * question (RESEARCH_PLANE and JOB_STATUS below are both look-only).
 */
async function _getApp(path) {
  const response = await _fetchApp(`${await apiBase()}${path}`, { method: "GET" });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      detail = (await response.json()).detail || detail;
    } catch (_) {
      // A body that is not JSON tells us nothing the status has not.
    }
    const refusal = new Error(`Kriko refused that (${detail}).`);
    refusal.status = response.status;
    throw refusal;
  }
  return response.json();
}

// The last checkout look for a page, for the panel opened after the banner was dismissed.
async function _getGuard(url) {
  const got = await extensionApi.storage.session.get(GUARD_KEY_PREFIX + url);
  const entry = got[GUARD_KEY_PREFIX + url];
  return entry && entry.ok ? { result: entry.result } : { result: null };
}

/** Bring the desktop app to the front, on the given route.
 *
 * A page cannot raise a native window, so this posts the route and lets the
 * engine tell the shell (see `src/app/web/routers/focus.py`).
 *
 * The interesting part is what counts as success. This used to treat any 2xx
 * as "the window was raised" and any error at all as "open a tab", and both
 * halves were wrong in the same direction — towards lying about what
 * happened:
 *
 *   * A 2xx only means the route was *recorded*. Whether a window came to the
 *     front depends on whether anything is reading the sidecar's stdout, which
 *     is what `delivery` now reports. With the server running in a terminal,
 *     the old code returned `raised: true`, declined to open a tab, and the
 *     button did visibly nothing — the bug this path exists to fix.
 *   * A 422 means the route is not a shape the app could navigate to, i.e.
 *     *this extension* built a bad route. Opening a tab at the same bad route
 *     hides a defect behind a fallback that was designed for a missing app.
 *     It is logged and rethrown instead.
 *
 * Neither failure opens a browser tab any more: the desktop app is the only
 * interface, so a tab would only show the reader a page that is not there.
 */
async function openInApp(route, fallbackUrl) {
  let delivery = "no_shell";
  try {
    const body = await _postApp("/api/focus", { route });
    delivery = body?.delivery ?? (body?.raised ? "raised" : "no_shell");
    if (delivery === "raised") return { ok: true, raised: true, delivery };
  } catch (error) {
    // A refusal is an answer: the app is running and objected. Only a
    // *transport* failure means there is nothing to raise.
    if (error.status) {
      console.warn(`Kriko rejected the route ${route}:`, error.message);
      throw error;
    }
    if (error.code === "APP_NOT_RESPONDING") return { ok: false, code: error.code, error: error.message };
    delivery = "unreachable";
  }

  // "unreachable" means the transport itself failed — there is no engine on
  // the other end, so a fallback tab would only open onto a dead local port
  // (ERR_CONNECTION_REFUSED) with nothing for the reader to do about it. For
  // "no_shell" the engine answered but no window is connected, which is said
  // as a named error: no browser tab, since the desktop app is the interface.
  if (delivery === "unreachable") {
    return {
      ok: false,
      code: "APP_NOT_RUNNING",
      error: "Kriko is not running. Open the Kriko app, then try again.",
    };
  }

  return {
    ok: false,
    code: "DESKTOP_NOT_CONNECTED",
    error: "The Kriko engine is running, but its desktop window is not connected. Open the Kriko app, then try again.",
    delivery,
  };
}

// ── messages ────────────────────────────────────────────────────────────

extensionApi.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (IS_FIREFOX && ["SAVE_FOLLOW_UPS", "RESTORE_FOLLOW_UPS"].includes(request.type)) {
    // Derive the key from the sending tab, never a caller-supplied URL.
    if (!sender.tab?.url) { sendResponse({ ok: false }); return; }
    const key = `kriko_followups_${sender.tab.url}`;
    const action = request.type === "SAVE_FOLLOW_UPS"
      ? extensionApi.storage.session.set({ [key]: request.value })
      : extensionApi.storage.session.get(key);
    action.then((bag) => sendResponse({ ok: true, value: bag?.[key] }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
  if (request.type === "ANALYZE") {
    const url = request.payload?.url;
    if (!url) {
      sendResponse({ ok: false, error: "Missing URL" });
      return false;
    }

    const run = async () => {
      let tabId = sender.tab?.id;
      if (!tabId) {
        const tabs = await extensionApi.tabs.query({ active: true, currentWindow: true });
        tabId = tabs[0]?.id;
      }
      if (!tabId) throw new Error("No active tab found.");
      return runAnalysisForTab(tabId, url, { fresh: Boolean(request.payload?.fresh) });
    };

    run()
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, hostKnown: Boolean(error.hostKnown),
        learnable: Boolean(error.learnable),
        productName: error.productName || "", error: error.message }));

    return true; // async
  }

  if (request.type === "REFRESH_ANSWER") {
    const { url, lookupId } = request.payload || {};
    if (!url || !lookupId) {
      sendResponse({ ok: false, error: "Missing answer" });
      return false;
    }
    refreshAnswer(sender.tab?.id, url, lookupId)
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
    runAnalysisForTab(tabId, url, { auto: true }).catch(() => {});
    if (CHECKOUT_PATH.test(url)) void guardCheckout(tabId, url);
    sendResponse({ ok: true, message: "Analysis triggered" });
    return false;
  }

  if (request.type === "OPEN_IN_APP") {
    const route = request.payload?.route;
    if (!route) {
      sendResponse({ ok: false, error: "Missing route" });
      return false;
    }
    apiBase().then((base) => openInApp(route, request.payload?.fallbackUrl || `${base}/#/${route}`))
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  if (request.type === "MARK_CLAIM") {
    const mark = request.payload || {};
    if (!mark.claim_id || !mark.pack_id) {
      sendResponse({ ok: false, error: "Missing claim" });
      return false;
    }
    // No verdict means "take it back". Pressing the same button twice is how
    // a reader unmarks, so the undo is the same message rather than a second
    // one the panel has to decide between.
    const run = mark.verdict
      ? _postApp("/api/marks", mark)
      : (async () => {
          const base = await apiBase();
          const url = `${base}/api/marks/${encodeURIComponent(mark.pack_id)}`
            + `/${encodeURIComponent(mark.claim_id)}`;
          const response = await _fetchApp(url, { method: "DELETE" });
          if (!response.ok) throw new Error(`Kriko refused that (${response.status}).`);
          return response.json();
        })();
    run
      .then((row) => sendResponse({ ok: true, mark: row }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  // Does the page this claim cites still say it? One press, on the card the
  // reader is looking at — which is the same question the app's report button
  // asks, through the same endpoint. The check is the app's: nothing about
  // the quote is sent from here, because a check whose input came from a
  // browser would prove nothing.
  if (request.type === "CHECK_FACTS") {
    const { pack_id, claim_id } = request.payload || {};
    if (!pack_id || !claim_id) {
      sendResponse({ ok: false, error: "Missing claim" });
      return false;
    }
    _postApp("/api/factcheck", { pack_id, claim_id })
      .then((check) => sendResponse({ ok: true, check }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  /* The agents that can answer from this panel, and the one the app uses.
   * Only a row the app calls ready *and* runnable ("use") is offered: a row
   * that needs a login or an install is Settings' business, not a choice. */
  if (request.type === "AGENTS") {
    _getApp("/api/agent-market")
      .then((market) => sendResponse({
        ok: true,
        chosen: String(market.chosen || ""),
        agents: (market.agents || [])
          .filter((one) => one && one.id && one.state === "ready" && one.action === "use")
          .map((one) => ({ id: String(one.id), label: String(one.label || one.id), kind: String(one.kind || ""),
            local: Boolean(one.local) })),
      }))
      .catch((error) => sendResponse({ ok: false, code: error.code, error: error.message }));
    return true;
  }

  /* "Learn this page": read the page the way an agent would have to, then hand
   * the app what it printed. The snapshot is taken here, from the tab that
   * pressed the button, because the page is already rendered and past whatever
   * bot check the site runs; the app never fetches it. */
  if (request.type === "LEARN_PAGE") {
    const agent = String(request.payload?.agent || "").slice(0, 64);
    const run = async () => {
      let tabId = sender.tab?.id;
      if (!tabId) {
        const tabs = await extensionApi.tabs.query({ active: true, currentWindow: true });
        tabId = tabs[0]?.id;
      }
      if (!tabId) throw new Error("No active tab found.");
      const reply = await _requestScrape(tabId, [], {}, true);
      if (!reply || !reply.ok || !reply.payload) throw new Error("Kriko could not read this page.");
      const scrape = reply.payload;
      return _postApp("/api/sites/learn", {
        url: scrape.url,
        title: String(scrape.title || "").slice(0, 500),
        page_title: String(scrape.title || "").slice(0, 500),
        fields: scrape.fields || {},
        description: String(scrape.description || "").slice(0, 5000),
        product: scrape.product || {},
        agent,
      });
    };
    run()
      .then((lesson) => sendResponse({ ok: true, lesson }))
      .catch((error) => sendResponse({ ok: false, code: error.code, error: error.message }));
    return true;
  }

  if (request.type === "RESEARCH_PRODUCT") {
    const input = request.payload || {};
    const subject_id = String(input.subject_id || "").trim();
    const q = String(input.q || "").trim();
    if (!subject_id && !q) {
      sendResponse({ ok: false, error: "Enter a product name or select a subject." });
      return false;
    }
    const body = subject_id ? { subject_id } : { q, allow_draft: input.allow_draft === true };
    // B148: the listing's own address, so the quick look is held to the bar
    // of the pack whose site this is.
    if (!subject_id && typeof input.url === "string" && input.url) body.url = input.url.slice(0, 2000);
    // The agent the reader picked in the panel, for this run only.
    if (typeof input.harness === "string" && input.harness) body.harness = input.harness.slice(0, 64);
    if (Number.isFinite(input.cap) && input.cap > 0) body.cap = input.cap;
    _postIdempotent("/api/extension/research-plane", body, async (prepared) => {
      if (!prepared.url) return;
      const page = await _pageFacts(prepared.url);
      // B150: what the listing says travels with its name.
      if (page && page.facts && Object.keys(page.facts).length) prepared.facts = page.facts;
      if (page && page.description) prepared.description = page.description;
    })
      .then((job) => sendResponse({ ok: true, job }))
      .catch((error) => sendResponse({
        ok: false, status: error.status, code: error.code, error: error.message }));
    return true;
  }

  // A saved quick look joins a pack only when the reader asks: the look is
  // one job, the pack run that files its sourced risks is a second, started
  // here (POST /api/extension/quick-looks/{id}/pack).
  if (request.type === "QUICK_TO_PACK") {
    const jobId = String(request.payload?.job_id || "").trim();
    if (!jobId) {
      sendResponse({ ok: false, error: "Missing job_id" });
      return false;
    }
    _postIdempotent(`/api/extension/quick-looks/${encodeURIComponent(jobId)}/pack`, {})
      .then((job) => sendResponse({ ok: true, job }))
      .catch((error) => sendResponse({
        ok: false, status: error.status, code: error.code, error: error.message }));
    return true; // async
  }

  // Queue mode: the listing's product joins the app's research queue, for an
  // agent to research in turn and the compare screen to line up. The page's
  // address keys it, so a second press answers "already queued".
  // The reader as a buyer: each is the reader's own button, forwarded to the
  // app's own API, and nothing here interprets a verdict.
  const BUYER_CALLS = {
    BUYER_FIT: (p) => _postApp("/api/buyer/fit", { items: Array.isArray(p.items) ? p.items.slice(0, 60) : [] }),
    BUYER_WATCH: (p) => _postApp("/api/prices/watches", {
      url: String(p.url || "").slice(0, 2000), name: String(p.name || "").slice(0, 300),
      target: p.target ?? null, drop_pct: p.drop_pct ?? null, price: p.price ?? null,
      currency: String(p.currency || "").slice(0, 8), cloud: p.cloud === true ? true : null }),
    BUYER_UNWATCH: async (p) => {
      const response = await _fetchApp(
        `${await apiBase()}/api/prices/watches/${encodeURIComponent(p.watch_id)}`, { method: "DELETE" });
      if (!response.ok) {
        // A refused delete is not a stopped watch: the panel must not draw it as gone.
        const refusal = new Error(`Kriko refused that (${response.status}).`);
        refusal.status = response.status;
        throw refusal;
      }
      return response.json();
    },
    BUYER_BOUGHT: (p) => _postApp("/api/buyer/purchases", {
      name: String(p.name || "").slice(0, 300), url: String(p.url || "").slice(0, 2000),
      price: p.price ?? null, currency: String(p.currency || "").slice(0, 8) }),
    BUYER_DUE: () => _getApp("/api/buyer/purchases"),
    BUYER_ANSWER: (p) => _postApp(`/api/buyer/purchases/${encodeURIComponent(p.purchase_id)}/answer`, {
      verdict: String(p.verdict || ""), reason: String(p.reason || "").slice(0, 600) }),
    BUYER_SNOOZE: (p) => _postApp(`/api/buyer/purchases/${encodeURIComponent(p.purchase_id)}/snooze`, {}),
    BUYER_PICK: () => _postApp("/api/buyer/pick", { queue: true }),
    BUYER_ADVICE: (p) => _postApp("/api/buyer/advice", {
      queue: true, mode: String(p.mode || "pick"), question: String(p.question || "").slice(0, 600) }),
    BUYER_GUARD: (p) => _getGuard(String(p.url || "")),
  };
  if (Object.prototype.hasOwnProperty.call(BUYER_CALLS, request.type)) {
    Promise.resolve()
      .then(() => BUYER_CALLS[request.type](request.payload || {}))
      .then((reply) => sendResponse({ ok: true, ...reply }))
      .catch((error) => sendResponse({
        ok: false, status: error.status, error: error.message }));
    return true;
  }

  if (request.type === "QUEUE_ADD") {
    const input = request.payload || {};
    const url = typeof input.url === "string" ? input.url.slice(0, 2000) : "";
    if (!url) {
      sendResponse({ ok: false, error: "This page has no address to queue." });
      return false;
    }
    _postApp("/api/queue", {
      url,
      name: String(input.name || "").slice(0, 400),
      lookup_id: String(input.lookup_id || "").slice(0, 64),
    })
      .then((reply) => sendResponse({ ok: true, ...reply }))
      .catch((error) => sendResponse({
        ok: false, status: error.status, code: error.code, error: error.message }));
    return true;
  }

  if (request.type === "CANCEL_JOB") {
    const jobId = request.payload?.job_id;
    if (!jobId) {
      sendResponse({ ok: false, error: "Missing job_id" });
      return false;
    }
    _postApp(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {})
      .then((job) => sendResponse({ ok: true, job }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  /* A run's question answered from the panel (B147). A live run hears it
   * through `/say` at once; a finished one is run again with the answer
   * applied, the same `retry` the app's Runs screen submits. */
  if (request.type === "JOB_SAY" || request.type === "JOB_RETRY") {
    const jobId = request.payload?.job_id;
    if (!jobId) {
      sendResponse({ ok: false, error: "Missing job_id" });
      return false;
    }
    const say = request.type === "JOB_SAY";
    const body = say
      ? { text: String(request.payload.text || "") }
      : { answers: request.payload.answers || {} };
    _postApp(`/api/jobs/${encodeURIComponent(jobId)}/${say ? "say" : "retry"}`, body)
      .then((answer) => sendResponse({ ok: true, ...answer }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (request.type === "RESEARCH_SUBJECT") {
    const { subject_id, pack_id, backend, budget_usd } = request.payload || {};
    if (!subject_id) {
      sendResponse({ ok: false, error: "Missing subject" });
      return false;
    }
    // Research is a job, not a request — it outlives this service worker,
    // which Chrome may stop at any moment. `backend` and `budget_usd` come
    // from the panel, which read them off RESEARCH_PLANE first: naming the
    // cost happens before this message is ever sent, not here.
    //
    // Unlike the old behaviour, this does not raise the desktop app. The
    // panel polls the returned job with JOB_STATUS and shows progress in
    // place — a button that fires a job and then jumps the reader to a
    // different window is not "inline", it is a navigation with extra
    // steps.
    _postApp("/api/research", {
      subject_id,
      pack_id,
      backend: backend || "agent",
      budget_usd: budget_usd || 0,
    })
      .then((job) => sendResponse({ ok: true, job }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  if (request.type === "SAVED_QUICK_LOOK") {
    const url = String(request.payload?.url || "").slice(0, 2000);
    _getApp(`/api/extension/quick-looks?url=${encodeURIComponent(url)}`)
      .then((response) => sendResponse({ ok: true, ...response }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  // What plane this installation is configured for, and what it costs — read
  // before RESEARCH_SUBJECT is ever sent, so the panel can name the cost
  // before it spends it (agent: nothing; api: the enforced cap). Never a key:
  // `/api/extension/research-plane` answers with the same discipline as
  // `/api/keys` — a plane name and a number, nothing that could be replayed
  // as a credential.
  if (request.type === "RESEARCH_PLANE") {
    _getApp("/api/extension/research-plane")
      .then((plane) => sendResponse({ ok: true, plane }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  /* Typing a product name, when standing on its page did not place it.
   *
   * A read, so it goes through `_getApp` — and through the worker at all for
   * the same reason every other call does: the content script has no
   * `host_permissions` for 127.0.0.1, so a fetch from the panel would be a
   * cross-origin request the page's own CSP gets a say in.
   *
   * The query is passed straight through and the limit is not the caller's to
   * choose. A panel is a list, not a catalogue, and a client that could ask
   * for a thousand rows is a client that will one day be asked to render
   * them.
   */
  if (request.type === "SEARCH" || request.type === "WEB_SEARCH") {
    const query = String(request.payload?.q || "").trim();
    if (!query) {
      sendResponse({ ok: true, items: [] });
      return false;
    }
    const path = request.type === "WEB_SEARCH"
      ? `/api/extension/web-search?q=${encodeURIComponent(query)}`
      : `/api/search?q=${encodeURIComponent(query)}&limit=${SEARCH_LIMIT}`;
    _getApp(path)
      .then((body) => sendResponse({
        ok: true, items: Array.isArray(body?.items) ? body.items : [] }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  // Progress on one job, polled from the panel rather than pushed — the
  // service worker can be stopped and restarted by Chrome mid-run, and a job
  // id is enough to pick the poll back up with no state lost.
  if (request.type === "JOB_STATUS") {
    const jobId = request.payload?.job_id;
    if (!jobId) {
      sendResponse({ ok: false, error: "Missing job_id" });
      return false;
    }
    _getApp(`/api/jobs/${encodeURIComponent(jobId)}`)
      .then((job) => sendResponse({ ok: true, job }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  /* What the rest of Kriko is doing, right now.
   *
   * The panel could see its own run and nothing else — so a reader whose
   * coding agent was mid-research on the very car they were looking at had
   * no way to know it from the page they were on, and the app's Live screen
   * (which does know) is the one place they are not, precisely because they
   * are here reading a listing.
   *
   * Read-only, and through `_getApp` like every other question: the panel
   * shows the feed, it does not join it. The extension's own run appears in
   * it anyway, by the `extension` door, written by the app.
   */
  if (request.type === "OPERATIONS") {
    const limit = Number(request.payload?.limit) || 6;
    _getApp(`/api/operations?limit=${encodeURIComponent(limit)}`)
      .then((feed) => sendResponse({ ok: true, feed }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  // ── where the app is ──────────────────────────────────────────────────
  //
  // The options page could read and write `krikoApiBaseUrl` itself — it has
  // the storage permission. It asks the worker instead so that the rules
  // about what a base URL *is* (`_normalizeBaseUrl`) live in exactly one
  // place. A settings screen that normalises differently from the code that
  // consumes the value is a settings screen that can save something the
  // extension then ignores, silently.
  if (request.type === "GET_API_BASE") {
    extensionApi.storage.local
      .get(["krikoApiBaseUrl"])
      .then((stored) => sendResponse({
        ok: true,
        base: _normalizeBaseUrl(stored.krikoApiBaseUrl) || DEFAULT_API_BASE,
        stored: stored.krikoApiBaseUrl || "",
        default: DEFAULT_API_BASE,
      }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true; // async
  }

  if (request.type === "SET_API_BASE") {
    const raw = (request.payload?.url ?? "").trim();
    const base = _normalizeBaseUrl(raw);
    if (raw && !base) {
      sendResponse({ ok: false, error: "That is not a URL Kriko can reach." });
      return false;
    }
    const run = async () => {
      // Empty means "go back to the default", which is a removal rather than
      // a stored empty string: `apiBase()` falls back on a missing key, and
      // storing "" would be a value that reads as a choice.
      if (base) await extensionApi.storage.local.set({ krikoApiBaseUrl: base });
      else await extensionApi.storage.local.remove("krikoApiBaseUrl");
      const stored = base || "";
      adaptersCache = null; // the old app's adapter list is not this one's
      const effective = base || DEFAULT_API_BASE;
      // Saved first, probed second, and the probe's failure is not the
      // save's. Someone configuring the extension before starting the app is
      // doing a reasonable thing, and refusing to remember the address until
      // something answers at it would make that impossible.
      try {
        const response = await _fetchApp(`${effective}/api/health`);
        if (!response.ok) {
          return { ok: true, base: effective, stored, reachable: false,
                   detail: `The app answered ${response.status}.` };
        }
        const health = await response.json();
        return { ok: true, base: effective, stored, reachable: true,
                 version: health.version };
      } catch (error) {
        return { ok: true, base: effective, stored, reachable: false,
                 detail: error.message };
      }
    };
    run()
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true; // async
  }

  // ── which sites this install actually covers ────────────────────────
  //
  // The options page asks; it does not compute. Whether a site is covered is
  // a function of the manifest, the installed packs and Chrome's permission
  // table, and a settings screen that worked any of those out for itself
  // would be a second implementation to drift from this one.
  //
  // `KRIKO_SITE_STATUS` reads the last sync's record without touching the
  // network, so opening the options page with the app closed shows what is
  // known rather than an error. `KRIKO_SYNC_SITES` is the reader pressing the
  // button, which is the only reason to bypass the adapter cache.
  if (request.type === "KRIKO_SITE_STATUS") {
    readSiteStatus()
      .then((record) => sendResponse({ ok: true, status: record }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true; // async
  }

  if (request.type === "KRIKO_SYNC_SITES") {
    syncSites({ fresh: true })
      .then((record) => sendResponse({ ok: true, status: record }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true; // async
  }

  if (request.type === "KRIKO_COMPAT") {
    // No network: the verdict was recorded by whatever request last reached
    // the app, and the reader who needs this sentence most is the one whose
    // app is closed right now.
    readCompat()
      .then((record) => sendResponse({ ok: true, compat: record }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true; // async
  }

  /* How much doubt the reader wants to see (#263): the app's own setting,
   * `info_sensitivity`, read and written through the one settings route the
   * app's Settings screen uses, so the two can never disagree. The worker is
   * the only caller, as for every other request: a content script has no
   * permission to reach the app.
   *
   * A value this does not know is `all`, on the way in and on the way out:
   * a setting that cannot be read must never hide evidence. */
  if (request.type === "INFO_SENSITIVITY") {
    _getApp("/api/settings")
      .then((settings) => sendResponse({ ok: true, sensitivity: _sensitivityOf(settings) }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message, sensitivity: "all" }));
    return true; // async
  }

  if (request.type === "SET_INFO_SENSITIVITY") {
    const wanted = String(request.payload?.sensitivity || "");
    if (!INFO_SENSITIVITIES.includes(wanted)) {
      sendResponse({ ok: false, error: "That is not one of the three settings." });
      return false;
    }
    _postApp("/api/settings", { values: { info_sensitivity: wanted } })
      .then((settings) => sendResponse({ ok: true, sensitivity: _sensitivityOf(settings) }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, error: error.message }));
    return true; // async
  }

  if (request.type === "OPEN_OPTIONS") {
    // A page cannot navigate to a `chrome-extension://` settings page on its
    // own, so the panel asks. Worth having because the one moment a reader
    // needs this screen is the moment the panel is telling them nothing is
    // listening — and the options page is otherwise buried in the browser's
    // own extension manager.
    try {
      extensionApi.runtime.openOptionsPage();
      sendResponse({ ok: true });
    } catch (error) {
      sendResponse({ ok: false, error: error.message });
    }
    return false;
  }

  if (request.type === "GET_CACHED_RESULT") {
    const url = request.payload?.url;
    if (!url) {
      sendResponse({ ok: false, error: "Missing URL" });
      return false;
    }

    const storageKey = STORAGE_KEY_PREFIX + url;
    extensionApi.storage.session
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
extensionApi.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    extensionApi.action.setBadgeText({ text: "", tabId }).catch(() => {});
  }
});
