// "Why did Kriko say that?" — the engine's own comparison, on a press.
//
// `POST /api/diagnose/identity` (`analyze.py:610-671`) runs the same
// adapt-then-lookup call `/api/analyze` answered through and returns the trace
// instead of the claims: the adapter that claimed the page, the identity it
// read, the labels no rule claimed, each key's supplied-against-held reading,
// and the sentence the engine would say next. It writes no history and runs no
// model, which is what makes it honest to offer.
//
// Three rules hold everywhere below: the press exists only where the verdict is
// somebody's doubt, it is asked for **only** on a press (never on mount, never
// on a poll), and nothing is drawn that the response did not carry.
const test = require("node:test");
const assert = require("node:assert/strict");
const { loadPanel } = require("./hover_lite_harness.js");

const ENTRY = (result) => ({
  ok: true,
  result: {
    lookup_id: "l1", claims: [], coverage: "PROBABLE_MATCH",
    identity: { make: "volkswagen" }, context: {}, packs: [], app_route: "result/l1",
    ...result,
  },
  listing: { title: "2014 Volkswagen Golf" },
  fetchedAt: Date.now(),
});

const PROBABLE = ENTRY({
  verdict: "probably", score: 0.58,
  considered: [{ subject_id: "s1", pack_id: "org.kriko.cars", label: "Golf VII EA211 105 hp",
    score: 0.58, keys: [{ key: "make", how: "exact", score: 1 }] }],
  next_step: { action: "confirm", subject_id: "s1", say: "Is that the same one?" },
});

const DIAGNOSIS = {
  adapter: { id: "listing", site: "listing.example", source: "pack" },
  page: { identity: { make: "volkswagen", model: "golf" }, context: { usage_km: "190000" },
    kind: "car", unmapped_labels: ["Takasa Uygun", "Boyasız"] },
  outcome: { method: "narrowed", verdict: "probably", score: 0.58,
    coverage: "PROBABLE_MATCH", notes: "one key disagreed", flags: [], subjects: ["s1"] },
  considered: [{
    subject_id: "s1", pack_id: "org.kriko.cars", label: "Golf VII EA211 105 hp", score: 0.58,
    keys: [
      { key: "make", supplied: "volkswagen", held: "volkswagen", score: 1, weight: 1,
        how: "exact", why: "the page and the pack agree" },
      { key: "engine_code", supplied: "", held: "EA211", score: 0, weight: 1,
        how: "absent", why: "the page never printed an engine code" },
    ],
  }],
  next_step: { action: "confirm", subject_id: "s1", say: "Is that the same one?" },
};

function opened(entry, answer = () => ({ ok: true, diagnosis: DIAGNOSIS })) {
  const p = loadPanel({ workerResponse: (m) => (m.type === "DIAGNOSE_IDENTITY" ? answer(m) : { ok: true }) });
  p.openPanel();
  p.deliverEntry(entry);
  return p;
}

const card = (p) => p.shadow().querySelector(".lite-verdict");
const whyButton = (p) => p.shadow().querySelector(".lite-diagnosis-btn");
const detail = (p) => p.shadow().querySelector(".lite-diagnosis");
const asked = (p) => p.sent.filter((m) => m.type === "DIAGNOSE_IDENTITY");

test("a plain match is not offered a why", () => {
  const p = opened(ENTRY({ verdict: "recognised", score: 1,
    next_step: { action: "research", say: "Nothing installed covers it yet." } }));
  assert.ok(card(p), "the card itself should still be drawn");
  assert.equal(whyButton(p), null,
    "a debug affordance on the ordinary answer is one the reader learns to ignore");
});

for (const verdict of ["probably", "several", "unrecognised"]) {
  test(`a ${verdict} verdict offers the comparison, and nothing is asked until it is pressed`, () => {
    const p = opened(ENTRY({ ...PROBABLE.result, verdict, score: 0.3 }));
    assert.ok(whyButton(p), `${verdict} offered no way to ask why`);
    assert.equal(whyButton(p).textContent, "What was compared");
    assert.deepEqual(asked(p), [], "the comparison was fetched without a press");
    p.click(".lite-diagnosis-btn");
    assert.equal(asked(p).length, 1);
    assert.deepEqual({ ...asked(p)[0].payload }, { url: p.dom.window.location.href });
  });
}

test("the comparison is drawn per key, with what the page said against what the engine holds", () => {
  const p = opened(PROBABLE);
  p.click(".lite-diagnosis-btn");
  const box = detail(p);
  assert.ok(box, "nothing was drawn for the comparison");
  assert.equal(box.dataset.state, "done");
  const text = box.textContent;
  assert.match(text, /Read by/);
  assert.match(text, /listing · listing\.example · from an installed pack/);
  assert.match(text, /make volkswagen/);
  assert.match(text, /No rule claimed.*Takasa Uygun/);
  assert.match(text, /narrowed · one key disagreed/);
  assert.match(text, /Golf VII EA211 105 hp/);
  assert.match(text, /58%/);
  const keys = [...box.querySelectorAll(".lite-diagnosis-keys li")];
  assert.equal(keys.length, 2);
  assert.equal(keys[0].dataset.how, "exact");
  assert.match(keys[0].textContent, /volkswagen → volkswagen/);
  assert.match(keys[0].textContent, /the page and the pack agree/);
  assert.equal(keys[1].dataset.how, "absent");
  assert.match(keys[1].textContent, /not on the page → EA211/,
    "a key the page never carried is said, not guessed");
  assert.match(text, /Next.*Is that the same one\?/);
  // The verdict and its own sentence are still on the card above it.
  assert.match(card(p).textContent, /Probably this one/);
});

test("a response with nothing to compare says so instead of inventing a why", () => {
  const p = opened(ENTRY({ ...PROBABLE.result, verdict: "unrecognised", score: 0 }),
    () => ({ ok: true, diagnosis: {
      adapter: null, page: { url: "https://shop.example/p/1" },
      outcome: { method: "no_adapter", verdict: "unreadable", notes: "nothing reads this site" },
      considered: [],
      next_step: { action: "register_site", say: "Kriko cannot read this site yet." },
    } }));
  p.click(".lite-diagnosis-btn");
  const text = detail(p).textContent;
  assert.match(text, /nothing installed/);
  assert.match(text, /nothing: the engine had no candidate to compare/);
  assert.match(text, /nothing reads this site/);
  assert.doesNotMatch(text, /undefined|null/);
});

test("a comparison that fails is a sentence and a retry, not a broken card", () => {
  const p = opened(PROBABLE, () => ({ ok: false, code: "APP_NOT_RUNNING", error: "Kriko is not running." }));
  p.click(".lite-diagnosis-btn");
  assert.match(detail(p).textContent, /Kriko is not running\./);
  assert.equal(detail(p).dataset.state, "error");
  assert.match(card(p).textContent, /Probably this one/, "the verdict survived the failure");
  assert.equal(whyButton(p).textContent, "Try again");
  p.click(".lite-diagnosis-btn");
  assert.equal(asked(p).length, 2, "the retry did not ask again");
});

test("a new answer clears the comparison rather than attaching it to a new verdict", () => {
  const p = opened(PROBABLE);
  p.click(".lite-diagnosis-btn");
  assert.ok(detail(p));
  p.deliverEntry(ENTRY({ verdict: "unrecognised", score: 0,
    next_step: { action: "research", say: "Nothing matched." } }));
  assert.equal(detail(p), null, "an old comparison was shown beside a new verdict");
  assert.equal(whyButton(p).textContent, "What was compared");
});
