// Renders the advertisement: every frame is a pure function of time (scenes.js),
// photographed in a browser and piped to ffmpeg. Silent, 1920x1080, 30 fps.
//
//   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/ad/render.mjs stills 1.5,6,12
//   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/ad/render.mjs video
//
// `stills` writes one picture per time, to look at while editing; `video` writes
// out/kriko-ad.mp4 (or the path given). Output stays out of git. Environment:
// PLAYWRIGHT_MODULE (required unless playwright resolves), FFMPEG (default `ffmpeg`).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const siteDir = path.resolve(here, '../..');
const outDir = path.join(here, 'out');
const ffmpeg = process.env.FFMPEG || 'ffmpeg';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.webp': 'image/webp', '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' };

// The ad's own files at /, the site's pictures and fonts at /site/ (the markup names them that way).
const server = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split('?')[0]);
  const fromSite = rel.startsWith('/site/');
  const root = fromSite ? siteDir : here;
  const file = path.resolve(root, '.' + (fromSite ? rel.slice(5) : rel === '/' ? '/index.html' : rel));
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}).listen(0, '127.0.0.1');
await new Promise((resolve) => server.on('listening', resolve));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch();
let failed = false;
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on('pageerror', (error) => { failed = true; console.log('PAGEERROR', error.message); });
  page.on('requestfailed', (request) => { failed = true; console.log('REQFAILED', request.url()); });
  page.on('response', (response) => { if (response.status() >= 400) { failed = true; console.log('HTTP', response.status(), response.url()); } });
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map((image) => image.decode())); });
  const stage = page.locator('#stage');
  const [mode, arg] = process.argv.slice(2);
  fs.mkdirSync(outDir, { recursive: true });
  if (mode === 'stills') {
    fs.mkdirSync(path.join(outDir, 'stills'), { recursive: true });
    for (const t of arg.split(',').map(Number)) {
      await page.evaluate((time) => window.render(time), t);
      await stage.screenshot({ path: path.join(outDir, 'stills', `t-${String(t).padStart(5, '0')}.png`) });
      console.log('still', t);
    }
  } else if (mode === 'video') {
    const outFile = path.resolve(arg || path.join(outDir, 'kriko-ad.mp4'));
    const fps = 30;
    const frames = Math.round((await page.evaluate(() => window.DURATION)) * fps);
    const encoder = spawn(ffmpeg, ['-y', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '14', '-preset', 'slow', '-movflags', '+faststart', outFile], { stdio: ['pipe', 'ignore', 'pipe'] });
    let log = '';
    encoder.stderr.on('data', (chunk) => { log += chunk; });
    const done = new Promise((resolve) => encoder.on('exit', resolve));
    for (let i = 0; i < frames; i++) {
      await page.evaluate((time) => window.render(time), i / fps);
      const png = await stage.screenshot({ type: 'png' });
      if (!encoder.stdin.write(png)) await new Promise((resolve) => encoder.stdin.once('drain', resolve));
      if (i % 60 === 0) console.log('frame', i, '/', frames);
    }
    encoder.stdin.end();
    const code = await done;
    if (code !== 0) { failed = true; console.log('ffmpeg failed', code, log.slice(-600)); }
    else console.log('wrote', outFile, frames, 'frames');
  } else throw new Error('usage: stills <times> | video [out]');
} catch (error) {
  failed = true;
  console.log('FAILED', String(error.message || error).split(/\r?\n/).slice(0, 4).join(' | '));
} finally {
  await browser.close();
  server.close();
  process.exit(failed ? 1 : 0);
}
