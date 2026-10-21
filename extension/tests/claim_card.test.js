// A finding reads claim first, then its source and quote (#262).
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const dom = new JSDOM("<!doctype html><body></body>");
const sandbox = { window: dom.window, document: dom.window.document, console };
dom.window.__KrikoPanelIcons = { iconSvg: () => "", domainIconSvg: () => "" };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "hover_lite", "claim_card.js"), "utf8"), sandbox);
const { renderClaimCard } = dom.window.__KrikoPanelClaimCard;

const claim = (extra = {}) => ({
  claim_id: "c1", pack_id: "p", title: "Timing chain rattles", body: "The tensioner wears.",
  severity: "high", strength: "reported", domain: "engine", ...extra,
});
const src = (n, extra = {}) => ({ url: `https://s${n}.example/page`, domain: `s${n}.example`, quote: `Quote number ${n}.`, ...extra });

test("the claim is the headline and its first quote sits under it before the card is opened", () => {
  const card = renderClaimCard(claim({ sources: [src(1), src(2)] }));
  const head = card.querySelector(".lite-rc-head");
  assert.equal(head.querySelector(".lite-rc-title").textContent, "Timing chain rattles");
  const peek = head.querySelector(".lite-rc-peek");
  assert.match(peek.textContent, /s1\.example/);
  assert.match(peek.textContent, /Quote number 1\./);
  assert.doesNotMatch(peek.textContent, /Quote number 2/, "only the first quote is previewed");
  // Claim before evidence, in reading order.
  assert.ok(head.querySelector(".lite-rc-title").compareDocumentPosition(peek) & dom.window.Node.DOCUMENT_POSITION_FOLLOWING);
});

test("opened, the claim's own words come first and each source shows its quote above its address", () => {
  const card = renderClaimCard(claim({ sources: [src(1), src(2)] }), { open: true });
  const body = card.querySelector(".lite-rc-body");
  const order = [...body.children].map((el) => el.className.split(" ")[0]);
  assert.ok(order.indexOf("lite-rc-text") < order.indexOf("lite-rc-sources"), order.join(","));
  const figures = body.querySelectorAll(".lite-rc-src");
  assert.equal(figures.length, 2);
  assert.equal(figures[0].children[0].tagName, "BLOCKQUOTE");
  assert.equal(figures[0].children[1].tagName, "FIGCAPTION");
  const link = figures[0].querySelector("a");
  assert.equal(link.href, "https://s1.example/page");
  assert.equal(link.rel, "noopener noreferrer");
  assert.equal(link.target, "_blank");
  assert.equal(body.querySelector(".lite-rc-label").textContent, "Sources · 2");
});

test("a single source says Source, and each source is one chip with its quote kept closed", () => {
  assert.equal(renderClaimCard(claim({ sources: [src(1)] })).querySelector(".lite-rc-label").textContent, "Source");
  const card = renderClaimCard(claim({ sources: [src(1), src(2), src(3), src(4)] }));
  const chips = card.querySelectorAll(".lite-rc-chips > .lite-chip");
  assert.equal(chips.length, 4, "every source is a chip; none folds away");
  assert.equal(chips[0].querySelector(".lite-chip-site").textContent, "s1.example");
  assert.ok([...card.querySelectorAll(".lite-rc-src")].every((figure) => figure.hidden), "no quote is open until a chip is pressed");
});

test("a chip opens its own quote, one at a time, and Escape closes it", () => {
  const card = renderClaimCard(claim({ sources: [src(1), src(2)] }), { open: true });
  const [one, two] = card.querySelectorAll(".lite-chip");
  const figure = (chip) => card.querySelector("#" + chip.getAttribute("aria-controls"));
  one.click();
  assert.equal(one.getAttribute("aria-expanded"), "true");
  assert.equal(figure(one).hidden, false);
  assert.match(figure(one).textContent, /Quote number 1\./);
  two.click();
  assert.equal(figure(one).hidden, true, "the first closes when the second opens");
  assert.equal(figure(two).hidden, false);
  two.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.equal(figure(two).hidden, true);
  assert.equal(two.getAttribute("aria-expanded"), "false");
  one.click(); one.click();
  assert.equal(figure(one).hidden, true, "a second press on the same chip closes it");
});

test("a chip draws the mark for where the engine stands the source, and none when it could not", () => {
  const card = renderClaimCard(claim({ sources: [
    src(1, { standing: "trusted", tier: "manufacturer" }),
    src(2, { standing: "low", tier: "forum_ugc" }),
    src(3),
    src(4, { standing: "constructor" }),
  ] }));
  const chips = [...card.querySelectorAll(".lite-chip")];
  assert.deepEqual(chips.map((chip) => chip.dataset.standing), ["trusted", "low", undefined, undefined]);
  assert.equal(chips[2].querySelector(".lite-chip-glyph"), null, "no standing, no mark");
  assert.match(chips[0].getAttribute("aria-label"), /trusted/);
  assert.match(card.querySelectorAll(".lite-rc-src")[1].textContent, /Low · forum ugc/);
});

test("a source that is not a web address is shown as text and never becomes a link", () => {
  const card = renderClaimCard(claim({ sources: [{ url: "javascript:alert(1)", domain: "evil.example", quote: "Hello" }] }));
  assert.equal(card.querySelector(".lite-rc-src a"), null);
  assert.match(card.querySelector(".lite-rc-src figcaption").textContent, /evil\.example/);
});

test("what a source or a claim says can never become markup", () => {
  const card = renderClaimCard(claim({
    title: "<img src=x onerror=alert(1)>",
    sources: [src(1, { quote: "<script>alert(1)</script>", domain: "<b>x</b>" })],
  }), { open: true });
  assert.equal(card.querySelector("img, script, b"), null);
  assert.match(card.querySelector(".lite-rc-src blockquote").textContent, /<script>alert\(1\)<\/script>/);
});

test("a source that disputes the claim says so", () => {
  const card = renderClaimCard(claim({ sources: [src(1, { stance: "refutes" })] }));
  assert.equal(card.querySelector(".lite-rc-src").dataset.stance, "refutes");
  assert.match(card.querySelector(".lite-rc-src-note").textContent, /disputes this/);
});

test("a claim with no sources has no source block and no preview", () => {
  const card = renderClaimCard(claim({ sources: [] }));
  assert.equal(card.querySelector(".lite-rc-sources"), null);
  assert.equal(card.querySelector(".lite-rc-peek"), null);
});

test("a source with no quote still shows where it is from, and is not previewed", () => {
  const card = renderClaimCard(claim({ sources: [{ url: "https://s.example/a", domain: "s.example" }] }));
  assert.equal(card.querySelector(".lite-rc-peek"), null);
  assert.equal(card.querySelector(".lite-rc-src blockquote"), null);
  assert.equal(card.querySelector(".lite-rc-src a").href, "https://s.example/a");
});
