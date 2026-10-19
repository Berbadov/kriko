// The renderers for the reader as a buyer: words and tones for what the app
// says, every value escaped, and an unknown verdict never drawn as good news.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

function load() {
  const dom = new JSDOM("<!doctype html><body></body>");
  const sandbox = { window: dom.window, document: dom.window.document, console };
  dom.window.__KrikoPanelIcons = { iconSvg: () => "", domainIconSvg: () => "" };
  vm.createContext(sandbox);
  // The pick's answer is drawn by the claim card's own rich-text renderer.
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "hover_lite", "claim_card.js"), "utf8"), sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "hover_lite", "buyer_card.js"), "utf8"), sandbox);
  return { B: dom.window.__KrikoBuyer, dom };
}
const { B, dom } = load();
const html = (markup) => { const div = dom.window.document.createElement("div"); div.innerHTML = markup; return div; };

const PRICE = { verdict: "lowest", price: 49.9, currency: "EUR", summary: "The lowest Kriko has seen in 40 days.",
  series: [{ price: 60 }, { price: 55 }, { price: 49.9 }], discount: null, elsewhere: [] };

test("a price reads as a figure, a verdict word and a line", () => {
  const card = html(B.renderBuyerCard({ price: PRICE, watch: null }, {}));
  assert.match(card.textContent, /49\.9 EUR/);
  assert.equal(card.querySelector(".lite-buy-chip").textContent, "Lowest seen");
  assert.equal(card.querySelector(".lite-buy-chip").dataset.tone, "good");
  assert.ok(card.querySelector("svg.lite-buy-line polyline"));
  assert.match(card.querySelector("svg").getAttribute("aria-label"), /from 60 to 49\.9/);
});

test("a page that says nothing draws nothing", () => {
  assert.equal(B.renderBuyerCard(null, {}), "");
  assert.equal(B.renderBuyerCard({ price: null, fit: null, audit: null, watch: null }, {}), "");
});

test("a first sighting and thin history are muted, never reassuring", () => {
  for (const verdict of ["first", "thin"]) {
    const card = html(B.renderPrice({ ...PRICE, verdict, series: [] }));
    assert.equal(card.querySelector(".lite-buy-chip").dataset.tone, "muted");
  }
  const unknown = html(B.renderPrice({ ...PRICE, verdict: "mystery", series: [] }));
  assert.equal(unknown.querySelector(".lite-buy-chip"), null, "an unknown verdict gets no chip at all");
});

test("a discount the history cannot support is drawn as a warning with the app's own sentence", () => {
  const card = html(B.renderPrice({ ...PRICE, verdict: "usual", discount: "inflated",
    discount_summary: "The old price looks invented." }));
  assert.equal(card.querySelector(".lite-buy-discount").dataset.tone, "bad");
  assert.match(card.querySelector(".lite-buy-discount").textContent, /invented/);
});

test("a cheaper shop is named only when it is meaningfully cheaper", () => {
  const card = html(B.renderPrice({ ...PRICE, elsewhere: [
    { host: "other.test", url: "https://other.test/p", price: 40, currency: "EUR" },
    { host: "near.test", url: "https://near.test/p", price: 49, currency: "EUR" }] }));
  const names = [...card.querySelectorAll(".lite-buy-elsewhere li")].map((li) => li.textContent.trim());
  assert.equal(names.length, 1);
  assert.match(names[0], /other\.test 40 EUR/);
  assert.equal(card.querySelector("a").rel, "noopener noreferrer");
});

test("what fits and what breaks the reader's needs are told apart", () => {
  const bad = html(B.renderFit({ score: 10, breaks: ["avoid"], reasons: [{ kind: "avoid", message: "mentions Acme, which you avoid" }] }));
  assert.equal(bad.querySelector(".lite-buy-fit").dataset.tone, "bad");
  assert.match(bad.textContent, /Not for you/);
  const good = html(B.renderFit({ score: 70, breaks: [], reasons: [{ kind: "must", message: "says it has usb-c" }] }));
  assert.equal(good.querySelector(".lite-buy-fit").dataset.tone, "good");
  assert.equal(B.renderFit({ score: 50, breaks: [], reasons: [] }), "");
});

test("the listing check opens on a seller warning and lists unbacked claims honestly", () => {
  const audit = { seller: { level: "red", notes: ["asks for payment by bitcoin"] },
    reviews: { doubtful: true, adjusted: 4.1, notes: ["4.9 from only 7 ratings is mostly noise"] },
    claims: { meter: 0, items: [{ kind: "water", phrase: "waterproof", status: "unbacked", why: "no water-resistance rating on the page" },
      { kind: "best", phrase: "best", status: "puffery", why: "a superlative" }] } };
  const card = html(B.renderAudit(audit));
  assert.equal(card.querySelector("details").hasAttribute("open"), true);
  const text = card.textContent;
  assert.match(text, /Seller warning/);
  assert.match(text, /“waterproof”: no water-resistance rating/);
  assert.match(text, /0% of claims backed/);
  assert.equal(B.renderAudit({ seller: { level: "green" }, reviews: {}, claims: { items: [] } }), "");
});

test("every value from the app is escaped", () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const card = html(B.renderBuyerCard({ price: { ...PRICE, summary: hostile, currency: hostile },
    fit: { score: 10, breaks: ["avoid"], reasons: [{ kind: "avoid", message: hostile }] },
    audit: { seller: { level: "amber", notes: [hostile] }, reviews: {}, claims: { items: [] } },
    watch: { watch_id: hostile, target: 5, currency: "EUR" } }, {}));
  assert.equal(card.querySelector("img"), null);
  assert.equal(html(B.renderDue([{ purchase_id: hostile, name: hostile }], {})).querySelector("img"), null);
  assert.equal(html(B.renderPick({ picked: { name: hostile, price: 1, currency: "" }, ranked: [{ name: hostile, score: 1 }],
    confidence: "clear", gave_up: [hostile], switch_if: [hostile], check_first: [hostile] }, {})).querySelector("img"), null);
});

test("a watched page shows its terms and a way to stop; an unwatched one a way to start", () => {
  const watching = html(B.renderBuyerCard({ price: PRICE, watch: { watch_id: "w1", target: 40, currency: "EUR" } }, {}));
  assert.match(watching.textContent, /Watching · alert at 40 EUR or less/);
  assert.equal(watching.querySelector('[data-act="unwatch"]').dataset.id, "w1");
  const idle = html(B.renderBuyerCard({ price: PRICE, watch: null }, {}));
  assert.ok(idle.querySelector('[data-act="watch-open"]'));
  const form = html(B.renderBuyerCard({ price: PRICE, watch: null }, { watchForm: true }));
  assert.equal(form.querySelector('input[name="target"]').value, "44", "the suggestion is ten percent under the price");
});

test("a purchase that is due asks glad, fine or regret, and regret asks why", () => {
  const due = [{ purchase_id: "p1", name: "Kettle" }];
  const ask = html(B.renderDue(due, {}));
  assert.match(ask.textContent, /Did your Kettle hold up\?/);
  assert.deepEqual([...ask.querySelectorAll("[data-act]")].map((b) => b.dataset.act),
    ["answer", "answer", "regret", "snooze"]);
  const why = html(B.renderDue(due, { regretFor: "p1" }));
  assert.ok(why.querySelector('form[data-act="regret-save"] input[name="reason"]'));
  assert.equal(B.renderDue([], {}), "");
});

test("the pick names a winner, its confidence, what it costs and what would change it", () => {
  const card = html(B.renderPick({
    picked: { name: "Kettle B", price: 66, currency: "EUR", strengths: ["the cheapest of these"] },
    confidence: "close", gave_up: ["costs more"], switch_if: ["Kettle A falls to about 66 EUR"],
    check_first: ["lid"], ranked: [{ name: "Kettle B", score: 60 }, { name: "Kettle A", score: 55 }] }, {}));
  assert.match(card.querySelector(".lite-pick-winner").textContent, /Kettle B/);
  assert.match(card.querySelector(".lite-pick-winner").textContent, /A close call/);
  assert.match(card.textContent, /It costs you:[\s\S]*costs more/);
  assert.match(card.textContent, /Switch if:[\s\S]*falls to about 66 EUR/);
  assert.deepEqual([...card.querySelectorAll('[data-act="advise"]')].map((b) => b.dataset.mode),
    ["pick", "debate", "tco", "timing"]);
});

test("a shortlist with nothing to rank says what to do, and a running agent disables the buttons", () => {
  assert.match(html(B.renderPick({ picked: null, ranked: [] }, {})).textContent, /at least two products/);
  const running = html(B.renderPick({ picked: { name: "A" }, ranked: [], confidence: "clear" },
    { advice: { state: "running", mode: "debate" } }));
  assert.ok([...running.querySelectorAll('[data-act="advise"]')].every((b) => b.disabled));
  assert.match(running.textContent, /Your agent is working/);
  const done = html(B.renderPick({ picked: { name: "A" }, ranked: [], confidence: "clear" },
    { advice: { state: "done", mode: "pick", answer: "**Buy: A** now" } }));
  assert.equal(done.querySelector(".lite-pick-answer strong").textContent, "Buy: A");
});

test("the guard card names a stop or a check, and nothing for a go", () => {
  assert.equal(B.renderGuard({ verdict: "go", findings: [] }), "");
  const stop = html(B.renderGuard({ verdict: "stop", findings: [
    { severity: "stop", message: "You researched A, but this is B." }, { severity: "ok", message: "returns" }] }));
  assert.match(stop.textContent, /Stop and check before paying/);
  assert.equal(stop.querySelectorAll("li").length, 1, "an ok finding is not worth interrupting for");
});
