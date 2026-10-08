// Real Chromium layout and saved Quick Look journey. Only the worker edge
// is scripted; the panel, card renderer and CSS are the production files.
// Run against: python -m http.server 8790 --directory extension
// NODE_PATH=<Playwright install>/node_modules node tools/journeys/quick-look.mjs
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const { chromium } = createRequire(import.meta.url)("playwright");
const base = process.argv[2] || "http://127.0.0.1:8790";
const out = process.argv[3] || ".walk";
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
try {
  for (const width of [1360, 440, 360]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    await page.addInitScript(() => {
      let value;
      const product = "Şımart Katya Ü / Dreame X50 Pro Ultra Complete · " + "Long listing title ".repeat(10);
      const job = { job_id: "saved-quick", kind: "quick_look", state: "succeeded", done: true,
        created_at: "2026-10-08T12:00:00Z", finished_at: "2026-10-08T12:00:12Z",
        log: "planning product queries\nsearch exact product\nread source report\nsource checks complete",
        params: { product }, result: { product, assumed: product,
          specs: [{ name: "Capacity", value: "2 litres", url: "https://example.org/spec" }],
          risks: [{ title: "A very long failure title ".repeat(8), body: "An owner reported a failure. ".repeat(20),
            severity: "high", strength: "reported", source_count: 1,
            sources: [{ url: "https://example.org/report", domain: "example.org", quote: "Owner report ".repeat(15) }] }] } };
      Object.defineProperty(window, "chrome", { configurable: true, get: () => value, set: chrome => {
        value = chrome;
        const send = chrome.runtime.sendMessage;
        chrome.runtime.sendMessage = (message, callback) => {
          if (message.type === "SAVED_QUICK_LOOK") return callback({ ok: true, job });
          if (message.type === "RESEARCH_PLANE") return callback({ ok: true, plane: { backend: "local", budget_usd: 0 } });
          if (message.type === "RESEARCH_PRODUCT") return callback({ ok: true, job: { job_id: "failed-refresh", kind: "quick_look" } });
          if (message.type === "JOB_STATUS" && message.payload.job_id === "failed-refresh") return callback({ ok: true,
            job: { job_id: "failed-refresh", kind: "quick_look", done: true, state: "failed", error: "Inference timeout; retry." } });
          return send(message, callback);
        };
      } });
    });
    await page.goto(`${base}/tests/preview/panel.html?state=idle`);
    const root = page.locator("kriko-panel-host");
    await root.locator(".lite-saved-result").waitFor();
    await page.screenshot({ path: `${out}/quick-look-restored-${width}.png` });
    await root.locator(".lite-quick-sources summary").click();
    assert.equal(await root.locator(".lite-quick-source-list a").count(), 2);
    await root.locator(".lite-rc-toggle").first().click();
    await page.waitForTimeout(500);
    assert(await root.locator(".lite-rc-text").first().isVisible());
    const dimensions = await page.evaluate(() => {
      const root = document.querySelector("kriko-panel-host").shadowRoot;
      const body = root.querySelector(".lite-body");
      return { width: body.clientWidth, scroll: body.scrollWidth,
        controls: [...root.querySelectorAll(".lite-research button,input,textarea")].filter(el => el.getBoundingClientRect().width > 0)
          .map(el => ({ left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right })) };
    });
    assert(dimensions.scroll <= dimensions.width + 1, JSON.stringify(dimensions));
    assert(dimensions.controls.every(r => r.left >= -1 && r.right <= width + 1), JSON.stringify(dimensions));
    await page.screenshot({ path: `${out}/quick-look-${width}.png` });
    const logs = root.locator(".lite-task-log");
    await logs.locator("summary").click();
    await logs.locator("select").selectOption("search");
    assert.equal(await logs.locator("pre").textContent(), "search exact product");
    await logs.locator("summary").click();
    await logs.locator("summary").click();
    assert.equal(await logs.locator("select").inputValue(), "search");
    assert.equal(await logs.locator("pre").textContent(), "search exact product");
    await root.locator(".lite-research-start").click();
    await root.locator(".lite-research-status").filter({ hasText: "Inference timeout" }).waitFor();
    assert.equal(await root.locator(".lite-quick-cards .lite-rc-toggle").count(), 1, "failed refresh lost saved cards");
    await root.locator(".lite-followup-input").fill("Which evidence supports this?");
    await root.locator(".lite-followup-send").click();
    await root.locator(".lite-followup-answer").filter({ hasText: "service records" }).waitFor();
    assert.equal(errors.length, 0, errors.join("\n"));
    await page.close();
    console.log(`Quick Look restore, sources, expanded layout, failed refresh and follow-up passed at ${width}px.`);
  }
} finally { await browser.close(); }
