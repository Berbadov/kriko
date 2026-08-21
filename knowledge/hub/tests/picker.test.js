// The Models tab picker: make → model → generation → task → run.
//
// The rule the whole flow exists to enforce: Kriko's model keys carry a
// generation (`clio_5`), and the demand queue hands us scraped display slugs
// ("VW CC 1.4 TSI" → `vw_cc_1_4_tsi`). So an onboarding run is only meaningful
// once a generation has been researched and picked. Offering "Onboard →"
// before that arms a run that cannot succeed — it would onboard the model key
// `volkswagen_vw_cc_1_4_tsi`, which is not a car.
const { test } = require("node:test");
const assert = require("node:assert");
const { loadHub } = require("./harness");

async function boot(opts) {
  const hub = await loadHub(opts);
  await hub.tick(150);
  return hub;
}

test("step 1 lists demand-ranked makes", async () => {
  const hub = await boot();
  assert.equal(hub.chips("#pick-make").length, 2);
  assert.match(hub.$("#pick-make").textContent, /Volkswagen/);
  assert.equal(hub.$("#step-model").hidden, true);
  hub.close();
});

test("picking a make reveals its models", async () => {
  const hub = await boot();
  await hub.clickChip("#pick-make", 0);
  assert.equal(hub.$("#step-model").hidden, false);
  assert.equal(hub.chips("#pick-model").length, 2);
  hub.close();
});

test("a model with no researched lineup cannot arm an onboard run", async () => {
  const hub = await boot();
  await hub.clickChip("#pick-make", 0);
  await hub.clickChip("#pick-model", 0);          // vw_cc_1_4_tsi — unresearched
  await hub.tick(120);

  assert.equal(hub.$("#step-gen").hidden, false);
  assert.match(hub.$("#pick-gen").textContent, /not researched/i);

  const run = hub.$("#b-agent-run");
  assert.match(run.textContent, /find generations/i,
    "the only runnable task here is generation research");
  assert.equal(run.disabled, false, "…and it must be runnable");

  const onboardChip = hub.chips("#pick-task")
    .find((c) => /onboard/i.test(c.textContent));
  assert.ok(onboardChip.disabled,
    "onboard must be unavailable until a generation exists");
  hub.close();
});

test("a researched lineup offers its generations, and onboard waits for one",
  async () => {
    const hub = await boot();
    await hub.clickChip("#pick-make", 1);         // Renault
    await hub.clickChip("#pick-model", 0);        // Clio — researched
    await hub.tick(120);

    assert.equal(hub.chips("#pick-gen").length, 2);
    const run = hub.$("#b-agent-run");
    assert.equal(run.disabled, true, "no generation picked yet");
    assert.match(hub.$("#onboard-state").textContent, /generation/i,
      "and the reason is stated, not left silent");

    await hub.clickChip("#pick-gen", 1);          // Clio V
    await hub.tick(120);
    assert.equal(run.disabled, false);
    assert.match(run.textContent, /onboard/i);
    assert.match(hub.$("#cmd-preview").textContent, /clio_5/,
      "the command targets the generation-qualified model key");
    hub.close();
  });

test("switching model resets a picked generation", async () => {
  const hub = await boot();
  await hub.clickChip("#pick-make", 1);
  await hub.clickChip("#pick-model", 0);
  await hub.tick(120);
  await hub.clickChip("#pick-gen", 0);
  await hub.tick(120);
  assert.equal(hub.$("#b-agent-run").disabled, false);

  await hub.clickChip("#pick-make", 0);           // back to Volkswagen
  await hub.clickChip("#pick-model", 1);          // Golf — unresearched
  await hub.tick(120);
  assert.match(hub.$("#b-agent-run").textContent, /find generations/i,
    "a stale generation must not carry over to another car");
  hub.close();
});

test("the page loads without a script error", async () => {
  const hub = await boot();
  assert.deepEqual(hub.errors, []);
  hub.close();
});


// ── Page/script skew ─────────────────────────────────────────────────────────
//
// The hub serves its page from the running process and its script from disk,
// so a server left running across an update pairs an OLD page with a NEW
// hub.js. That combination used to throw at load — the first top-level
// `$('#missing').onclick = …` — which killed every panel on the page,
// including this one, with no message anywhere a person would look. Reported
// as "onboard a model shows nothing".

test("a page missing newer elements still renders the picker", async () => {
  const hub = await boot({
    stripSelectors: ["#b-doctor", "#b-doctor-fix", "#t-doctor", "#doc-meta",
                     "#t-agentruns", "#agentruns-meta", "#hdr-lamp",
                     "#hdr-docs", "#hdr-spend"],
  });
  assert.equal(hub.chips("#pick-make").length, 2,
    "the picker must survive elements the page does not have");
  await hub.clickChip("#pick-make", 0);
  assert.equal(hub.$("#step-model").hidden, false);
  hub.close();
});

test("a stale page says so instead of failing silently", async () => {
  const hub = await boot({ stripSelectors: ["#b-doctor", "#hdr-lamp"] });
  const banner = hub.$("#stale-banner");
  assert.ok(banner, "a page/script mismatch must be visible");
  assert.match(banner.textContent, /older kriko-hub process/);
  assert.match(banner.textContent, /knowledge\.hub\.web/, "…and say how to fix it");
  hub.close();
});

test("a current page shows no staleness banner", async () => {
  const hub = await boot();
  assert.equal(hub.$("#stale-banner"), null);
  hub.close();
});
