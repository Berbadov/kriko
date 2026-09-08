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
  input.value = reply.stored;
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
  grantButton.disabled = pendingOrigins.length === 0;
  grantButton.textContent = pendingOrigins.length > 1
    ? `Allow ${pendingOrigins.length} pending sites`
    : "Allow the pending site";

  if (!sites.length) {
    const li = document.createElement("li");
    li.className = "empty";
    // Not an error: the packaged extension already reads the sites the packs
    // shipped with, and this list is only the ones it had to learn.
    li.textContent = status && status.error
      ? "Kriko has not been reachable, so there is nothing new to report yet."
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
        ? "Kriko is not running, so this list is the last one it gave us. "
          + "Start the app and press Check again."
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
      saySites("Left as it was — Kriko will not read those sites.", "warn");
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
      + "The app has not answered yet, so there is nothing to compare it to.";
    delete compatEl.dataset.state;
    return;
  }
  if (compat.stale) {
    compatEl.textContent =
      `Extension ${compat.running} is older than the ${compat.minimum} this `
      + "app needs. Open Kriko's Extension page and load the copy it wrote — "
      + "yours is out of date, not broken.";
    compatEl.dataset.state = "error";
    return;
  }
  compatEl.textContent =
    `Extension ${compat.running}, and the app accepts ${compat.minimum} or `
    + "newer. Nothing to do.";
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
