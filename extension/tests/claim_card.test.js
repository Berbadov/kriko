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

test("a single source says Source, and more than two fold away behind a count", () => {
  assert.equal(renderClaimCard(claim({ sources: [src(1)] })).querySelector(".lite-rc-label").textContent, "Source");
  const card = renderClaimCard(claim({ sources: [src(1), src(2), src(3), src(4)] }));
  assert.equal(card.querySelectorAll(".lite-rc-sources > .lite-rc-src").length, 2);
  const more = card.querySelector(".lite-rc-more");
  assert.equal(more.querySelector("summary").textContent, "2 more sources");
  assert.equal(more.querySelectorAll(".lite-rc-src").length, 2);
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
