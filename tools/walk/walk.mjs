// Every screen, every button, timed. Run by tools/walk.sh, which starts the
// app on a throwaway home first; see the header there for why this exists.
//
//     node tools/walk/walk.mjs http://127.0.0.1:8799 report-dir
//
// Per screen: how long it takes to settle, what the console said, and every
// request that failed or answered >= 400. Per button: the same, plus whether
// pressing it did anything at all — a button that changes no text, sends no
// request and goes nowhere is reported, because "it does nothing" was the
// complaint that no unit test could see.
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

// Playwright is not a dependency of this repo — it is a 100 MB tool, not
// something the app or its tests need — so a global install is accepted.
const require = createRequire(import.meta.url);
const { chromium } = (() => {
    try { return require("playwright"); } catch { /* not local */ }
    return require(join(execSync("npm root -g").toString().trim(), "playwright"));
})();

const base = process.argv[2] ?? "http://127.0.0.1:8799";
const out = process.argv[3] ?? "walk-report";
const only = process.env.KRIKO_WALK_ONLY ?? "";
const SLOW_MS = Number(process.env.KRIKO_WALK_SLOW_MS ?? 1000);
mkdirSync(out, { recursive: true });

// Pressing these would end the process under test or throw its data away
// halfway through the walk, and every screen after it would be judging a
// different installation. They are listed, never pressed.
const SKIP = /\b(quit|uninstall|delete|remove|forget|reset|revoke|undo)\b/i;
// Streams never go quiet; they are not "pending" in the sense that matters.
const STREAM = /\/stream\b|text\/event-stream/;

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
let log = [];
const pending = new Map();
let page;
let sent = 0;

// A page per need, not one for the whole walk: a button that closes its
// window or crashes the renderer is a finding, and must not end the walk.
async function freshPage() {
    try { await page?.close(); } catch { /* already gone */ }
    pending.clear();
    page = await context.newPage();
    page.on("dialog", (dialog) => dialog.accept().catch(() => {}));
    page.on("popup", (popup) => {
        log.push({ kind: "popup", text: popup.url() });
        popup.close().catch(() => {});
    });
    page.on("crash", () => log.push({ kind: "crash", text: "the renderer crashed" }));
    page.on("console", (msg) => {
        if (msg.type() === "error" || msg.type() === "warning")
            log.push({ kind: `console.${msg.type()}`, text: msg.text().slice(0, 400) });
    });
    page.on("pageerror", (err) => log.push({ kind: "pageerror", text: String(err).slice(0, 400) }));
    page.on("request", (req) => {
        sent++;
        if (!STREAM.test(req.url())) pending.set(req, Date.now());
    });
    const settled = (req) => pending.delete(req);
    page.on("requestfailed", (req) => {
        settled(req);
        const why = req.failure()?.errorText ?? "";
        if (!/ERR_ABORTED/.test(why)) log.push({ kind: "requestfailed", text: `${req.method()} ${req.url()} ${why}` });
    });
    page.on("requestfinished", settled);
    page.on("response", async (res) => {
        const req = res.request();
        const started = pending.get(req);
        const ms = started ? Date.now() - started : 0;
        if (!res.url().startsWith(base) || STREAM.test(res.url())) return;
        const path = res.url().slice(base.length);
        if (res.status() >= 400) {
            let body = "";
            try { body = (await res.text()).slice(0, 300); } catch { /* gone */ }
            log.push({ kind: `http.${res.status()}`, text: `${req.method()} ${path} ${body}` });
        }
        if (ms >= SLOW_MS) log.push({ kind: "slow-request", text: `${req.method()} ${path} ${ms}ms` });
    });
}
await freshPage();

async function quiet(limit = 8000) {
    const start = Date.now();
    let calm = 0;
    while (Date.now() - start < limit) {
        await page.waitForTimeout(50);
        calm = pending.size ? 0 : calm + 50;
        if (calm >= 300) return { ms: Date.now() - start - 300, timedOut: false };
    }
    log.push({ kind: "never-quiet", text: [...pending.keys()].map((r) => `${r.method()} ${r.url().replace(base, "")}`).join(", ") });
    return { ms: limit, timedOut: true };
}

// What a press can change: the words, and the state a toggle carries without
// changing any words — pressed, selected, checked, a value.
const text = () => page.evaluate(() => {
    const main = document.querySelector("main");
    if (!main) return "";
    const states = [...main.querySelectorAll("button, input, select, textarea, [aria-pressed], [aria-selected]")]
        .map((el) => [el.getAttribute("aria-pressed"), el.getAttribute("aria-selected"), el.className,
            el.disabled, el.value, el.checked].join("|"));
    return main.innerText + "\u0000" + states.join("\n");
});

async function open(hash) {
    log = [];
    const started = Date.now();
    // Via a blank page: `goto` to the address already open only changes the
    // hash, and the next button would be judged on the last one's aftermath.
    if (page.isClosed()) await freshPage();
    await page.goto("about:blank");
    // A request the navigation cut off fires neither `requestfinished` nor
    // `requestfailed`, and would read as pending forever.
    pending.clear();
    await page.goto(`${base}/${hash}`);
    const { timedOut } = await quiet(15000);
    // "Reading…" and friends: a screen that is still loading has not arrived.
    await page.waitForFunction(
        () => !/\b(Reading|Loading|Starting|Adding it up|Asking)[^.\n]*…/.test(document.querySelector("main")?.innerText ?? ""),
        null, { timeout: 10000 },
    ).catch(() => log.push({ kind: "stuck-loading", text: "a loading line never went away" }));
    return { ms: Date.now() - started, timedOut };
}

// Every <details> open, so the buttons inside are reachable too.
const expand = () => page.evaluate(() => document.querySelectorAll("main details").forEach((d) => (d.open = true)));

async function buttons() {
    return page.evaluate(() => {
        const all = [...document.querySelectorAll("main button")];
        const seen = {};
        return all.map((b) => {
            const r = b.getBoundingClientRect();
            const label = (b.getAttribute("aria-label") || b.innerText || b.title || "").trim().replace(/\s+/g, " ");
            seen[label] = (seen[label] ?? -1) + 1;
            return {
                label: label.slice(0, 80),
                full: label,
                nth: seen[label],
                disabled: b.disabled,
                visible: r.width > 0 && r.height > 0,
            };
        });
    });
}

async function press(hash, one, row) {
    await open(hash);
    await expand();
    const before = await text();
    const beforeHash = page.url();
    // By what it says, not by position: a list that renders a beat later
    // shifts every index after it.
    const found = await page.evaluate(([want, nth]) => {
        document.querySelectorAll("[data-walk]").forEach((el) => el.removeAttribute("data-walk"));
        let k = -1;
        for (const b of document.querySelectorAll("main button")) {
            const label = (b.getAttribute("aria-label") || b.innerText || b.title || "").trim().replace(/\s+/g, " ");
            if (label === want && ++k === nth) { b.setAttribute("data-walk", "here"); return true; }
        }
        return false;
    }, [one.full, one.nth]);
    if (!found) { row.result = "gone after reload"; return; }
    sent = 0;
    const started = Date.now();
    try {
        await page.locator('[data-walk="here"]').click({ timeout: 3000 });
    } catch (err) {
        row.result = "could not press";
        row.why = String(err).split("\n")[0].slice(0, 200);
        return;
    }
    const { ms, timedOut } = await quiet();
    const after = await text();
    row.ms = Date.now() - started;
    row.settleMs = ms;
    row.requests = sent;
    row.changed = before !== after || beforeHash !== page.url();
    row.problems = [...log];
    row.result = timedOut ? "never settled"
        : row.problems.some((p) => /pageerror|crash|http\.5|console\.error|requestfailed/.test(p.kind)) ? "error"
        : !row.changed && !sent ? "did nothing visible"
        : row.ms >= SLOW_MS ? "slow"
        : "ok";
}

// The destinations are the rail's own, read off the page, so a screen added
// tomorrow is walked tomorrow without anyone editing this file.
await page.goto(`${base}/#/check?mode=author`);
await quiet();
let routes = await page.evaluate(() =>
    [...new Set([...document.querySelectorAll("nav a[href^='#/']")].map((a) => a.getAttribute("href")))],
);
routes = routes.map((h) => (h.includes("mode=") ? h : `${h}${h.includes("?") ? "&" : "?"}mode=author`));
if (only) routes = routes.filter((h) => h.includes(only));

const report = [];
for (const hash of routes) {
    const arrived = await open(hash);
    await expand();
    const screen = { hash, ms: arrived.ms, timedOut: arrived.timedOut, problems: [...log], buttons: [] };
    const listed = await buttons();
    for (const one of listed) {
        const row = { label: one.label || "(unlabelled button)" };
        if (!one.visible) continue;
        if (one.disabled) { row.result = "disabled"; screen.buttons.push(row); continue; }
        if (SKIP.test(one.label)) { row.result = "not pressed (destructive)"; screen.buttons.push(row); continue; }
        if (process.env.KRIKO_WALK_VERBOSE) console.error(`  pressing ${row.label}`);
        try {
            await press(hash, one, row);
        } catch (err) {
            row.result = page.isClosed() ? "closed the page" : "walk error";
            row.why = String(err).split("\n")[0].slice(0, 200);
            row.problems = [...log];
            await freshPage();
        }
        if (process.env.KRIKO_WALK_VERBOSE) console.error(`    ${row.result} ${row.ms ?? ""} ${(row.problems ?? []).map((p) => p.kind + ": " + p.text).join(" / ").slice(0, 300)}`);
        screen.buttons.push(row);
    }
    await open(hash);
    await expand();
    const name = hash.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "");
    await page.screenshot({ path: join(out, `${name}.png`), fullPage: true });
    report.push(screen);
    const bad = screen.buttons.filter((b) => !["ok", "disabled", "not pressed (destructive)"].includes(b.result));
    console.log(`${hash.padEnd(38)} ${String(screen.ms).padStart(5)}ms  ${screen.buttons.length} buttons, ${bad.length} flagged, ${screen.problems.length} load problems`);
}

writeFileSync(join(out, "walk.json"), JSON.stringify(report, null, 2));

const lines = ["# UI walk", "", `Base: ${base} · slow = ${SLOW_MS}ms or more`, ""];
for (const s of report) {
    lines.push(`## ${s.hash} — ${s.ms}ms${s.timedOut ? " (never settled)" : ""}`);
    for (const p of s.problems) lines.push(`- load: **${p.kind}** ${p.text}`);
    for (const b of s.buttons) {
        if (b.result === "ok") continue;
        lines.push(`- \`${b.label}\` — **${b.result}**${b.ms ? ` (${b.ms}ms)` : ""}${b.why ? `: ${b.why}` : ""}`);
        for (const p of b.problems ?? []) lines.push(`  - ${p.kind}: ${p.text}`);
    }
    const ok = s.buttons.filter((b) => b.result === "ok");
    if (ok.length) lines.push(`- ok: ${ok.map((b) => `\`${b.label}\` ${b.ms}ms`).join(", ")}`);
    lines.push("");
}
writeFileSync(join(out, "walk.md"), lines.join("\n"));
await browser.close();
const flagged = report.flatMap((s) => [
    ...s.problems.filter((p) => p.kind !== "slow-request"),
    ...s.buttons.filter((b) => ["error", "never settled", "could not press"].includes(b.result)),
]);
console.log(`\n${report.length} screens; report in ${out}/walk.md`);
process.exit(flagged.length ? 1 : 0);
