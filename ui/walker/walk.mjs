// The screen walker: open every screen, press every control, write down what broke.
//
// The vitest suites test components one at a time against a stubbed fetch, so
// they can all pass on an app whose buttons do nothing once assembled. This is
// the other half: the real server, the real bundle, a real browser, and every
// control pressed once from a freshly loaded screen.
//
// It never touches the reader's own install. It copies ~/.kriko into a scratch
// home and points USERPROFILE/HOME there, so everything Path.home() resolves —
// the store, app.sqlite, the logs, the agent configs under ~/.claude — lands in
// the copy. Endpoints that spend money or reach the desktop (running an agent,
// a benchmark, opening Explorer, restarting) are blocked at the browser and
// reported as "outward", not pressed.
//
//   node ui/walker/walk.mjs [--out DIR] [--python PATH] [--max N] [--only a,b]

import { chromium } from "playwright-core";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");

const args = Object.fromEntries(
    process.argv.slice(2).reduce((acc, a, i, all) => {
        if (a.startsWith("--")) acc.push([a.slice(2), all[i + 1]?.startsWith("--") ? true : all[i + 1] ?? true]);
        return acc;
    }, []),
);
const OUT = path.resolve(args.out || path.join(os.tmpdir(), `kriko-walk-${Date.now()}`));
const MAX_CONTROLS = Number(args.max || 60);
const ONLY = args.only ? String(args.only).split(",") : null;
const SLOW_MS = 2000;
const SETTLE_MS = 15000;

// Money, the desktop, or the process itself. Everything else runs against the copy.
const OUTWARD = [
    /\/api\/research(\?|$)/, /\/api\/agenda\/run/, /\/api\/bench(\?|$)/, /\/api\/agent-verify/,
    /\/test(\?|$)/, /\/api\/packs\/update/, /\/launch(\?|$)/, /\/reveal(\?|$)/,
    /\/restart(\?|$)/, /\/close(\?|$)/, /\/api\/packs\/author/, /\/schedule\/check/,
    /\/diagnose\/identity/, /\/jobs\/[^/]+\/retry/, /\/packs\/drafts\/[^/]+\/amend/,
];

function chromePath() {
    const candidates = [
        process.env.CHROME,
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "/usr/bin/google-chrome", "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ];
    return candidates.find((c) => c && fs.existsSync(c));
}

function pythonPath() {
    if (args.python) return args.python;
    for (const root of [repo, path.resolve(repo, "..", "..", "..")]) {
        for (const rel of [".venv/Scripts/python.exe", ".venv/bin/python"]) {
            const p = path.join(root, rel);
            if (fs.existsSync(p)) return p;
        }
    }
    return "python";
}

function scratchHome() {
    const home = path.join(OUT, "home");
    const real = path.join(os.homedir(), ".kriko");
    fs.mkdirSync(home, { recursive: true });
    if (fs.existsSync(real)) fs.cpSync(real, path.join(home, ".kriko"), { recursive: true });
    return home;
}

function startServer(home) {
    const env = {
        ...process.env,
        USERPROFILE: home, HOME: home,
        PYTHONPATH: [path.join(repo, "src"), repo].join(path.delimiter),
        PYTHONIOENCODING: "utf-8",
    };
    for (const k of Object.keys(env)) if (k.startsWith("KRIKO_")) delete env[k];
    // No agent CLI is ever found, so none is ever started — not a run, not
    // `--help`, not `models`. HOME is the scratch copy, so the home-relative
    // install dirs miss too; PATH is the one place left to find one.
    const system = process.env.SystemRoot || "C:\\Windows";
    for (const k of Object.keys(env)) if (k.toUpperCase() === "PATH") delete env[k];
    env.PATH = [path.dirname(pythonPath()), path.join(system, "System32"), system].join(path.delimiter);
    const child = spawn(pythonPath(), ["-m", "app.sidecar", "--exit-with-parent"], {
        cwd: repo, env, stdio: ["pipe", "pipe", "pipe"],
    });
    const stderr = [];
    child.stderr.on("data", (d) => stderr.push(String(d)));
    return new Promise((resolve, reject) => {
        let buf = "";
        const timer = setTimeout(() => reject(new Error("sidecar never announced a port:\n" + stderr.join(""))), 60000);
        child.stdout.on("data", (d) => {
            buf += String(d);
            const m = buf.match(/KRIKO_PORT (\d+)/);
            if (m) { clearTimeout(timer); resolve({ child, port: Number(m[1]), stderr }); }
        });
        child.on("exit", (code) => reject(new Error(`sidecar exited ${code}:\n${stderr.join("")}`)));
    });
}

// What counts as visible trouble in rendered text. Closed vocabulary of the
// renderer, not of any pack.
const BAD_TEXT = /\bundefined\b|\bNaN\b|\[object Object\]|Traceback|Internal Server Error/;

function watch(page, base) {
    const log = { console: [], pageErrors: [], failed: [], bad: [], slow: [], outward: [], requests: 0, dialogs: [] };
    const started = new Map();
    page.on("console", (m) => {
        if (m.type() === "error" || m.type() === "warning")
            log.console.push(`${m.type()}: ${m.text()}`.slice(0, 400));
    });
    page.on("pageerror", (e) => log.pageErrors.push(String(e.message || e).slice(0, 400)));
    page.on("request", (r) => {
        if (!r.url().startsWith(base)) return;
        log.requests++;
        started.set(r, Date.now());
    });
    page.on("requestfinished", async (r) => {
        const t0 = started.get(r);
        const ms = t0 ? Date.now() - t0 : 0;
        const short = `${r.method()} ${r.url().replace(base, "")}`;
        if (ms > SLOW_MS) log.slow.push(`${short} ${ms}ms`);
        try {
            const res = await r.response();
            if (res && res.status() >= 400) {
                let body = "";
                try { body = (await res.text()).slice(0, 300); } catch {}
                log.bad.push(`${res.status()} ${short} ${body}`);
            }
        } catch {}
    });
    page.on("requestfailed", (r) => {
        const why = r.failure()?.errorText || "";
        if (why.includes("BLOCKED_BY_CLIENT") || why.includes("ERR_ABORTED")) return;
        if (r.url().startsWith(base)) log.failed.push(`${r.method()} ${r.url().replace(base, "")} ${why}`);
    });
    page.on("dialog", (d) => { log.dialogs.push(`${d.type()}: ${d.message()}`.slice(0, 200)); d.dismiss().catch(() => {}); });
    return log;
}

const snapshot = (log) => JSON.parse(JSON.stringify(log));
const since = (now, then) => Object.fromEntries(Object.entries(now).map(([k, v]) =>
    [k, Array.isArray(v) ? v.slice(then[k].length) : v - then[k]]));

async function settle(page) {
    const t0 = Date.now();
    try { await page.waitForLoadState("networkidle", { timeout: SETTLE_MS }); return { ms: Date.now() - t0, settled: true }; }
    catch { return { ms: Date.now() - t0, settled: false }; }
}

// Where the bundle is served. The sidecar serves it at /, the Vite dev server
// (--dev) at its `base`, /static/.
let PAGE_ROOT = "";

function startDevUi(apiBase) {
    const port = Number(args.devport || 5199);
    const vite = path.join(repo, "ui", "node_modules", "vite", "bin", "vite.js");
    const child = spawn(process.execPath, [vite, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], {
        cwd: path.join(repo, "ui"), env: { ...process.env, KRIKO_API: apiBase }, stdio: ["ignore", "pipe", "pipe"],
    });
    return new Promise((resolve, reject) => {
        let buf = "";
        const timer = setTimeout(() => reject(new Error("vite never came up:\n" + buf)), 60000);
        const on = (d) => {
            buf += String(d);
            if (/ready in|Local:/.test(buf)) { clearTimeout(timer); resolve({ child, origin: `http://127.0.0.1:${port}` }); }
        };
        child.stdout.on("data", on);
        child.stderr.on("data", on);
    });
}

async function openScreen(page, base, name) {
    await page.goto("about:blank");
    const t0 = Date.now();
    await page.goto(`${PAGE_ROOT}/#/${name}?mode=author`);
    const s = await settle(page);
    await page.waitForTimeout(300);
    return { ...s, ms: Date.now() - t0 };
}

// Controls in the screen's own content — the rail is walked by visiting every route.
const CONTROL_QUERY = "main button, main a[href], main [role=button], main [role=tab], main select, main input[type=checkbox], main input[type=radio], main summary";

const labelOf = (e) => (e.getAttribute("aria-label") || e.textContent || e.getAttribute("title") || e.getAttribute("href") || "").trim().replace(/\s+/g, " ").slice(0, 80);

async function listControls(page) {
    return page.$$eval(CONTROL_QUERY, (els, src) => {
        const labelOf = new Function("return " + src)();
        const seen = {};
        return els.map((el, i) => {
            const r = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            const label = labelOf(el);
            const nth = (seen[label] = (seen[label] ?? -1) + 1);
            return {
                i, nth, tag: el.tagName.toLowerCase(), label,
                href: el.getAttribute("href"),
                disabled: el.disabled || el.getAttribute("aria-disabled") === "true",
                visible: r.width > 0 && r.height > 0 && style.visibility !== "hidden" && style.display !== "none",
            };
        });
    }, labelOf.toString());
}

async function pageProblems(page) {
    return page.evaluate((badSrc) => {
        const bad = new RegExp(badSrc);
        const main = document.querySelector("main") || document.body;
        const text = main.innerText || "";
        const out = [];
        const m = text.match(bad);
        if (m) {
            const at = text.indexOf(m[0]);
            out.push(`renders "${m[0]}": …${text.slice(Math.max(0, at - 60), at + 60).replace(/\s+/g, " ")}…`);
        }
        document.querySelectorAll(".failure, [role=alert]").forEach((el) => {
            const t = (el.innerText || "").trim().replace(/\s+/g, " ");
            if (t) out.push(`alert: ${t.slice(0, 200)}`);
        });
        if (text.trim().length < 20) out.push("screen is (nearly) empty");
        const sw = document.documentElement.scrollWidth, cw = document.documentElement.clientWidth;
        if (sw > cw + 4) out.push(`horizontal overflow: ${sw}px content in ${cw}px`);
        return out;
    }, BAD_TEXT.source);
}

async function armMutationCounter(page) {
    await page.evaluate(() => {
        window.__muts = 0;
        window.__mo?.disconnect();
        window.__mo = new MutationObserver((l) => { window.__muts += l.length; });
        window.__mo.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
    });
}

async function pressControl(page, base, name, ctl, log, shotDir) {
    await openScreen(page, base, name);
    // Found by label and occurrence, not position: an earlier press ("Forget",
    // "Hide") may have removed a row from the copied store, shifting every index.
    // Wait for the list to stop growing — rows arrive after networkidle on some screens.
    let el;
    for (let tries = 0; tries < 6 && !el; tries++) {
        const handles = await page.$$(CONTROL_QUERY);
        const labels = await Promise.all(handles.map((h) => h.evaluate((e, src) => new Function("return " + src)()(e), labelOf.toString())));
        const matches = handles.filter((_, k) => labels[k] === ctl.label);
        el = matches[ctl.nth];
        if (!el) await page.waitForTimeout(500);
    }
    if (!el) return { verdict: "unstable", note: "control not present on a fresh load" };
    // A control in a collapsed <details> is one click from the reader; open it
    // the way they would, rather than reporting the control as unreachable.
    if (ctl.tag !== "summary")
        await el.evaluate((e) => { for (let d = e.closest("details"); d; d = d.parentElement?.closest("details")) d.open = true; });
    const checkedBefore = await el.evaluate((e) => ("checked" in e ? e.checked : null) ?? e.open ?? null);
    if (checkedBefore && ctl.tag === "input" && (await el.getAttribute("type")) === "radio")
        return { verdict: "skipped", note: "radio already chosen" };
    await armMutationCounter(page);
    const before = snapshot(log);
    const hashBefore = await page.evaluate(() => location.hash);
    const popups = [];
    const onPopup = (p) => { popups.push(p.url()); p.close().catch(() => {}); };
    page.context().on("page", onPopup);
    const t0 = Date.now();
    try {
        if (ctl.tag === "select") {
            const opts = await el.$$eval("option", (os) => os.map((o) => ({ v: o.value, off: o.disabled, sel: o.selected })));
            const pick = opts.find((o) => !o.off && !o.sel);
            if (!pick) { page.context().off("page", onPopup); return { verdict: "skipped", note: "select with no other enabled option" }; }
            await el.selectOption(pick.v, { timeout: 4000 });
        } else {
            await el.click({ timeout: 4000 });
        }
    } catch (e) {
        page.context().off("page", onPopup);
        return { verdict: "unclickable", note: String(e.message).split("\n")[0].slice(0, 200) };
    }
    await page.waitForTimeout(400);
    const s = await settle(page);
    await page.waitForTimeout(300);
    page.context().off("page", onPopup);
    const d = since(snapshot(log), before);
    const muts = await page.evaluate(() => window.__muts).catch(() => -1);
    const hashAfter = await page.evaluate(() => location.hash).catch(() => hashBefore);
    const problems = await pageProblems(page).catch(() => []);
    const checkedAfter = await el.evaluate((e) => ("checked" in e ? e.checked : null) ?? e.open ?? null).catch(() => checkedBefore);
    const toggled = checkedBefore !== checkedAfter;
    // A request the walker itself blocked logs a console error; that is "outward", not a bug.
    const own = (x) => x.includes("ERR_BLOCKED_BY_CLIENT");
    const errors = [...d.pageErrors.map((x) => `JS: ${x}`), ...d.console.filter((x) => x.startsWith("error") && !own(x)).map((x) => `console ${x}`),
        ...d.bad.map((x) => `HTTP ${x}`), ...d.failed.map((x) => `network ${x}`)];
    let verdict = "ok";
    if (errors.length) verdict = "error";
    else if (d.outward.length) verdict = "outward";
    else if (muts === 0 && d.requests === 0 && !toggled && hashAfter === hashBefore && !popups.length && !d.dialogs.length) verdict = "dead";
    else if (d.slow.length || !s.settled) verdict = "slow";
    let shot;
    if (verdict === "error" || verdict === "dead") {
        shot = path.join(shotDir, `${name}-${ctl.i}.png`);        await page.screenshot({ path: shot }).catch(() => {});
    }
    return { verdict, errors, outward: d.outward, slow: d.slow, settled: s.settled, ms: Date.now() - t0, dialogs: d.dialogs, popups,
        requests: d.requests, mutations: muts, navigated: hashAfter !== hashBefore ? hashAfter : undefined, problems, shot };
}

async function main() {
    fs.mkdirSync(path.join(OUT, "shots"), { recursive: true });
    console.log(`walker: output in ${OUT}`);
    const home = scratchHome();
    const { child, port, stderr } = await startServer(home);
    let base = `http://127.0.0.1:${port}`;
    console.log(`walker: sidecar on ${base}`);
    PAGE_ROOT = base;
    let dev;
    if (args.dev) {
        dev = await startDevUi(base);
        base = dev.origin;
        PAGE_ROOT = `${dev.origin}/static`;
        console.log(`walker: dev UI on ${PAGE_ROOT} (unminified errors)`);
    }
    const browser = await chromium.launch({ executablePath: chromePath(), headless: true });
    const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    const page = await context.newPage();
    const log = watch(page, base);
    await page.route("**/api/**", (route) => {
        const req = route.request();
        const url = req.url();
        if (req.method() !== "GET" && OUTWARD.some((re) => re.test(url))) {
            log.outward.push(`${req.method()} ${url.replace(base, "")}`);
            return route.abort("blockedbyclient");
        }
        return route.continue();
    });

    // Routes come from the rendered rail, so a screen added to nav.ts is walked
    // the day it exists.
    await openScreen(page, base, "overview");
    let routes = await page.$$eval("a[href^='#/']", (as) => [...new Set(as.filter((a) => !a.closest("main")).map((a) => a.getAttribute("href").replace(/^#\//, "").split(/[/?]/)[0]))]);
    if (!routes.length) routes = ["check"];
    if (ONLY) routes = routes.filter((r) => ONLY.includes(r));
    console.log(`walker: ${routes.length} screens: ${routes.join(", ")}`);

    const report = { base, startedAt: new Date().toISOString(), screens: [] };
    for (const name of routes) {
        const before = snapshot(log);
        const load = await openScreen(page, base, name);
        const d = since(snapshot(log), before);
        const shot = path.join(OUT, "shots", `${name}.png`);
        await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
        const screen = {
            name, loadMs: load.ms, settled: load.settled,
            onLoad: {
                errors: [...d.pageErrors.map((x) => `JS: ${x}`), ...d.console.map((x) => `console ${x}`), ...d.bad.map((x) => `HTTP ${x}`), ...d.failed.map((x) => `network ${x}`)],
                slow: d.slow, problems: await pageProblems(page),
            },
            shot, controls: [],
        };
        const controls = (await listControls(page)).filter((c) => c.visible);
        screen.controlCount = controls.length;
        screen.disabled = controls.filter((c) => c.disabled).map((c) => c.label);
        const toPress = controls.filter((c) => !c.disabled && !(c.href && /^https?:/.test(c.href))).slice(0, MAX_CONTROLS);
        screen.truncated = controls.length > MAX_CONTROLS;
        screen.external = controls.filter((c) => c.href && /^https?:/.test(c.href)).map((c) => c.href);
        console.log(`walker: ${name} loaded in ${load.ms}ms${load.settled ? "" : " (never settled)"}, ${controls.length} controls; load issues: ${screen.onLoad.errors.length + screen.onLoad.problems.length}`);
        for (const ctl of toPress) {
            const r = await pressControl(page, base, name, ctl, log, path.join(OUT, "shots"));
            screen.controls.push({ label: ctl.label, tag: ctl.tag, ...r });
            if (r.verdict !== "ok") console.log(`  ${r.verdict.padEnd(11)} ${ctl.tag} "${ctl.label}" ${(r.errors || []).concat(r.note || [], r.slow || []).join(" | ").slice(0, 200)}`);
        }
        report.screens.push(screen);
        fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 2));
    }
    report.finishedAt = new Date().toISOString();
    report.serverStderrTail = stderr.join("").split("\n").slice(-80).join("\n");
    fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 2));
    await browser.close();
    child.kill();
    dev?.child.kill();
    const tally = {};
    for (const s of report.screens) for (const c of s.controls) tally[c.verdict] = (tally[c.verdict] || 0) + 1;
    console.log(`walker: done — ${JSON.stringify(tally)}; report at ${path.join(OUT, "report.json")}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
