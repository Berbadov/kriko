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
