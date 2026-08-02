// Panel footer (deploy-staleness guard, B15): the results panel must name the
// backend build that answered, so a stale deploy is visible to anyone looking
// at the panel instead of silently serving pre-fix behaviour.
const test = require("node:test");
const assert = require("node:assert");

const { loadPanel } = require("./hover_lite_harness.js");

test("footer is hidden before any analysis result", () => {
  const p = loadPanel();
  p.openPanel();
  assert.equal(p.footer().hidden, true);
});

test("footer shows the backend short commit from result.build", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({
    ok: true,
    result: {
      risks: [],
      summary: "s",
      build: { commit: "a0b39d1", build_time: "2026-07-22T15:02:31+03:00" },
    },
  });

  const footer = p.footer();
  assert.equal(footer.hidden, false);
  assert.equal(footer.textContent, "api · a0b39d1");
});

test("a pre-stamp backend (no `build` field) renders as 'api · unknown'", () => {
  // The B15 incident shape: the serving backend predates stamping. The footer
  // must still render — "unknown" is itself the tell, not a blank panel.
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({ ok: true, result: { risks: [], summary: "s" } });

  const footer = p.footer();
  assert.equal(footer.hidden, false);
  assert.equal(footer.textContent, "api · unknown");
});

test("footer hides again when the analysis fails", () => {
  const p = loadPanel();
  p.openPanel();
  p.deliverEntry({
    ok: true,
    result: { risks: [], summary: "s", build: { commit: "a0b39d1" } },
  });
  assert.equal(p.footer().hidden, false);

  p.deliverEntry({ ok: false, error: "Network error" });
  assert.equal(p.footer().hidden, true);
});
