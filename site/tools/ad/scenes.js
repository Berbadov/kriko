// The advertisement: every frame is a pure function of time. render(t) sets the whole page.
// 120 beats per minute, so a beat is half a second and every cut and every slam lands on one.
const $ = (id) => document.getElementById(id);
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const prog = (t, a, b) => clamp((t - a) / (b - a));
const lerp = (a, b, p) => a + (b - a) * p;
const out3 = (p) => 1 - Math.pow(1 - p, 3);
const out4 = (p) => 1 - Math.pow(1 - p, 4);
const io = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
// 0 at the start, overshoots to about 1.2, settles on 1: a thing that lands hard
const spring = (u) => (u <= 0 ? 0 : 1 - Math.exp(-7.5 * u) * Math.cos(u * 13.5));
const nz = (t, s) => Math.sin(t * 12.9898 + s * 78.233) * 0.5 + Math.sin(t * 7.13 + s * 3.7) * 0.5;
const rng = (seed) => () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let x = Math.imul(seed ^ (seed >>> 15), 1 | seed); x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x; return ((x ^ (x >>> 14)) >>> 0) / 4294967296; };

const BEAT = 0.5;
const DURATION = 28.5;
const INK = '#0b1020';

const cam = $('cam');
const bg = $('bg');
const bgx = bg.getContext('2d');
const fx = $('fx').getContext('2d');

function node(parent, cls, html, css) {
  const el = document.createElement('div');
  el.className = `n ${cls || ''}`;
  if (html) el.innerHTML = html;
  if (css) el.style.cssText += css;
  parent.appendChild(el);
  return el;
}
function setT(n, { x = 0, y = 0, s = 1, sx, sy, r = 0, o = 1 } = {}) {
  n.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%) rotate(${r}deg) scale(${sx ?? s}, ${sy ?? s})`;
  n.style.opacity = String(o);
}
const scenes = [];
function scene(id, a, b) {
  const el = document.createElement('div');
  el.className = 'scene';
  el.id = id;
  cam.appendChild(el);
  const s = { el, a, b };
  scenes.push(s);
  return s;
}
// a thing that lands on `t0` from a direction, spins to rest, and keeps breathing
function slam(n, t, t0, { dx = 0, dy = -260, r0 = -10, rest = 0, s0 = 2, x = 0, y = 0, bob = 0, seed = 0, o = 1 } = {}) {
  const u = t - t0;
  if (u < 0) { n.style.opacity = '0'; return; }
  const sp = spring(u);
  setT(n, {
    x: x + dx * (1 - sp),
    y: y + dy * (1 - sp) + Math.sin(t * 2.4 + seed) * bob,
    s: s0 + (1 - s0) * sp,
    r: rest + r0 * (1 - sp) + Math.sin(t * 1.7 + seed) * (bob ? 0.8 : 0),
    o: Math.min(1, u * 40) * o,
  });
}
function row(parent, y, items, size) {
  const r = node(parent, 'row');
  items.forEach((it) => {
    const w = document.createElement('span');
    w.className = 'wb';
    w.textContent = it.text;
    w.style.cssText = `font-size:${size}px;background:${it.bg};color:${it.fg || INK}`;
    w.style.transform = 'translateY(0)';
    r.appendChild(w);
    it.el = w;
  });
  r.style.top = '0';
  setT(r, { x: 960, y });
  return r;
}
function popWord(it, t, t0, i, dir) {
  const u = t - t0;
  if (u < 0) { it.el.style.opacity = '0'; return; }
  const sp = spring(u);
  const s = 2.1 + (1 - 2.1) * sp;
  const ang = (dir ? -1 : 1) * 14 * (1 - sp) + Math.sin(t * 2 + i) * 0.6 + (i % 2 ? 1.2 : -1.2);
  it.el.style.opacity = String(Math.min(1, u * 40));
  it.el.style.transform = `translate(${(dir ? -1 : 1) * 260 * (1 - sp)}px, ${-220 * (1 - sp) + Math.sin(t * 2.6 + i * 1.3) * 5}px) rotate(${ang}deg) scale(${s})`;
}

// ── palettes for the dithered field ───────────────────────────────────────────
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const PAL = {
  warm: ['#f58fb2', '#ff8f8f', '#ffb38f', '#ffd6a8', '#fff0d4', '#ffe6a0'],
  xray: ['#05061a', '#0a0f36', '#16215f', '#352d73', '#8a4a97', '#e0308f'],
  hot: ['#ff3d7f', '#ff6a5c', '#ff9a3d', '#ffc933', '#ffe14a', '#fff0a0'],
  cool: ['#0a1370', '#2447e6', '#3d63f5', '#5b8cff', '#7fd4ff', '#d6f1ff'],
  grape: ['#3a1d9a', '#5a2bb5', '#8f4fe0', '#c28fe8', '#f58fb2', '#ffd6a8'],
  mint: ['#0f9d7a', '#1fbf75', '#5be3a0', '#b9f5c9', '#fff6c2', '#ffe14a'],
  night: ['#05061a', '#1b0f5c', '#3a1d9a', '#7a2fe0', '#c23ad6', '#ff5aa8'],
  sky: ['#0a0f36', '#16215f', '#2c3c9a', '#352d73', '#8a4a97', '#d97aa0', '#f5b9a8'],
};
Object.keys(PAL).forEach((k) => { PAL[k] = PAL[k].map(hex); });
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16);
const bgImage = bgx.createImageData(198, 114);
function drawField(t, pal, speed, freq) {
  const K = pal.length;
  const d = bgImage.data;
  const T = t * speed;
  for (let y = 0; y < 114; y++) {
    const v = y / 114;
    for (let x = 0; x < 198; x++) {
      const u = x / 198;
      let f = 0.5 + 0.27 * Math.sin(freq * 3.1 * u + 1.7 * Math.sin(freq * 2.0 * v + T * 0.9) + T * 0.8)
        + 0.23 * Math.sin(freq * 4.3 * v + 2.2 * Math.sin(freq * 2.7 * u - T * 0.7) - T * 0.6);
      f = clamp(f);
      const level = f * (K - 1) + (BAYER[(y & 3) * 4 + (x & 3)] - 0.5) * 1.15;
      const c = pal[clamp(Math.round(level), 0, K - 1)];
      const i = (y * 198 + x) * 4;
      d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2]; d[i + 3] = 255;
    }
  }
  bgx.putImageData(bgImage, 0, 0);
}

// ── confetti and sparkles, drawn on one canvas ─────────────────────────────────
const BURSTS = [];
function burst(t0, x, y, n, colors, power = 1) { BURSTS.push({ t0, x, y, n, colors, power }); }
function drawFx(t) {
  fx.clearRect(0, 0, 1920, 1080);
  for (const [bi, b] of BURSTS.entries()) {
    const tau = t - b.t0;
    if (tau < 0 || tau > 1.6) continue;
    const r = rng(bi * 977 + 13);
    for (let i = 0; i < b.n; i++) {
      const ang = r() * Math.PI * 2;
      const sp = (260 + r() * 900) * b.power;
      const size = 10 + Math.floor(r() * 4) * 6;
      const x = b.x + Math.cos(ang) * sp * tau * (1 - tau * 0.28);
      const y = b.y + Math.sin(ang) * sp * tau * (1 - tau * 0.28) + 1100 * tau * tau * 0.5;
      const life = 1 - tau / 1.6;
      fx.globalAlpha = Math.min(1, life * 2.2);
      fx.fillStyle = b.colors[Math.floor(r() * b.colors.length)];
      const px = Math.round(x / 6) * 6;
      const py = Math.round(y / 6) * 6;
      fx.fillRect(px, py, size, size);
      fx.strokeStyle = INK;
      fx.lineWidth = 3;
      fx.strokeRect(px, py, size, size);
    }
  }
  fx.globalAlpha = 1;
}
function sparkles(t, list, color) {
  fx.fillStyle = color;
  for (const [i, [x, y, size, ph]] of list.entries()) {
    const tw = Math.max(0, Math.sin(t * 3.2 + ph * 6 + i));
    if (tw < 0.05) continue;
    const s = size * tw;
    fx.save();
    fx.translate(x, y);
    fx.rotate(Math.sin(t + i) * 0.2);
    fx.beginPath();
    fx.moveTo(0, -s); fx.lineTo(s * 0.22, -s * 0.22); fx.lineTo(s, 0); fx.lineTo(s * 0.22, s * 0.22);
    fx.lineTo(0, s); fx.lineTo(-s * 0.22, s * 0.22); fx.lineTo(-s, 0); fx.lineTo(-s * 0.22, -s * 0.22);
    fx.closePath();
    fx.fill();
    fx.restore();
  }
}
const SPARK = (() => { const r = rng(7); return Array.from({ length: 16 }, () => [80 + r() * 1760, 70 + r() * 940, 22 + r() * 30, r()]); })();

// ── the scenes ────────────────────────────────────────────────────────────────
const S0 = scene('s0', 0, 4.5); // the listing, then the x-ray of it (one card, two looks)
const S2 = scene('s2', 4.0, 6.0);
const S3 = scene('s3', 6.0, 8.0);
const S4 = scene('s4', 8.0, 12.0);
const S5 = scene('s5', 12.0, 16.0);
const S6 = scene('s6', 16.0, 19.0);
const S7 = scene('s7', 19.0, 23.0);
const S8 = scene('s8', 23.0, 28.5);

const BIKE = `<svg viewBox="0 0 560 300" fill="none" stroke="currentColor" stroke-width="9" stroke-linecap="round" stroke-linejoin="round">
  <circle class="d" cx="120" cy="205" r="84" pathLength="1"/><circle class="d" cx="440" cy="205" r="84" pathLength="1"/>
  <path class="d" d="M120 205 L225 112 L392 108" pathLength="1"/><path class="d" d="M120 205 L258 205 L225 112" pathLength="1"/>
  <path class="d" d="M258 205 L392 108" pathLength="1"/><path class="d" d="M392 108 L440 205" pathLength="1"/>
  <path class="d" d="M372 84 L420 76 M392 108 L384 84" pathLength="1"/><path class="d" d="M196 100 L250 100" pathLength="1"/>
  <rect x="262" y="150" width="86" height="26" rx="8" fill="#ffe14a" stroke="currentColor" transform="rotate(-42 262 150)"/>
  <circle cx="258" cy="205" r="17" fill="#ff2e93" stroke="none"/></svg>`;
const CARD = (x) => `<div class="card${x ? ' x' : ''}">${BIKE}<div class="t">E-bike M · 2022</div><div class="s">Like new. Barely used.</div><div class="p">€1,450</div><div class="chips"><span class="chip">Free delivery</span><span class="chip">4.9 ★ seller</span></div></div>`;

// scene 0: the listing, the scan, the findings
const cardw = node(S0.el, '', '', 'width:900px;height:640px');
cardw.innerHTML = `${CARD(false)}<div class="xw" style="position:absolute;left:0;top:0;width:900px;height:640px">${CARD(true)}</div><div class="scan"></div>`;
const cardX = cardw.querySelector('.xw');
const scanEl = cardw.querySelector('.scan');
const draws0 = [...cardw.querySelectorAll('.card:not(.x) .d')];
const cap0 = node(S0.el, 'cap', '', 'color:' + INK + ';text-shadow:8px 8px 0 #ff2e93');
cap0.innerHTML = [...'LOOKS PERFECT.'].map((c) => `<i>${c === ' ' ? '&nbsp;' : c}</i>`).join('');
const caps0 = [...cap0.querySelectorAll('i')];
const starA = node(S0.el, 'star', 'Great<br>deal!');
const likeNew = node(S0.el, 'stk', 'Like new', 'background:#ff2e93;color:#fff');
const wait = node(S0.el, 'cap', 'But what is inside?', 'font-size:104px;color:#fff;text-shadow:7px 7px 0 #ff2e93');
const FINDINGS = [
  { k: 'High', text: 'Battery range drops<br>by a third in two winters', bg: '#ff5a4f', fg: '#fff', x: 330, y: 350, r: -8, t: 2.6 },
  { k: 'Medium', text: 'Motor cuts out<br>after rain', bg: '#ffc233', fg: INK, x: 1590, y: 360, r: 7, t: 2.85 },
  { k: 'Medium', text: 'Brake pads are<br>a six-month item', bg: '#ffc233', fg: INK, x: 320, y: 820, r: 6, t: 3.1 },
  { k: 'Low', text: 'Display error<br>on cold starts', bg: '#5be3a0', fg: INK, x: 1600, y: 830, r: -6, t: 3.35 },
];
FINDINGS.forEach((f) => { f.el = node(S0.el, 'stk', `<small>${f.k}</small>${f.text}`, `background:${f.bg};color:${f.fg}`); });

// scene 2: the headline
const l1 = [{ text: 'The', bg: '#fff6df' }, { text: 'listing', bg: '#ffe14a' }, { text: 'tells', bg: '#fff6df' }];
const l2 = [{ text: 'half', bg: '#ff2e93', fg: '#fff' }, { text: 'the', bg: '#fff6df' }, { text: 'story.', bg: '#2447e6', fg: '#fff' }];
const r1 = row(S2.el, 390, l1, 225);
const r2 = row(S2.el, 680, l2, 225);
const squig = document.createElement('div');
squig.style.cssText = 'position:absolute;left:-6px;bottom:-62px;width:calc(100% + 12px);height:56px';
squig.innerHTML = '<svg width="100%" height="56" viewBox="0 0 760 70" preserveAspectRatio="none" fill="none" stroke="#ffe14a" stroke-width="16" stroke-linecap="round"><path id="sq" d="M8 38 C60 4 100 72 152 38 S244 4 296 38 S388 72 440 38 S532 4 584 38 S676 72 752 36" pathLength="1"/></svg>';
l2[2].el.style.position = 'relative';
l2[2].el.appendChild(squig);
const sq = squig.querySelector('#sq');

// scene 3: the wordmark and the other half
const mark = node(S3.el, '', '<img src="/site/assets/kriko-wordmark-white.svg" style="width:880px;filter:drop-shadow(7px 0 0 #0b1020) drop-shadow(-7px 0 0 #0b1020) drop-shadow(0 7px 0 #0b1020) drop-shadow(0 -7px 0 #0b1020) drop-shadow(14px 14px 0 #0b1020)" alt="">');
const ring3 = node(S3.el, '', '', 'width:300px;height:300px;border:14px solid #fff;border-radius:50%');
const l3 = [{ text: 'tells', bg: '#ffe14a' }, { text: 'the', bg: '#fff6df' }, { text: 'other', bg: '#ff2e93', fg: '#fff' }, { text: 'half.', bg: '#fff6df' }];
const r3 = row(S3.el, 760, l3, 170);

// scene 4: the extension
const PX = 1.2; // logical px of the 400-wide panel picture to stage px
const panel = node(S4.el, 'shot', '', 'width:480px;height:922px');
panel.innerHTML = `<img src="/site/assets/examples/ebike-light.webp" style="width:480px;height:922px"><img id="pB" src="/site/assets/examples/claim-open-light.webp" style="width:480px;height:922px;opacity:0">`;
const pB = panel.querySelector('#pB');
const prings = {};
for (const [id, [x, y, w, h]] of Object.entries({ counts: [9, 54, 176, 24], find: [14, 235, 372, 120], body: [18, 318, 356, 98], source: [22, 420, 108, 48], ask: [27, 468, 348, 80] })) {
  const r = document.createElement('div');
  r.className = 'ring';
  r.style.cssText = `left:${x * PX}px;top:${y * PX}px;width:${w * PX}px;height:${h * PX}px`;
  panel.appendChild(r);
  prings[id] = r;
}
const t4a = row(S4.el, 360, [{ text: 'Open any', bg: '#fff6df' }], 190);
const t4b = row(S4.el, 590, [{ text: 'listing.', bg: '#ffe14a' }], 190);
const t4c = row(S4.el, 360, [{ text: 'Four things', bg: '#fff6df' }], 190);
const t4d = row(S4.el, 590, [{ text: 'to check.', bg: '#ff2e93', fg: '#fff' }], 190);
const t4e = row(S4.el, 360, [{ text: 'Every finding', bg: '#fff6df' }], 150);
const t4f = row(S4.el, 590, [{ text: 'keeps its source.', bg: '#5be3a0' }], 150);
const stkSource = node(S4.el, 'stk', '<small>Source</small>The page it came from', 'background:#ffe14a');
const stkAsk = node(S4.el, 'stk', '<small>And</small>What to ask the seller', 'background:#fff');
const cursor = node(cam, '', '<svg viewBox="0 0 64 64"><path d="M8 4 L8 50 L20 39 L28 58 L38 54 L30 36 L46 36 Z" fill="#fff" stroke="#0b1020" stroke-width="5" stroke-linejoin="round"/></svg>');
cursor.id = 'cursor';
const clickRing = node(cam, 'click');

// scene 5: compare
S5.el.style.perspective = '2400px';
const win = node(S5.el, 'shot', '', 'width:1440px;height:900px;border-radius:26px');
win.innerHTML = '<img src="/site/assets/desktop/compare-light.webp" style="width:1440px;height:900px">';
const wrings = {};
for (const [id, [x, y, w, h]] of Object.entries({ e1: [42, 452, 434, 196], e2: [501, 452, 434, 180], s1: [100, 456, 124, 24], s2: [560, 456, 124, 24], s3: [1040, 456, 124, 24] })) {
  const r = document.createElement('div');
  r.className = 'ring';
  r.style.cssText = `left:${x}px;top:${y}px;width:${w}px;height:${h}px`;
  win.appendChild(r);
  wrings[id] = r;
}
const t5a = row(S5.el, 118, [{ text: 'Torn between three?', bg: '#fff6df' }], 150);
const t5b = row(S5.el, 940, [{ text: 'Line them up.', bg: '#ff2e93', fg: '#fff' }], 190);
const stkSame = node(S5.el, 'stk', '<small>Found in two</small>Same problem, two bikes', 'background:#ffe14a');
const stkAlso = node(S5.el, 'stk', '<small>On every card</small>Also in 1 of 2 others', 'background:#fff');

// scene 6: solid, partial, thin
const grades = [
  { w: 'Solid.', why: 'No gaps in the evidence', bg: '#2fd68a', fg: INK, y: 180, t: 16.0, fromLeft: true, lit: [1, 1, 1] },
  { w: 'Partial.', why: 'Some gaps. Worth checking.', bg: '#ffb320', fg: INK, y: 540, t: 16.5, fromLeft: false, lit: [1, 1, 0] },
  { w: 'Thin.', why: 'Little to stand on', bg: '#ff4d45', fg: '#fff', y: 900, t: 17.0, fromLeft: true, lit: [1, 0, 0] },
];
grades.forEach((g) => {
  g.el = node(S6.el, 'band', `<div class="w">${g.w}</div><div class="why">${g.why}</div><div class="bars"><i style="height:70px"></i><i style="height:140px"></i><i style="height:210px"></i></div>`, `background:${g.bg};color:${g.fg};border-top:9px solid ${INK};border-bottom:9px solid ${INK}`);
  g.bars = [...g.el.querySelectorAll('.bars i')];
  g.bars.forEach((b, i) => { if (g.lit[i]) b.style.background = g.fg === '#fff' ? '#fff' : INK; });
});
const stkDoubt = node(S6.el, 'stk', 'Hide the thin ones.<br>Or keep them. Your call.', 'background:#fff;font-size:64px;border-width:9px;padding:18px 36px 12px');

// scene 7: the promises
const MQ_TEXT = 'A source beside every finding &nbsp;✱&nbsp; Your research stays on your computer &nbsp;✱&nbsp; Free and open source &nbsp;✱&nbsp; ';
const mqs = [0, 1, 2, 3, 4].map((i) => node(S7.el, 'mq', MQ_TEXT + MQ_TEXT, `top:${i * 250 - 10}px;left:0`));
const TICK = '<span class="tick"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>';
const promises = [
  { text: 'A source beside every finding', y: 290, r: -3, t: 19.0, x: 940 },
  { text: 'Your research stays on your computer', y: 540, r: 2.4, t: 19.5, x: 980 },
  { text: 'Free and open source', y: 790, r: -2, t: 20.0, x: 900 },
];
promises.forEach((p) => { p.el = node(S7.el, 'pb', `${TICK}<span>${p.text}</span>`); });

// scene 8: the end
const mark8 = node(S8.el, '', '<img src="/site/assets/kriko-wordmark-white.svg" style="width:1100px;filter:drop-shadow(7px 0 0 #0b1020) drop-shadow(-7px 0 0 #0b1020) drop-shadow(0 7px 0 #0b1020) drop-shadow(0 -7px 0 #0b1020) drop-shadow(14px 14px 0 #0b1020)" alt="">');
const ring8 = node(S8.el, '', '', 'width:340px;height:340px;border:16px solid #fff;border-radius:50%');
const l8 = [{ text: 'Know', bg: '#fff6df' }, { text: 'what', bg: '#ffe14a' }, { text: 'is', bg: '#ff2e93', fg: '#fff' }, { text: 'known', bg: '#fff6df' }, { text: 'to', bg: '#5be3a0' }, { text: 'go', bg: '#fff6df' }, { text: 'wrong.', bg: '#2447e6', fg: '#fff' }];
const r8 = row(S8.el, 590, l8, 96);
const cta1 = node(S8.el, 'btn', 'Download for Windows', 'background:#fff;color:' + INK);
const cta2 = node(S8.el, 'btn', 'kriko.cc', 'background:#ffe14a;color:' + INK);
const fine8 = node(S8.el, 'cap', 'Free · Open source · No account', 'font-size:50px;color:#fff;text-shadow:5px 5px 0 ' + INK);

const fine = document.createElement('div');
fine.className = 'fine';
fine.textContent = 'Invented products and findings.';
$('stage').appendChild(fine);

// bursts: the places where something lands
burst(0.05, 960, 430, 46, ['#ffe14a', '#ff2e93', '#fff', '#2447e6'], 1.1);
burst(2.6, 960, 520, 22, ['#ff5a4f', '#ffc233', '#fff'], 0.9);
burst(4.0, 960, 540, 60, ['#ffe14a', '#fff', '#ff2e93', '#0b1020'], 1.3);
burst(6.0, 960, 380, 70, ['#fff', '#ffe14a', '#ff2e93', '#7fd4ff'], 1.4);
burst(8.0, 1420, 560, 36, ['#fff', '#ffe14a', '#ff2e93'], 1);
burst(12.25, 960, 600, 40, ['#fff', '#5be3a0', '#ffe14a'], 1.1);
burst(16.0, 400, 360, 30, ['#fff', '#0b1020'], 1);
burst(17.0, 1500, 900, 30, ['#fff', '#0b1020'], 1);
burst(23.0, 960, 360, 90, ['#fff', '#ffe14a', '#ff2e93', '#7fd4ff', '#5be3a0'], 1.5);
burst(25.0, 960, 800, 40, ['#fff', '#ffe14a', '#ff2e93'], 1.1);

// the cursor's walk through scene 4
const WALK = [[8.9, 1100, 760], [9.6, 1250, 340], [10.1, 1300, 330], [11.5, 1180, 720]];
function walk(t) {
  if (t < WALK[0][0] - 0.2 || t > WALK[WALK.length - 1][0] + 0.3) return null;
  let a = WALK[0];
  let b = WALK[1];
  for (let i = 0; i < WALK.length - 1; i++) if (t >= WALK[i][0]) { a = WALK[i]; b = WALK[i + 1]; }
  const p = io(prog(t, a[0], b[0]));
  return { x: lerp(a[1], b[1], p), y: lerp(a[2], b[2], p) };
}

function sceneAt(t) {
  return t < 2 ? 'warm' : t < 4 ? 'xray' : t < 6 ? 'hot' : t < 8 ? 'cool' : t < 12 ? 'grape' : t < 16 ? 'mint' : t < 19 ? 'hot' : t < 23 ? 'night' : 'sky';
}
const cuts = [0, 2, 4, 6, 8, 12, 16, 19, 23];

function render(t) {
  // ── the room: a dithered field that keeps moving, and a camera that never sits still
  const key = sceneAt(t);
  const speed = key === 'sky' ? 0.8 : key === 'night' ? 1.3 : 1.0;
  drawField(t, PAL[key], speed, key === 'hot' ? 1.4 : 1);
  const tb = t - Math.floor(t / BEAT) * BEAT;
  const down = Math.floor(t / BEAT) % 4 === 0;
  const punch = Math.exp(-tb * 9) * (down ? 1 : 0.5);
  const cutAge = Math.min(...cuts.map((c) => (t >= c ? t - c : 9)));
  const hit = Math.exp(-cutAge * 10);
  const cs = 1 + 0.016 * punch + 0.05 * hit;
  const cr = nz(t, 1) * 0.35 * (punch + hit * 2) + Math.sin(t * 0.7) * 0.25;
  const cx = Math.sin(t * 0.9) * 7 + nz(t, 2) * 14 * hit;
  const cy = Math.cos(t * 1.1) * 6 + nz(t, 3) * 14 * hit;
  cam.style.transform = `translate(${cx}px, ${cy}px) rotate(${cr}deg) scale(${cs})`;
  bg.style.transform = `translate(${-cx * 1.6}px, ${-cy * 1.6}px)`;
  $('flash').style.opacity = String(Math.exp(-cutAge * 16) * (t < 0.5 ? 0.7 : 0.8));
  $('flash').style.background = t >= 16 && t < 19 ? '#fff' : t >= 19 && t < 23 ? '#ff5aa8' : '#fff';

  for (const s of scenes) s.el.style.display = t >= s.a && t < s.b ? 'block' : 'none';
  const f = $('stage').querySelector('.fine');
  f.style.opacity = String(t > 0.6 && t < 15.6 ? out3(prog(t, 0.6, 1.0)) * (1 - prog(t, 15.3, 15.6)) : 0);

  // ── 0 to 4.5: the listing, the scan, the findings
  if (t < 4.5) {
    const u = t;
    if (t < 2) {
      const sp = spring(u);
      setT(cardw, { x: 960, y: 430 + Math.sin(t * 3) * 8, s: 2.6 + (1 - 2.6) * sp, r: -3 + -14 * (1 - sp) + Math.sin(t * 2.3) * 1.2 });
      cardw.style.opacity = String(Math.min(1, u * 40));
      if (t > 1.5) { const j = (t - 1.5) * 2; cardw.style.transform += ` translate(${nz(t * 30, 4) * 10 * j}px, ${nz(t * 30, 5) * 8 * j}px)`; }
    } else if (t < 4.0) {
      const k = out3(prog(t, 2.0, 2.4));
      setT(cardw, { x: lerp(960, 960, k), y: lerp(430, 520, k) + Math.sin(t * 3) * 6, s: lerp(1, 0.72, k), r: lerp(-3, -1.5, k) + Math.sin(t * 2.3) * 0.8 });
    } else {
      const k = out4(prog(t, 4.0, 4.45));
      setT(cardw, { x: 960 + k * 1700, y: 520 - k * 600, s: 0.72, r: -1.5 + k * 70, o: 1 - k });
    }
    draws0.forEach((el, i) => {
      el.style.strokeDasharray = '1';
      el.style.strokeDashoffset = String(1 - out3(prog(t, 0.1 + i * 0.05, 0.7 + i * 0.05)));
    });
    // the scan
    const p = io(prog(t, 2.2, 3.0));
    cardX.style.clipPath = `inset(0 ${(1 - p) * 100}% 0 0)`;
    scanEl.style.left = `${p * 900 - 7}px`;
    scanEl.style.opacity = String(p > 0 && p < 1 ? 1 : 0);

    // the caption, letter by letter, then it gives itself away
    caps0.forEach((c, i) => {
      const uu = t - (0.45 + i * 0.045);
      const sp2 = spring(uu);
      const glitch = t > 1.55 && t < 2.0 ? nz(t * 25, i) : 0;
      c.style.transform = `translateY(${(1 - sp2) * -170 + glitch * 16}px) rotate(${(1 - sp2) * 18 + glitch * 7}deg) scale(${1 + (1 - sp2) * 0.6})`;
      c.style.opacity = uu < 0 ? '0' : '1';
      c.style.color = glitch > 0.45 ? '#ff2e93' : glitch < -0.45 ? '#2447e6' : INK;
    });
    setT(cap0, { x: 960, y: 940, o: t < 2.0 ? 1 : 0 });
    slam(starA, t, 0.75, { x: 1530, y: 230, r0: 60, rest: 10, s0: 0.1, dx: 0, dy: 0, bob: 8, o: t < 2.0 ? 1 : 0 });
    slam(likeNew, t, 1.0, { x: 400, y: 190, r0: -40, rest: -10, s0: 0.1, dx: 0, dy: 0, bob: 6, o: t < 2.0 ? 1 : 0 });
    // the turn
    slam(wait, t, 2.0, { x: 960, y: 100, dy: 0, dx: 0, r0: 6, rest: -1.5, s0: 2.4, bob: 4, o: t < 4.0 ? 1 : 0 });
    FINDINGS.forEach((fnd, i) => {
      const uu = t - fnd.t;
      if (uu < 0) { fnd.el.style.opacity = '0'; return; }
      const sp3 = spring(uu);
      const out = t >= 4.0 ? out4(prog(t, 4.0, 4.4)) : 0;
      const ex = fnd.x + (fnd.x < 960 ? -1 : 1) * out * 1500;
      setT(fnd.el, {
        x: lerp(960, ex, Math.min(1.25, sp3)),
        y: lerp(520, fnd.y + Math.sin(t * 3.1 + i) * 8, Math.min(1.25, sp3)) - out * 500,
        s: Math.max(0.05, sp3) * (1 - out * 0.3),
        r: fnd.r + (1 - sp3) * 160 + Math.sin(t * 4 + i) * 1.4 + out * 80,
        o: Math.min(1, uu * 40) * (1 - out),
      });
    });
  }

  // ── 4 to 6: the headline
  if (t >= 4 && t < 6) {
    const times1 = [4.0, 4.25, 4.5];
    const times2 = [5.0, 5.25, 5.5];
    l1.forEach((it, i) => popWord(it, t, times1[i], i, i % 2 === 0));
    l2.forEach((it, i) => popWord(it, t, times2[i], i + 3, i % 2 === 1));
    sq.style.strokeDasharray = '1';
    sq.style.strokeDashoffset = String(1 - out3(prog(t, 5.75, 5.97)));
  }

  // ── 6 to 8: the other half
  if (t >= 6 && t < 8) {
    slam(mark, t, 6.0, { x: 960, y: 330, dy: 0, r0: -8, s0: 3.2, bob: 6 });
    const rp = prog(t, 6.0, 6.6);
    setT(ring3, { x: 960, y: 330, s: 1 + rp * 9, o: (1 - rp) * (t >= 6 ? 1 : 0) });
    [6.5, 6.75, 7.0, 7.25].forEach((tt, i) => popWord(l3[i], t, tt, i, i % 2 === 0));
  }

  // ── 8 to 12: the extension
  if (t >= 8 && t < 12) {
    const a = spring(t - 8.0);
    const tilt = lerp(9, 5, Math.min(1, a));
    setT(panel, { x: 1420 + 700 * (1 - a), y: 560 + Math.sin(t * 2) * 8, s: 1, r: tilt + (1 - a) * 22, o: Math.min(1, (t - 8) * 40) });
    pB.style.opacity = String(prog(t, 10.2, 10.4));
    // rings: pulse while they are the point
    const pulse = (id, a0, b0) => {
      const el = prings[id];
      const on = t > a0 && t < b0;
      const k = on ? spring(t - a0) : 0;
      el.style.opacity = on ? String(Math.min(1, (t - a0) * 20)) : '0';
      el.style.transform = `scale(${lerp(1.5, 1, Math.min(1.1, k))})`;
    };
    pulse('counts', 9.0, 10.0);
    pulse('find', 9.5, 10.2);
    pulse('body', 10.6, 11.0);
    pulse('source', 10.9, 11.5);
    pulse('ask', 11.3, 12.0);
    // three captions in turn
    const phase = t < 9.0 ? 0 : t < 10.5 ? 1 : 2;
    [[t4a, t4b, 0], [t4c, t4d, 1], [t4e, t4f, 2]].forEach(([ra, rb, ph]) => {
      const start = [8.0, 9.0, 10.5][ph];
      const show = phase === ph;
      ra.style.display = show ? 'flex' : 'none';
      rb.style.display = show ? 'flex' : 'none';
      if (show) {
        const wa = ra.firstChild;
        const wb2 = rb.firstChild;
        popWord({ el: wa }, t, start, ph * 2, ph % 2 === 0);
        popWord({ el: wb2 }, t, start + 0.25, ph * 2 + 1, ph % 2 === 1);
        setT(ra, { x: 640, y: 380 });
        setT(rb, { x: 640, y: 610 });
      }
    });
    slam(stkSource, t, 11.1, { x: 350, y: 770, dy: 0, dx: 0, r0: -50, rest: -5, s0: 0.1, bob: 6, o: t < 12 ? 1 : 0 });
    slam(stkAsk, t, 11.5, { x: 430, y: 915, dy: 0, dx: 0, r0: 50, rest: 3, s0: 0.1, bob: 5, o: t < 12 ? 1 : 0 });
    const w = walk(t);
    const clickT = 10.1;
    if (w) {
      setT(cursor, { x: w.x + 25, y: w.y + 30, s: t > clickT && t < clickT + 0.12 ? 0.82 : 1, o: 1 });
      const cp = prog(t, clickT, clickT + 0.5);
      setT(clickRing, { x: w.x, y: w.y, s: 0.4 + cp * 1.5, o: cp > 0 && cp < 1 ? 1 - cp : 0 });
    }
  }
  if (t < 8.6 || t >= 12) { cursor.style.opacity = '0'; clickRing.style.opacity = '0'; }

  // ── 12 to 16: compare
  if (t >= 12 && t < 16) {
    const a = spring(t - 12.25);
    const zin = io(prog(t, 13.0, 13.55)) * (1 - io(prog(t, 14.9, 15.4)));
    const sBase = 0.92;
    const s = lerp(sBase, 1.32, zin);
    const cxw = lerp(960, 960 + s * 240, zin);
    const cyw = lerp(620, 560 - s * 90, zin);
    const rotY = lerp(-34, -5, Math.min(1, a)) * (1 - zin);
    const rotX = lerp(14, 3, Math.min(1, a)) * (1 - zin);
    win.style.opacity = String(t < 12.25 ? 0 : 1);
    win.style.transform = `translate(${cxw + (1 - Math.min(1, a)) * -1300}px, ${cyw}px) translate(-50%, -50%) rotateY(${rotY}deg) rotateX(${rotX}deg) scale(${s})`;
    const pulse = (id, a0, b0) => {
      const el = wrings[id];
      const on = t > a0 && t < b0;
      el.style.opacity = on ? String(Math.min(1, (t - a0) * 20)) : '0';
      el.style.transform = `scale(${lerp(1.4, 1, Math.min(1.1, spring(t - a0)))})`;
    };
    pulse('e1', 13.5, 14.5);
    pulse('e2', 13.65, 14.5);
    pulse('s1', 14.55, 15.4);
    pulse('s2', 14.65, 15.4);
    pulse('s3', 14.75, 15.4);
    popWord({ el: t5a.firstChild }, t, 12.0, 0, true);
    setT(t5a, { x: 960, y: 118, o: 1 - prog(t, 12.9, 13.1) });
    popWord({ el: t5b.firstChild }, t, 15.0, 1, false);
    setT(t5b, { x: 960, y: 940, o: t >= 15.0 ? 1 : 0 });
    slam(stkSame, t, 13.7, { x: 440, y: 250, dy: 0, dx: 0, r0: -40, rest: -6, s0: 0.1, bob: 6, o: t < 14.8 ? 1 : 0 });
    slam(stkAlso, t, 14.6, { x: 1450, y: 300, dy: 0, dx: 0, r0: 40, rest: 4, s0: 0.1, bob: 6, o: t < 15.6 ? 1 : 0 });
  }

  // ── 16 to 19: solid, partial, thin
  if (t >= 16 && t < 19) {
    grades.forEach((g, i) => {
      const sp = spring(t - g.t);
      const dir = g.fromLeft ? -1 : 1;
      g.el.style.top = `${g.y - 190}px`;
      g.el.style.transform = `translateX(${dir * 1960 * (1 - Math.min(1, sp))}px) skewX(${dir * -8 * (1 - Math.min(1, sp))}deg)`;
      g.el.style.opacity = t < g.t ? '0' : '1';
      g.bars.forEach((b, j) => { b.style.transform = `scaleY(${out4(prog(t, g.t + 0.2 + j * 0.1, g.t + 0.6 + j * 0.1))})`; b.style.transformOrigin = '50% 100%'; });
      const w = g.el.querySelector('.w');
      w.style.transform = `translateX(${Math.sin(t * 2 + i) * 6}px) rotate(${Math.sin(t * 1.7 + i) * 0.5}deg)`;
    });
    slam(stkDoubt, t, 18.0, { x: 1230, y: 880, dy: 0, dx: 0, r0: 12, rest: -2.5, s0: 2.2, bob: 6 });
  }

  // ── 19 to 23: the promises
  if (t >= 19 && t < 23) {
    mqs.forEach((m, i) => {
      const dirn = i % 2 ? 1 : -1;
      m.style.transform = `translateX(${dirn * ((t - 19) * 260 % 1700) - (dirn > 0 ? 1700 : 0)}px) rotate(-7deg)`;
      m.style.opacity = '1';
    });
    promises.forEach((p, i) => {
      slam(p.el, t, p.t, { x: p.x, y: p.y, dy: 0, dx: i % 2 ? 1800 : -1800, r0: 0, rest: p.r, s0: 1, bob: 5, seed: i * 2 });
      const sp = spring(t - p.t - 0.15);
      const tick = p.el.querySelector('.tick');
      tick.style.transform = `scale(${Math.max(0, sp)})`;
    });
  }

  // ── 23 to 28.5: the end
  if (t >= 23) {
    slam(mark8, t, 23.0, { x: 960, y: 270, dy: 0, r0: -6, s0: 3.2, bob: 6 });
    const rp = prog(t, 23.0, 23.7);
    setT(ring8, { x: 960, y: 270, s: 1 + rp * 9, o: 1 - rp });
    const tm = [23.5, 23.75, 24.0, 24.25, 24.5, 24.75, 25.0];
    l8.forEach((it, i) => popWord(it, t, tm[i], i, i % 2 === 0));
    setT(r8, { x: 960, y: 590 });
    slam(cta1, t, 25.5, { x: 640, y: 790, dy: 0, dx: -500, r0: -10, rest: -2, s0: 1, bob: 5 });
    slam(cta2, t, 25.75, { x: 1330, y: 790, dy: 0, dx: 500, r0: 10, rest: 2, s0: 1, bob: 5, seed: 2 });
    slam(fine8, t, 26.25, { x: 960, y: 940, dy: 80, dx: 0, r0: 0, s0: 1, bob: 3 });
  }

  drawFx(t);
  sparkles(t, SPARK.slice(0, t < 4 ? 6 : 16), t < 2 ? '#ffffff' : '#ffe14a');
}
window.render = render;
window.DURATION = DURATION;
render(0);
