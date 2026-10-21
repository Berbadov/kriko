// The panel lets the page show through, and a setting makes it opaque (#260).
//
// The reader's limits: "readable over both light and dark pages (contrast
// checked on each), and a setting turns it opaque". The contrast is computed
// here from the stylesheet's own numbers, so retuning the glass cannot quietly
// make the text unreadable over the page it sits on.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { loadPanel } = require("./hover_lite_harness.js");
const { loadOptions, settle } = require("./options_harness.js");

const CSS = fs.readFileSync(path.join(__dirname, "..", "hover_lite", "hover_lite.css"), "utf8");

// ── reading the tokens off the sheet ────────────────────────────────────
const token = (name) => {
  const hit = new RegExp(`${name}:\\s*([^;]+);`).exec(CSS);
  assert.ok(hit, `${name} is not declared in hover_lite.css`);
  return hit[1].trim();
};
const channels = (text) => text.split(",").map((n) => Number(n));
const hex = (text) => {
  const h = /^#([0-9a-f]{6})$/i.exec(text);
  assert.ok(h, `${text} is not a six-digit colour`);
  return [0, 2, 4].map((i) => parseInt(h[1].slice(i, i + 2), 16));
};
const brightnessOf = (backdrop) => {
  const hit = /brightness\(([\d.]+)\)/.exec(backdrop);
  return hit ? Number(hit[1]) : 1;
};

// WCAG 2 relative luminance and contrast ratio.
const lin = (v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

// What the reader sees behind a line of text: the panel colour at its alpha,
// over the page after the backdrop has dimmed it. The page is uniform here
// because blur turns whatever is behind into its average; the extremes are the
// worst averages a page can have.
function behindText({ rgb, alpha, brightness, page }) {
  const seen = page.map((v) => v * brightness);
  return rgb.map((v, i) => alpha * v + (1 - alpha) * seen[i]);
}

const THEMES = {
  dark: {
    rgb: channels(token("--bg-panel-rgb")),
    alpha: Number(token("--glass-panel-alpha")),
    brightness: brightnessOf(token("--glass-backdrop")),
    ink: { "--fg": hex(token("--fg")), "--fg-body": hex(token("--fg-body")), "--fg-muted": hex(token("--fg-muted")) },
  },
  light: {
    rgb: channels(token("--light-bg-panel-rgb")),
    alpha: Number(token("--light-glass-panel-alpha")),
    brightness: brightnessOf(token("--light-glass-backdrop")),
    ink: { "--fg": hex(token("--light-fg")), "--fg-body": hex(token("--light-fg-body")), "--fg-muted": hex(token("--light-fg-muted")) },
  },
};
const PAGES = { white: [255, 255, 255], black: [0, 0, 0], grey: [128, 128, 128], "listing yellow": [241, 214, 138] };

for (const [name, theme] of Object.entries(THEMES)) {
  for (const [pageName, page] of Object.entries(PAGES)) {
    test(`text stays at 4.5:1 or better on the ${name} panel over a ${pageName} page`, () => {
      const behind = behindText({ ...theme, page });
      for (const [ink, colour] of Object.entries(theme.ink)) {
        const got = ratio(colour, behind);
        assert.ok(got >= 4.5, `${ink} on the ${name} glass over ${pageName} is ${got.toFixed(2)}:1`);
      }
    });
  }
  test(`the ${name} panel really is translucent`, () => {
    assert.ok(theme.alpha < 1, "an alpha of 1 is not glass");
    assert.ok(theme.alpha >= 0.5, "below half, the page is the panel's background and not its backdrop");
  });
}

test("the opaque setting comes after both light mappings, so it wins over either", () => {
  const solid = CSS.indexOf(':host([data-glass="solid"])');
  const lightMedia = CSS.indexOf('--glass-panel-alpha: var(--light-glass-panel-alpha)');
  const lightExplicit = CSS.lastIndexOf('--glass-panel-alpha: var(--light-glass-panel-alpha)');
  assert.ok(solid > 0 && lightMedia > 0 && lightExplicit > lightMedia);
  assert.ok(solid > lightExplicit, "a light panel would keep its glass under the opaque setting");
  const block = /:host\(\[data-glass="solid"\]\)\s*\{([^}]*)\}/.exec(CSS)[1];
  assert.match(block, /--glass-panel-alpha:\s*1;/);
  assert.match(block, /--glass-backdrop:\s*none;/);
});

// ── the panel follows the setting ───────────────────────────────────────
const hostOf = (p) => p.dom.window.document.querySelector("kriko-panel-host");

test("the panel is glass until the reader says otherwise", () => {
  const p = loadPanel();
  p.openPanel();
  assert.equal(hostOf(p).dataset.glass, "glass");
});

test("a stored choice of solid opens the panel opaque", () => {
  const p = loadPanel();
  p.local["kriko.glass"] = "solid";
  p.openPanel();
  assert.equal(hostOf(p).dataset.glass, "solid");
});

test("changing the setting while the panel is open reaches it without a reload", () => {
  const p = loadPanel();
  p.openPanel();
  p.setLocal("kriko.glass", "solid");
  assert.equal(hostOf(p).dataset.glass, "solid");
  p.setLocal("kriko.glass", "glass");
  assert.equal(hostOf(p).dataset.glass, "glass");
});

test("a value nobody wrote is glass, never a broken panel", () => {
  const p = loadPanel();
  p.local["kriko.glass"] = "frosted-maybe";
  p.openPanel();
  assert.equal(hostOf(p).dataset.glass, "glass");
});

// ── the options page is where the reader changes it ─────────────────────
test("the options page offers the opaque panel and remembers the choice", async () => {
  const page = loadOptions({ local: { "kriko.glass": "solid" } });
  await settle();
  const box = page.document.getElementById("panel-solid");
  assert.equal(box.checked, true, "a stored solid is shown as ticked");
  box.checked = false;
  box.dispatchEvent(new page.window.Event("change"));
  assert.equal(page.bag["kriko.glass"], "glass");
  box.checked = true;
  box.dispatchEvent(new page.window.Event("change"));
  assert.equal(page.bag["kriko.glass"], "solid");
});
