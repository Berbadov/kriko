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
const LOADED_CONTENT_DIGEST = "";

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
    await chrome.storage.session.set({
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

// Hover Lite is the only in-page surface, and there are two ways to reach it.
//
// One function rather than a listener each, because a keyboard shortcut whose
// behaviour has drifted from the toolbar button's is worse than no shortcut:
// the reader learns the key, and then one day it does something else.
async function toggleHoverLite(tab) {
  if (!tab || !tab.id) return false;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "TOGGLE_HOVER_LITE" });
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
// registered, so basically it opens on sahibinden only". Nothing was broken;
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
chrome.action.onClicked.addListener((tab) => { void onToolbarClick(tab); });

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

if (chrome.permissions && chrome.permissions.contains) {
  chrome.permissions.contains({ origins: [EVERY_SITE] })
    .then((yes) => { everySiteGranted = Boolean(yes); })
    .catch(() => {});
}

function _askEverySiteOnce(tab) {
  const url = String((tab && tab.url) || "");
  if (everySiteGranted === true || !/^https:/i.test(url)) return null;
  if (!chrome.permissions || !chrome.permissions.request) return null;
  // Not on a site the package already runs on: the panel works there, and a
  // prompt on the reader's usual site would be asking for nothing they need.
  if (staticSiteHosts().has(_hostOf(url))) return null;
  try {
    return Promise.resolve(chrome.permissions.request({ origins: [EVERY_SITE] }))
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
  if (!tab || !tab.id || !/^https:/i.test(url) || !chrome.scripting) return false;
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: SITE_SCRIPTS });
  } catch (_) {
    return false;    // a page Chrome keeps extensions out of (the web store, say)
  }
  return toggleHoverLite(tab);
}

async function reportUnreadableSite(tab) {
  const url = tab && tab.url;
  if (!url || !/^https?:/i.test(url)) return false;
  try {
    const response = await _fetchApp(`${await apiBase()}/api/sites/seen`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url, title: (tab && tab.title) || "" }),
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
          + "permission yet. Open Kriko's extension options and press Grant — "
          + "only the extension can ask.",
        );
        if (chrome.runtime.openOptionsPage) chrome.runtime.openOptionsPage();
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
      if (chrome.tabs && chrome.tabs.reload) await chrome.tabs.reload(tab.id);
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
// `chrome.scripting.executeScript` under `activeTab` is granted by the click
// itself; a toast that needs a permission the reader has not given would be a
// message they never see.
async function notify(tab, text) {
  if (!tab || !tab.id || !chrome.scripting) return;
  try {
    await chrome.scripting.executeScript({
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
if (chrome.commands && chrome.commands.onCommand) {
  chrome.commands.onCommand.addListener(async (command) => {
    if (command !== "toggle-panel") return;
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
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
  const stored = await chrome.storage.local.get(["krikoApiBaseUrl"]);
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
  return new RegExp("^" + body + "$", "i");
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
// like `*sahibinden.com/ilan/*` — the domain fragment before the first `/` is
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
    return String(chrome.runtime.getManifest().version || "");
  } catch (_) {
    return "";
  }
}

async function _fetchApp(url, init) {
  const stamped = { ...(init || {}) };
  stamped.headers = { ...(stamped.headers || {}), [VERSION_HEADER]: _ownVersion() };
  if (LOADED_CONTENT_DIGEST) stamped.headers["X-Kriko-Extension-Digest"] = LOADED_CONTENT_DIGEST;
  try {
    const response = await fetch(url, stamped);
    void _noteMinimum(response);
    void _noteStaged(response);
    return response;
  } catch (cause) {
    const down = new Error(
      "Kriko is not running. Open the Kriko app, then try again.");
    down.code = "APP_NOT_RUNNING";
    down.cause = cause;
    throw down;
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
    const got = await chrome.storage.local.get(SELF_RELOAD_KEY);
    const last = got && got[SELF_RELOAD_KEY];
    if (last && last.digest === staged && Date.now() - last.at < SELF_RELOAD_QUIET_MS) return;
    await chrome.storage.local.set({
      [SELF_RELOAD_KEY]: { digest: staged, at: Date.now(), pending: true },
    });
    chrome.runtime.reload();
  } catch (_) {
    // A worker that cannot reload keeps working on the files it has.
  }
}

// After a self-reload the listing tabs still hold the old content script,
// cut off from this worker. Refresh them so the panel on screen is the new one.
chrome.runtime.onInstalled.addListener(async (details) => {
  if (!details || details.reason !== "update") return;
  try {
    const got = await chrome.storage.local.get(SELF_RELOAD_KEY);
    const last = got && got[SELF_RELOAD_KEY];
    if (!last || !last.pending) return;
    await chrome.storage.local.set({ [SELF_RELOAD_KEY]: { ...last, pending: false } });
    const patterns = [];
    for (const entry of chrome.runtime.getManifest().content_scripts || []) {
      for (const one of entry.matches || []) if (!patterns.includes(one)) patterns.push(one);
    }
    if (!patterns.length) return;
    for (const tab of await chrome.tabs.query({ url: patterns })) {
      if (tab && tab.id !== undefined) chrome.tabs.reload(tab.id);
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
    await chrome.storage.local.set({ [COMPAT_KEY]: record });
  } catch (_) {
    // Nothing to do and nothing lost: the next response says it again.
  }
}

async function readCompat() {
  try {
    const stored = await chrome.storage.local.get([COMPAT_KEY]);
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
// an adapter's `site` is a bare registrable host (`sahibinden.com`), which
// becomes exactly one match pattern. No hostname list lives in this file, and
// none should ever be added to it.
//
// *Synchronisation.* `chrome.scripting` holds the registration, not this
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
// the array is what matters: `icons.js` and `claim_card.js` define what
// `hover_lite.js` calls.
const SITE_SCRIPTS = [
  "content.js",
  "hover_lite/icons.js",
  "hover_lite/claim_card.js",
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
  const manifest = chrome.runtime.getManifest ? chrome.runtime.getManifest() : {};
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
  if (!chrome.permissions || !chrome.permissions.contains) return false;
  try {
    return await chrome.permissions.contains({ origins: [pattern] });
  } catch (_) {
    return false;
  }
}

async function _registeredSiteScripts() {
  if (!chrome.scripting || !chrome.scripting.getRegisteredContentScripts) return [];
  try {
    const all = await chrome.scripting.getRegisteredContentScripts();
    return (all || []).filter((s) => String(s.id).startsWith(SITE_SCRIPT_PREFIX));
  } catch (_) {
    return [];
  }
}

async function _writeSiteStatus(record) {
  try {
    await chrome.storage.local.set({ [SITE_SYNC_KEY]: record });
  } catch (_) {
    // A status nobody can read is not a reason to undo a registration.
  }
}

async function readSiteStatus() {
  try {
    const stored = await chrome.storage.local.get([SITE_SYNC_KEY]);
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
  if (stale.length && chrome.scripting.unregisterContentScripts) {
    try {
      await chrome.scripting.unregisterContentScripts({ ids: stale });
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
      await chrome.scripting.registerContentScripts([{
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
  if (!chrome.scripting || !chrome.scripting.getRegisteredContentScripts) return;
  const granted = await _granted(EVERY_SITE);
  everySiteGranted = granted;
  let all = [];
  try {
    all = (await chrome.scripting.getRegisteredContentScripts()) || [];
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
      await chrome.scripting.unregisterContentScripts({ ids: [ANY_SITE_SCRIPT_ID] });
    } catch (_) {
      // Already gone.
    }
  }
  if (!granted || same) return;
  try {
    await chrome.scripting.registerContentScripts([{
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
chrome.runtime.onInstalled.addListener(() => {
  void syncSites({ fresh: true });
});
if (chrome.runtime.onStartup) {
  chrome.runtime.onStartup.addListener(() => { void syncSites({ fresh: true }); });
}
if (chrome.alarms) {
  chrome.alarms.create(SITE_SYNC_ALARM, {
    periodInMinutes: SITE_SYNC_PERIOD_MINUTES,
    delayInMinutes: 1,
  });
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm && alarm.name === SITE_SYNC_ALARM) void syncSites({ fresh: true });
  });
}
// A grant is the event the pending list was waiting for, and a revocation has
// to take the injection with it — an extension still running on a site the
// reader took back is the worst failure available here.
if (chrome.permissions && chrome.permissions.onAdded) {
  chrome.permissions.onAdded.addListener(() => { void syncSites(); });
  chrome.permissions.onRemoved.addListener(() => { void syncSites(); });
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
    title: scrape?.title || "",
    fields: scrape?.fields || {},
    packs: (adapters || []).map((a) => `${a.pack_id}@${a.version || ""}`).sort(),
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

  await chrome.action.setBadgeText({ text: badgeText, tabId });
  await chrome.action.setBadgeBackgroundColor({ color: badgeColor, tabId });
}

// ── scraping ────────────────────────────────────────────────────────────

async function _requestScrape(tabId, labels, panel) {
  // `panel` is the adapter's `local_panel` block: the words, selectors and
  // rules the content script needs to read the damage and equipment blocks.
  // It travels per-request rather than being cached in the content script,
  // because the adapter list is refreshed here and a scrape reading last
  // week's rules would be invisible.
  const ask = { type: "GET_SCRAPE", labels, panel };
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
    await chrome.storage.session.set({ [PAGE_FACTS_PREFIX + url]: { facts, description } });
  } catch (_) {
    // A listing whose facts could not be kept still gets researched by name.
  }
}

async function _pageFacts(url) {
  try {
    const key = PAGE_FACTS_PREFIX + url;
    const got = await chrome.storage.session.get(key);
    return (got && got[key]) || null;
  } catch (_) {
    return null;
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

  try {
    await _stage(url, "adapters", "");
    const adapters = await fetchAdapters();
    const adapter = adapterFor(url, adapters);
    // Not an error the reader can act on — most pages are not listings —
    // but not something to answer with an empty result either, which would
    // read as "nothing is known about this car". Coded so the panel can
    // fall quiet instead of showing a red banner on every ordinary page.
    const noAdapter = () => {
      const quiet = new Error("No installed pack can read this page.");
      quiet.code = "NO_ADAPTER";
      quiet.hostKnown = hostHasAnyAdapter(url, adapters);
      return quiet;
    };

    // Named after the pack that will read it, not after the mechanism: the
    // reader knows which site they are on, and "reading this page" is the
    // step they can see happening in front of them.
    await _stage(url, "reading", (adapter && adapter.pack_id) || "");
    const scrapeStartedAt = _now();
    // No site adapter is no longer the end (B149): every page is read for
    // the product it publishes, and the app decides whether a pack knows it.
    const reply = await _requestScrape(
      tabId, (adapter && adapter.labels) || [], (adapter && adapter.local_panel) || {}
    );
    timings.scrape_ms = _elapsed(scrapeStartedAt);
    if (!reply || !reply.ok) {
      if (!adapter) throw noAdapter();
      throw new Error("Unable to read this page.");
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
      await chrome.storage.session.set({ [storageKey]: cachedEntry });
      await _updateBadgeForResult(cachedEntry.result, tabId);
      return cachedEntry.result;
    }

    await _stage(url, "asking", "");
    const raw = await requestAnalysis(scrape, timings);
    if (raw && raw.readable === false) {
      if (raw.reason === "unknown_product") {
        const unknown = new Error("Kriko doesn't know this product yet.");
        unknown.code = "UNKNOWN_PRODUCT";
        unknown.productName = (raw.product && raw.product.name) || "";
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
    await _stage(url, "failed", error.message || "");
    if (error.code) errEntry.code = error.code;
    if (error.hostKnown) errEntry.hostKnown = true;
    if (error.productName) errEntry.productName = error.productName;
    if (scrape) errEntry.listing = { ...(scrape.listing || {}), title: scrape.title || "" };
    await chrome.storage.session.set({ [storageKey]: errEntry });
    // NO_ADAPTER is not a failure — it's most pages on the internet, which is
    // exactly why the badge used to paint a red "!" on every non-listing page
    // of the one site Kriko *does* read (extension-5, B145 audit). A page
    // this extension was never going to have an opinion on gets no badge.
    if (error.code === "NO_ADAPTER") {
      await chrome.action.setBadgeText({ text: "", tabId });
    } else if (error.code === "UNKNOWN_PRODUCT") {
      // Not a failure either: a product nothing installed covers yet, one
      // click from being researched. A question, not an alarm.
      await chrome.action.setBadgeText({ text: "?", tabId });
      await chrome.action.setBadgeBackgroundColor({ color: "#5b6472", tabId });
    } else {
      await chrome.action.setBadgeText({ text: "!", tabId });
      await chrome.action.setBadgeBackgroundColor({ color: "#b5392f", tabId });
    }
    throw error;
  }
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
 * The fallback tab is therefore reserved for the two cases it was meant for:
 * no server reachable, and a server with no shell attached to it.
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
    delivery = "unreachable";
  }

  // "unreachable" means the transport itself failed — there is no engine on
  // the other end, so a fallback tab would only open onto a dead local port
  // (ERR_CONNECTION_REFUSED) with nothing for the reader to do about it. The
  // fallback tab stays reserved for "no_shell": the engine answered, it just
  // has no window to raise.
  if (delivery === "unreachable") {
    return {
      ok: false,
      code: "APP_NOT_RUNNING",
      error: "Kriko is not running. Open the Kriko app, then try again.",
    };
  }

  if (fallbackUrl) {
    await chrome.tabs.create({ url: fallbackUrl });
    return { ok: true, raised: false, fallback: true, delivery };
  }
  // Nothing to raise and nowhere to fall back to. Still not an error: the
  // route is recorded server-side for the TTL, so a window opened in the next
  // thirty seconds picks it up.
  return { ok: true, raised: false, delivery };
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
      return runAnalysisForTab(tabId, url, { fresh: Boolean(request.payload?.fresh) });
    };

    run()
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({
        ok: false, code: error.code, hostKnown: Boolean(error.hostKnown),
        productName: error.productName || "", error: error.message }));

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
    if (Number.isFinite(input.cap) && input.cap > 0) body.cap = input.cap;
    (body.url ? _pageFacts(body.url) : Promise.resolve(null))
      .then((page) => {
        // B150: what the listing says travels with its name.
        if (page && page.facts && Object.keys(page.facts).length) body.facts = page.facts;
        if (page && page.description) body.description = page.description;
        return _postApp("/api/extension/research-plane", body);
      })
      .then((job) => sendResponse({ ok: true, job }))
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
  if (request.type === "SEARCH") {
    const query = String(request.payload?.q || "").trim();
    if (!query) {
      sendResponse({ ok: true, items: [] });
      return false;
    }
    _getApp(`/api/search?q=${encodeURIComponent(query)}&limit=${SEARCH_LIMIT}`)
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
    chrome.storage.local
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
      if (base) await chrome.storage.local.set({ krikoApiBaseUrl: base });
      else await chrome.storage.local.remove("krikoApiBaseUrl");
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

  if (request.type === "OPEN_OPTIONS") {
    // A page cannot navigate to a `chrome-extension://` settings page on its
    // own, so the panel asks. Worth having because the one moment a reader
    // needs this screen is the moment the panel is telling them nothing is
    // listening — and the options page is otherwise buried in the browser's
    // own extension manager.
    try {
      chrome.runtime.openOptionsPage();
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
