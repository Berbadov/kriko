// A private, seeded copy of the desktop app, for the site's pictures and guide GIFs.
//
// The window is the app's own build (kriko-ui/dist, so run `npm run build` in kriko-ui
// first) talking to a real engine: a sidecar started in an empty home folder of its own,
// whose saved checks, queue and comparison are the invented e-bikes of examples.json and
// app_examples.json (seed_app_examples.py). Nothing of the reader's own machine can reach
// a picture: the engine's home is a temporary folder, its extension port is off, and the
// proxy below is the only door the page has.
//
// Environment: PYTHON (default `python`; a full path also hides the agents on this
// machine's PATH from the engine).
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
const dist = path.resolve(repo, 'kriko-ui/dist');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.png': 'image/png', '.webp': 'image/webp', '.json': 'application/json' };

/** Starts the engine and the window's server. `stop()` ends both and removes the folder. */
export async function startApp() {
  const python = process.env.PYTHON || 'python';
  if (!fs.existsSync(path.join(dist, 'index.html'))) throw new Error('kriko-ui/dist is missing: run `npm run build` in kriko-ui first');
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'kriko-site-'));
  fs.mkdirSync(path.join(home, '.kriko'));
  // Placeholder keys, so the app offers its own Kriko Agent as the reader's agent.
  // They are not real and nothing here runs a search, so nothing ever sends them.
  fs.writeFileSync(path.join(home, '.kriko', 'env'), 'MERCURY_API_KEY=placeholder-not-a-key\nDEEPSEEK_API_KEY=placeholder-not-a-key\n');
  // The engine lists the coding agents it finds on PATH. A picture should show the
  // agent the app ships, not whichever CLI this machine happens to have, so the
  // engine sees Python and Windows and nothing else (when PYTHON is a full path).
  const system = process.env.SystemRoot || 'C:\Windows';
  const searchPath = path.isAbsolute(python)
    ? [path.dirname(python), path.join(system, 'System32'), system].join(path.delimiter)
    : process.env.PATH;
  if (!path.isAbsolute(python)) console.log('PYTHON is not a full path: agents installed on this machine may appear in the pictures');
  const env = { ...process.env, PATH: searchPath, USERPROFILE: home, HOME: home, PYTHONPATH: path.join(repo, 'src'), PYTHONIOENCODING: 'utf-8' };
  const seeded = spawnSync(python, [path.join(here, 'seed_app_examples.py'), path.join(home, '.kriko', 'app.sqlite')], { env, encoding: 'utf8' });
  if (seeded.status !== 0) throw new Error(`seeding failed: ${seeded.stderr}`);
  const engine = spawn(python, ['-m', 'app.sidecar', '--extension-port', '0'], { env, cwd: repo, stdio: ['pipe', 'pipe', 'pipe'] });
  const enginePort = await new Promise((resolve, reject) => {
    let seen = '';
    const timer = setTimeout(() => reject(new Error(`the engine did not announce its port: ${seen}`)), 60000);
    engine.stdout.on('data', (chunk) => {
      seen += chunk;
      const match = /KRIKO_PORT (\d+)/.exec(seen);
      if (match) { clearTimeout(timer); resolve(Number(match[1])); }
    });
    engine.on('exit', () => reject(new Error(`the engine exited: ${seen}`)));
  });

  const server = http.createServer((req, res) => {
    if (req.url.startsWith('/api/')) {
      // The way the shell calls it: from outside the page, so with no Origin.
      const headers = { ...req.headers, host: `127.0.0.1:${enginePort}` };
      delete headers.origin;
      delete headers.referer;
      const upstream = http.request({ host: '127.0.0.1', port: enginePort, path: req.url, method: req.method, headers }, (reply) => {
        res.writeHead(reply.statusCode, reply.headers);
        reply.pipe(res);
      });
      upstream.on('error', () => { res.writeHead(502); res.end(); });
      req.pipe(upstream);
      return;
    }
    let rel = decodeURIComponent(req.url.split('?')[0]);
    if (rel === '/') rel = '/index.html';
    const file = path.resolve(dist, '.' + rel);
    if (!file.startsWith(dist) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  }).listen(0, '127.0.0.1');
  await new Promise((resolve) => server.on('listening', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;

  async function stop() {
    server.close();
    // Closing its stdin is how the engine is told to go; it holds its files until
    // it has, so the folder is removed only after it has gone (or been killed).
    engine.stdin.end();
    const gone = new Promise((resolve) => engine.once('exit', resolve));
    await Promise.race([gone, new Promise((resolve) => setTimeout(resolve, 8000))]);
    if (engine.exitCode === null) { engine.kill(); await Promise.race([gone, new Promise((resolve) => setTimeout(resolve, 3000))]); }
    try { fs.rmSync(home, { recursive: true, force: true, maxRetries: 8, retryDelay: 400 }); } catch { console.log(`left behind: ${home}`); }
  }
  return { base, stop };
}
