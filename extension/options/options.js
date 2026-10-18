// The extension's one setting, and no logic of its own.
//
// Every rule about what an address means lives in the service worker
// (`_normalizeBaseUrl`, and the probe that decides whether anything answered).
// This file reads a field, sends a message, and writes the reply into a
// sentence — because two places that both "know" what a valid base URL is
// eventually disagree, and the disagreement shows up as a saved setting the
// extension quietly does not use.

const form = document.getElementById("form");
const input = document.getElementById("base");
const statusEl = document.getElementById("status");
const defaultEl = document.getElementById("default");
const resetButton = document.getElementById("reset");
const saveButton = document.getElementById("save");

function say(text, state) {
  statusEl.textContent = text;
  if (state) statusEl.dataset.state = state;
  else delete statusEl.dataset.state;
}

function ask(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || { ok: false, error: "No answer from the extension." });
    });
  });
}

async function load() {
  const reply = await ask({ type: "GET_API_BASE" });
  if (!reply.ok) {
    say(reply.error, "error");
    return;
  }
  if (defaultEl) defaultEl.textContent = reply.default;
  input.placeholder = reply.default;
  // The *stored* value, not the effective one. Showing the default in the
  // field would make "I have not chosen" indistinguishable from "I chose the
  // default", and then emptying the field to go back would look like a no-op.
  input.value = reply.stored ?? "";
}

async function save(value) {
  saveButton.disabled = true;
  say("Saving…");
  const reply = await ask({ type: "SET_API_BASE", payload: { url: value } });
  saveButton.disabled = false;
  if (!reply.ok) {
    say(reply.error, "error");
    return;
  }
  // `stored`, so an empty field stays empty: the worker echoes back what it
  // actually kept, and it keeps nothing when the reader asked for the default.
  input.value = reply.stored ?? "";
  if (reply.reachable) {
    say(
      `Saved. Kriko ${reply.version || ""} answered at ${reply.base}.`.replace(
        /\s+/g, " "),
      "ok");
  } else {
    say(
      `Saved ${reply.base}, but nothing answered there yet. ${reply.detail || ""}`
        .trim(),
      "warn");
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  void save(input.value);
});

resetButton.addEventListener("click", () => {
  input.value = "";
  void save("");
});

void load();

// ── the sites, and the one permission this page has to ask for ──────────
//
// Same rule as the address field: this page renders an answer it was given.
// The worker decides which sites the installed packs want, which of those the
// package already covers, and which are actually registered — see
// `syncSites` in background.js.
//
// The exception is `chrome.permissions.request`, which must be called *here*.
// Chrome requires it to happen inside a user gesture, and a gesture does not
// survive `sendMessage` — the worker cannot ask on our behalf even though it
// is the thing that knows what to ask for. So the worker supplies the list of
// origins and the click supplies the consent. The grant then fires
// `permissions.onAdded` in the worker, which re-syncs on its own; this page
// does not have to tell it to.

const sitesList = document.getElementById("sites");
const sitesStatus = document.getElementById("sites-status");
const grantButton = document.getElementById("grant");
const recheckButton = document.getElementById("recheck");

const SITE_WORD = {
  active: "reading",
  pending: "needs your permission",
  refused: "not usable",
};

let pendingOrigins = [];

function saySites(text, state) {
  sitesStatus.textContent = text;
  if (state) sitesStatus.dataset.state = state;
  else delete sitesStatus.dataset.state;
}

function renderSites(status) {
  sitesList.textContent = "";
  const sites = (status && status.sites) || [];
  pendingOrigins = sites
    .filter((row) => row.state === "pending" && row.pattern)
    .map((row) => row.pattern);
  // Gone, not greyed, when nothing waits: a lit-looking button with nothing
  // to allow read as a step the reader had missed.
  grantButton.disabled = pendingOrigins.length === 0;
  grantButton.hidden = pendingOrigins.length === 0;
  grantButton.textContent = pendingOrigins.length > 1
    ? `Allow ${pendingOrigins.length} pending sites`
    : "Allow the pending site";

  if (!sites.length) {
    const li = document.createElement("li");
    li.className = "empty";
    // Not an error: the packaged extension already reads the sites the packs
    // shipped with, and this list is only the ones it had to learn.
    li.textContent = status && status.error
      ? "Kriko has not been reachable; nothing new to report."
      : "Nothing beyond the sites this extension already covers.";
    sitesList.appendChild(li);
  }

  for (const row of sites) {
    const li = document.createElement("li");
    li.dataset.state = row.state;
    const name = document.createElement("span");
    name.className = "site-name";
    name.textContent = row.site;
    const word = document.createElement("span");
    word.className = "site-state";
    word.textContent = SITE_WORD[row.state] || row.state;
    li.append(name, word);
    if (row.detail) {
      const why = document.createElement("span");
      why.className = "site-detail";
      why.textContent = row.detail;
      li.appendChild(why);
    }
    sitesList.appendChild(li);
  }

  if (status && status.error) {
    saySites(
      status.code === "APP_NOT_RUNNING"
        ? "Kriko is not running; this list may be stale. "
          + "Start it, then Check again."
        : status.error,
      "warn");
  } else if (status) {
    saySites("", null);
  }
}

async function loadSites(fresh) {
  recheckButton.disabled = true;
  if (fresh) saySites("Asking Kriko…");
  const reply = await ask({ type: fresh ? "KRIKO_SYNC_SITES" : "KRIKO_SITE_STATUS" });
  recheckButton.disabled = false;
  if (!reply.ok) {
    saySites(reply.error, "error");
    return;
  }
  renderSites(reply.status);
}

grantButton.addEventListener("click", () => {
  // Nothing to do if the list is empty, and nothing to do if the reader says
  // no — a refused prompt leaves the site pending, which is the honest state.
  if (!pendingOrigins.length) return;
  chrome.permissions.request({ origins: pendingOrigins }, (granted) => {
    if (chrome.runtime.lastError) {
      saySites(chrome.runtime.lastError.message, "error");
      return;
    }
    if (!granted) {
      saySites("Left as it was; Kriko will not read those sites.", "warn");
      return;
    }
    // The worker's own `permissions.onAdded` does the registering; this only
    // needs to show the result, which is why it re-reads rather than acts.
    void loadSites(true);
  });
});

recheckButton.addEventListener("click", () => { void loadSites(true); });

void loadSites(false);

// ── the two clocks ──────────────────────────────────────────────────────
//
// Same rule again: the worker holds the verdict, this page renders it. The
// comparison was made against a floor the *app* stated, so nothing here
// knows which versions are compatible — which is what keeps this page from
// becoming a second, drifting copy of that rule.

const compatEl = document.getElementById("compat");

function renderCompat(compat) {
  if (!compat) {
    // Never having reached the app is not a version problem, and saying
    // "up to date" would be a claim we have no evidence for.
    compatEl.textContent =
      `Extension ${chrome.runtime.getManifest().version}. `
      + "The app has not answered, so there is nothing to compare.";
    delete compatEl.dataset.state;
    return;
  }
  if (compat.stale) {
    // The way out of an old extension is an update, and the reader is one
    // browser menu away from it. Naming that action is the whole difference
    // between a sentence they can act on and one that only says what is
    // wrong: the copy this page must not point at is the app's own staged
    // one, which is the install path this release turned off.
    compatEl.textContent =
      `Extension ${compat.running} is older than the ${compat.minimum} this `
      + "app needs. Update Kriko from the Chrome Web Store: yours is out of "
      + "date, not broken.";
    compatEl.dataset.state = "error";
    return;
  }
  compatEl.textContent =
    `Extension ${compat.running}; the app accepts ${compat.minimum} or newer.`;
  compatEl.dataset.state = "ok";
}

async function loadCompat() {
  const reply = await ask({ type: "KRIKO_COMPAT" });
  if (!reply.ok) {
    compatEl.textContent = reply.error;
    compatEl.dataset.state = "error";
    return;
  }
  renderCompat(reply.compat);
}

void loadCompat();

// ── the theme, remembered beside the address ────────────────────────────
//
// One key, `kriko.theme`, shared with the panel: choosing light or dark in
// either place is the choice the other one opens with. Absent, the system
// preference decides — and the stylesheet already paints that before this
// file has read anything.

const THEME_KEY = "kriko.theme";
const themeButton = document.getElementById("theme");

const SUN_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="M4.9 4.9 6.3 6.3" /><path d="M17.7 17.7l1.4 1.4" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="M4.9 19.1 6.3 17.7" /><path d="M17.7 6.3l1.4-1.4" /></svg>';
const MOON_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></svg>';

function prefersLight() {
  return Boolean(window.matchMedia
    && window.matchMedia("(prefers-color-scheme: light)").matches);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const light = theme === "light";
  // The icon is the way out of the theme the page is in, so it names the
  // action rather than the state.
  const label = light ? "Switch to dark theme" : "Switch to light theme";
  themeButton.innerHTML = light ? MOON_ICON : SUN_ICON;
  themeButton.setAttribute("aria-label", label);
  themeButton.title = label;
  themeButton.setAttribute("aria-pressed", light ? "true" : "false");
}

function toggleTheme() {
  const now = document.documentElement.dataset.theme || (prefersLight() ? "light" : "dark");
  const next = now === "light" ? "dark" : "light";
  applyTheme(next);
  try {
    chrome.storage?.local?.set?.({ [THEME_KEY]: next }, () => { void chrome.runtime.lastError; });
  } catch (_) {
    // A browser without local storage keeps the choice for this tab only.
  }
}

applyTheme(prefersLight() ? "light" : "dark");
themeButton.addEventListener("click", toggleTheme);
try {
  chrome.storage?.local?.get?.([THEME_KEY], (bag) => {
    const saved = bag?.[THEME_KEY];
    if (saved === "light" || saved === "dark") applyTheme(saved);
  });
} catch (_) { /* follow the system, as above */ }

// ── the motion profile, remembered beside the theme ─────────────────────
//
// One key, `kriko.motion`, shared with the panel: Calm / Standard / Vivid in
// either place is the profile the other opens with. Standard is the default,
// and the stylesheet already paints it before this file has read anything.
// The profile is only a `data-motion` attribute on the root — one mechanism,
// not a rule per transition — so the whole page answers to it at once.

const MOTION_KEY = "kriko.motion";
const MOTION_PROFILES = ["calm", "standard", "vivid"];
const motionGroup = document.getElementById("motion");

function applyMotion(profile) {
  const chosen = MOTION_PROFILES.includes(profile) ? profile : "standard";
  document.documentElement.dataset.motion = chosen;
  if (!motionGroup) return;
  for (const button of motionGroup.querySelectorAll(".motion-btn")) {
    button.setAttribute("aria-pressed", button.dataset.motion === chosen ? "true" : "false");
  }
}

function chooseMotion(profile) {
  applyMotion(profile);
  try {
    chrome.storage?.local?.set?.({ [MOTION_KEY]: profile }, () => { void chrome.runtime.lastError; });
  } catch (_) {
    // A browser without local storage keeps the choice for this tab only.
  }
}

applyMotion("standard");
if (motionGroup) {
  motionGroup.addEventListener("click", (event) => {
    const button = event.target.closest ? event.target.closest(".motion-btn") : null;
    if (button) chooseMotion(button.dataset.motion);
  });
}
try {
  chrome.storage?.local?.get?.([MOTION_KEY], (bag) => {
    if (MOTION_PROFILES.includes(bag?.[MOTION_KEY])) applyMotion(bag[MOTION_KEY]);
  });
} catch (_) { /* standard, as above */ }

// The panel may change the profile while this page is open; follow it so the
// two surfaces stay in step without a reload.
try {
  chrome.storage?.onChanged?.addListener?.((changes, area) => {
    if (area !== "local" || !(MOTION_KEY in changes)) return;
    const saved = changes[MOTION_KEY].newValue;
    applyMotion(MOTION_PROFILES.includes(saved) ? saved : "standard");
  });
} catch (_) { /* no change feed; the stored value still lands on load */ }

// ── a ripple under the pointer ──────────────────────────────────────────
//
// A CSS :active is a state, not a press: it cannot start where the pointer
// is or fade from it. One listener appends a dot; the animation removes it.

function reducedMotion() {
  return Boolean(window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

document.addEventListener("pointerdown", (event) => {
  if (reducedMotion() || typeof event.clientX !== "number") return;
  const dot = document.createElement("span");
  dot.className = "page-ripple";
  dot.style.left = event.clientX + "px";
  dot.style.top = event.clientY + "px";
  document.body.appendChild(dot);
  dot.addEventListener("animationend", () => dot.remove());
});
