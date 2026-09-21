// The two matchers have to agree, and for a long time they did not.
//
// A site's adapter carries `match` patterns. Chrome reads them to decide where
// to inject the content script, and `adapterFor` in background.js reads the
// same strings to decide which adapter a scraped page belongs to. Chrome
// applies the documented match-pattern semantics; background.js applied a
// hand-rolled glob. For the one pattern shape `app/sites.py` actually
// generates — `*://*.<site>/*` — the two disagree on the bare host, because a
// plain glob reads `*.` as "a subdomain, and there must be one".
//
// The reader's side of that disagreement: add a site, open a listing on it at
// its bare host, and the panel comes up knowing nothing. Chrome injected the
// script, the page was scraped and handed over, and the worker then found no
// adapter for the very URL Chrome had matched.
//
// Why the existing suite passed throughout: `background_sites.test.js` builds
// its fixtures with `match: ["*<site>/*"]`, which has no `*.` host prefix and
// so matches the bare host under either reading. The fixture had drifted from
// the data, and the gap between them was exactly the bug. So this file takes
// the pattern from `app/sites.py` rather than writing one down — a test that
// spells the pattern out itself can drift the same way.
const test = require("node:test");
const assert = require("node:assert");

const fs = require("node:fs");
const path = require("node:path");

const { loadBackground } = require("./background_harness.js");

const SITES_PY = path.join(__dirname, "..", "..", "src", "app", "sites.py");

// Invented, so that passing cannot depend on which packs are installed.
const SITE = "otoparca.example";

/** Every default match pattern `app/sites.py` writes, with the site filled in.
 *
 * Both the generator (`match = [f"*://*.{site}/*"]`) and the brief the agent
 * is handed (`"match": ["*://*.{site}/*"]`) state the shape, and they are
 * required to state the same one — if a third shape appears, this picks it up
 * and the assertions below run against it too.
 */
function generatedPatterns() {
    const source = fs.readFileSync(SITES_PY, "utf8");
    const found = new Set();
    for (const [, pattern] of source.matchAll(/"(\*:\/\/[^"]*\{site\}[^"]*)"/g)) {
        found.add(pattern.replace("{site}", SITE));
    }
    assert.ok(
        found.size > 0,
        `no match-pattern template found in ${SITES_PY} — has it been renamed? ` +
        "If sites.py no longer generates the patterns, this test needs a new source.",
    );
    return [...found];
}

test("the worker matches a generated pattern the way Chrome does", () => {
    const { sandbox } = loadBackground();
    const { globToRegExp } = sandbox;
    assert.equal(typeof globToRegExp, "function",
                 "globToRegExp is gone — this test reads it off the worker");

    for (const pattern of generatedPatterns()) {
        const matches = (url) => globToRegExp(pattern).test(url);

        // The regression. A reader who adds a site and opens a listing on it
        // is on the bare host far more often than not.
        assert.ok(matches(`https://${SITE}/ilan/1`),
                  `${pattern} must match the bare host`);

        // Still true, and the half that always worked.
        assert.ok(matches(`https://www.${SITE}/ilan/1`),
                  `${pattern} must match a subdomain`);
        assert.ok(matches(`https://a.b.${SITE}/ilan/1`),
                  `${pattern} must match a nested subdomain`);
        assert.ok(matches(`http://${SITE}/ilan/1`),
                  `${pattern} must match either scheme`);

        // And the half that matters more than the rest put together: widening
        // the host rule must not widen it to somebody else's site. A worker
        // that reads a page it was never granted is worse than one that reads
        // nothing, so these are the assertions to keep if any are dropped.
        assert.ok(!matches(`https://not${SITE}/ilan/1`),
                  `${pattern} must not match a host that merely ends the same way`);
        assert.ok(!matches(`https://evil-${SITE}/ilan/1`),
                  `${pattern} must not match a hyphenated lookalike`);
        assert.ok(!matches(`https://${SITE}.evil.test/ilan/1`),
                  `${pattern} must not match a host that merely contains it`);
    }
});

test("adapterFor picks the adapter up on the bare host", () => {
    const { sandbox } = loadBackground();
    const [pattern] = generatedPatterns();
    const adapter = { id: "otoparca", site: SITE, match: [pattern], fields: {} };

    // Through `adapterFor` rather than the matcher alone: this is the call
    // that returned null, and the null is what the reader saw as an empty
    // panel on a site they had just added.
    assert.equal(sandbox.adapterFor(`https://${SITE}/ilan/1`, [adapter]), adapter);
    assert.equal(sandbox.adapterFor(`https://www.${SITE}/ilan/1`, [adapter]), adapter);
    assert.equal(sandbox.adapterFor("https://elsewhere.example/ilan/1", [adapter]), null);
});
