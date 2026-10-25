// Every frame of the ad is a pure function of time: render(t) sets the whole page.
const $ = (id) => document.getElementById(id);
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const prog = (t, a, b) => clamp((t - a) / (b - a));
const lerp = (a, b, p) => a + (b - a) * p;
const out3 = (p) => 1 - Math.pow(1 - p, 3);
const out4 = (p) => 1 - Math.pow(1 - p, 4);
const io = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
const back = (p) => { const c = 1.7; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); };

const DURATION = 40.6;

function put(el, { o = 1, x = 0, y = 0, s = 1, r = 0 } = {}) {
  el.style.opacity = String(clamp(o));
  el.style.transform = `translate(${x}px, ${y}px) rotate(${r}deg) scale(${s})`;
}
// fade in over [a, b], out over [c, d]; rises by `rise` px as it comes in
function span(t, a, b, c, d, rise = 0) {
  const pin = out3(prog(t, a, b));
  const pout = c === undefined ? 0 : io(prog(t, c, d));
  return { o: pin * (1 - pout), y: (1 - pin) * rise - pout * rise * 0.6 };
}
// rings pop in, hold, go out
function ring(el, t, a, b, c, d) {
  const pin = back(prog(t, a, b));
  const pout = prog(t, c, d);
  put(el, { o: clamp(prog(t, a, a + 0.18)) * (1 - pout), s: lerp(1.05, 1, clamp(pin)) });
}

// ── set-up that depends on layout, run once ───────────────────────────────────
const panelRings = {
  // logical px inside the 400-wide panel picture, drawn at 1.25x from (1250, 60)
  ringCounts: [9, 54, 176, 24],
  ringFind: [14, 235, 372, 120],
  ringBody: [18, 318, 356, 98],
  ringSource: [22, 420, 108, 48],
  ringAsk: [27, 468, 348, 80],
};
function place() {
  const stage = $('stage');
  if (!$('ringBody')) {
    const el = document.createElement('div');
    el.id = 'ringBody';
    el.className = 'ring abs';
    stage.insertBefore(el, $('ringSource'));
  }
  for (const [id, [x, y, w, h]] of Object.entries(panelRings)) {
    const el = $(id);
    el.style.left = `${1250 + x * 1.25}px`;
    el.style.top = `${60 + y * 1.25}px`;
    el.style.width = `${w * 1.25}px`;
    el.style.height = `${h * 1.25}px`;
  }
  // the three words of the headline share one rise; the pill sits over the window
  if (!$('pill')) {
    const pill = document.createElement('div');
    pill.id = 'pill';
    pill.className = 'abs';
    pill.style.cssText = 'left:0;width:1920px;bottom:78px;text-align:center;opacity:0;';
    pill.innerHTML = '<span style="display:inline-block;background:#0b1020;color:#fff;font:700 52px/1 var(--display);letter-spacing:.01em;padding:22px 44px;border-radius:999px;box-shadow:0 18px 50px -12px rgba(11,16,32,.5)"></span>';
    stage.insertBefore(pill, $('row1'));
  }
}
place();

const words = [...document.querySelectorAll('#headline .w')];
const draws = [...document.querySelectorAll('#listing .d')];
const fills = [...document.querySelectorAll('#listing .f')];

// the Compare window's camera: base framing and the zoomed one
const CAM0 = { s: 0.84, x: 355, y: 232 };
const FOCUS = { fx: 480, fy: 560, qx: 960, qy: 560, s: 1.22 };
const CAM1 = { s: FOCUS.s, x: FOCUS.qx - FOCUS.s * FOCUS.fx, y: FOCUS.qy - FOCUS.s * FOCUS.fy };

function render(t) {
  // ── 1: the listing ───────────────────────────────────────────────────────────
  {
    const inn = out4(prog(t, 0, 0.9));
    const outp = io(prog(t, 3.9, 4.5));
    put($('listing'), { o: inn * (1 - outp), y: (1 - inn) * 44 - outp * 30, s: lerp(0.96, 1, inn) * lerp(1, 0.93, outp) });
    draws.forEach((el, i) => {
      el.style.strokeDasharray = '1';
      el.style.strokeDashoffset = String(1 - out3(prog(t, 0.3 + i * 0.1, 1.5 + i * 0.1)));
    });
    fills.forEach((el) => { el.style.opacity = String(out3(prog(t, 1.7, 2.3))); });
    for (const [sel, a] of [['.t', 0.7], ['.s', 0.9], ['.p', 1.1], ['.chips', 1.3]]) {
      const el = document.querySelector(`#listing ${sel}`);
      const p = out3(prog(t, a, a + 0.6));
      el.style.opacity = String(p);
      el.style.transform = `translateY(${(1 - p) * 14}px)`;
    }
    put($('cap1'), { ...span(t, 1.7, 2.4, 3.7, 4.2, 20) });
  }
  // ── 2: the headline ──────────────────────────────────────────────────────────
  {
    words.forEach((el, i) => {
      const pin = out4(prog(t, 4.5 + i * 0.13, 5.2 + i * 0.13));
      const pout = io(prog(t, 8.0 + i * 0.04, 8.6 + i * 0.04));
      el.style.transform = `translateY(${(1 - pin) * 112 - pout * 40}%)`;
      el.style.opacity = String(1 - pout);
    });
    const bp = io(prog(t, 6.3, 7.2));
    const bo = io(prog(t, 8.0, 8.5));
    $('bar').style.width = `${bp * 560}px`;
    $('bar').style.opacity = String(1 - bo);
  }
  // ── chrome that lives across the middle ──────────────────────────────────────
  put($('wordmark'), { o: Math.max(out3(prog(t, 8.9, 9.5)) * (1 - prog(t, 20.0, 20.3)), out3(prog(t, 27.4, 27.9))) * (1 - prog(t, 34.9, 35.4)) });
  put($('fine'), { o: out3(prog(t, 0.9, 1.5)) * (1 - prog(t, 22.6, 23.0)) });

  // ── 3: open a product page ───────────────────────────────────────────────────
  {
    const st = $('step1');
    const a = span(t, 8.95, 9.55, 14.3, 14.8, 24);
    put(st, a);
    $('step1').querySelector('.num').style.opacity = String(out3(prog(t, 8.95, 9.3)));
    const h = st.querySelector('h2');
    h.style.opacity = String(out3(prog(t, 9.1, 9.6)));
    h.style.transform = `translateY(${(1 - out3(prog(t, 9.1, 9.6))) * 28}px)`;
    const p = st.querySelector('p');
    p.style.opacity = String(out3(prog(t, 9.5, 10.1)));
    p.style.transform = `translateY(${(1 - out3(prog(t, 9.5, 10.1))) * 22}px)`;
    const f = st.querySelector('.find');
    f.style.opacity = String(out3(prog(t, 10.7, 11.2)));
    f.style.transform = `translateY(${(1 - out3(prog(t, 10.7, 11.2))) * 18}px)`;

    const pin = out4(prog(t, 9.0, 10.1));
    const crossfade = prog(t, 14.6, 15.2);
    put($('panelA'), { o: pin * (1 - crossfade) * (1 - prog(t, 20.0, 20.5)), x: (1 - pin) * 150, s: lerp(0.97, 1, pin) });
    ring($('ringCounts'), t, 10.5, 11.1, 12.1, 12.4);
    ring($('ringFind'), t, 12.3, 12.9, 14.0, 14.4);
  }
  // ── 4: every finding keeps its source ────────────────────────────────────────
  {
    const st = $('step2');
    put(st, span(t, 14.95, 15.55, 20.0, 20.4, 24));
    const h = st.querySelector('h2');
    h.style.opacity = String(out3(prog(t, 15.1, 15.6)));
    h.style.transform = `translateY(${(1 - out3(prog(t, 15.1, 15.6))) * 28}px)`;
    const p = st.querySelector('p');
    p.style.opacity = String(out3(prog(t, 15.5, 16.1)));
    p.style.transform = `translateY(${(1 - out3(prog(t, 15.5, 16.1))) * 22}px)`;
    const fin = prog(t, 14.6, 15.2);
    const fout = prog(t, 20.0, 20.6);
    put($('panelB'), { o: fin * (1 - fout), x: fout * 140, s: lerp(1, 0.97, fout) });
    ring($('ringBody'), t, 16.5, 17.1, 17.9, 18.2);
    ring($('ringSource'), t, 18.1, 18.7, 19.0, 19.3);
    ring($('ringAsk'), t, 19.2, 19.8, 19.95, 20.2);
  }
  // ── 5: compare ───────────────────────────────────────────────────────────────
  {
    const st = $('step3');
    put(st, span(t, 20.4, 21.0, 22.8, 23.4, 20));
    st.querySelector('.num').style.opacity = String(out3(prog(t, 20.4, 20.8)));
    const h = st.querySelector('h2');
    h.style.opacity = String(out3(prog(t, 20.55, 21.05)));
    h.style.transform = `translateY(${(1 - out3(prog(t, 20.55, 21.05))) * 28}px)`;

    const cap = $('cmpcap');
    cap.innerHTML = 'Add the products you are torn between.<br><b>The app lines them up side by side.</b>';
    put(cap, span(t, 21.1, 21.7, 22.8, 23.3, 16));

    const win = $('win');
    const enter = out4(prog(t, 21.0, 22.4));
    const zoom = io(prog(t, 22.8, 24.4));
    const leave = io(prog(t, 27.0, 27.6));
    const s = lerp(CAM0.s, CAM1.s, zoom);
    const x = lerp(CAM0.x, CAM1.x, zoom);
    const y = lerp(CAM0.y, CAM1.y, zoom) + (1 - enter) * 80 + leave * 30;
    win.style.opacity = String(enter * (1 - leave));
    win.style.transform = `translate(${x}px, ${y}px) scale(${s})`;
    $('tilt').style.transform = `rotateX(${(1 - enter) * 9}deg)`;

    const pill = $('pill');
    const text = t < 25.9 ? 'The same problem, found in two products.' : 'Each one says where else it shows up.';
    pill.firstChild.textContent = text;
    const swap = t < 25.9 ? span(t, 24.7, 25.2, 25.6, 25.9, 16) : span(t, 26.0, 26.5, 26.9, 27.3, 16);
    put(pill, swap);

    ring($('rEv1'), t, 24.9, 25.4, 25.7, 26.0);
    ring($('rEv2'), t, 25.05, 25.55, 25.7, 26.0);
    for (const [id, a] of [['rSh1', 26.1], ['rSh2', 26.2], ['rSh3', 26.3]]) ring($(id), t, a, a + 0.5, 26.95, 27.3);
  }
  // ── 6: Solid. Partial. Thin. ─────────────────────────────────────────────────
  {
    ['row1', 'row2', 'row3'].forEach((id, i) => {
      const a = 27.6 + i * 0.5;
      const sp = span(t, a, a + 0.6, 31.0 + i * 0.08, 31.6 + i * 0.08, 0);
      put($(id), { o: sp.o, x: (1 - out4(prog(t, a, a + 0.8))) * -70 });
      // the bars climb as the row arrives
      const bars = $(id).querySelectorAll('.bars i');
      bars.forEach((b, j) => { b.style.transform = `scaleY(${out4(prog(t, a + 0.15 + j * 0.1, a + 0.7 + j * 0.1))})`; b.style.transformOrigin = '50% 100%'; });
    });
    put($('wordsub'), span(t, 29.5, 30.1, 31.0, 31.6, 14));
  }
  // ── 7: three promises ────────────────────────────────────────────────────────
  {
    ['pr1', 'pr2', 'pr3'].forEach((id, i) => {
      const a = 31.9 + i * 0.75;
      const sp = span(t, a, a + 0.6, 35.0, 35.5, 0);
      put($(id), { o: sp.o, x: (1 - out4(prog(t, a, a + 0.8))) * 80 });
      const tick = $(id).querySelector('.tick');
      tick.style.transform = `scale(${back(prog(t, a + 0.15, a + 0.65))})`;
    });
  }
  // ── 8: the end card ──────────────────────────────────────────────────────────
  {
    const sky = out3(prog(t, 35.0, 36.0));
    $('sky').style.opacity = String(sky);
    $('sky').style.transform = `scale(${lerp(1.06, 1, sky)})`;
    const end = $('end');
    end.style.opacity = String(out3(prog(t, 35.6, 36.2)));
    const img = end.querySelector('img');
    img.style.transform = `translateY(${(1 - out4(prog(t, 35.7, 36.5))) * 30}px) scale(${lerp(0.94, 1, out4(prog(t, 35.7, 36.5)))})`;
    const tag = end.querySelector('.tag');
    const ptag = out4(prog(t, 36.3, 37.1));
    tag.style.opacity = String(ptag);
    tag.style.transform = `translateY(${(1 - ptag) * 36}px)`;
    const cta = end.querySelector('.cta');
    const pcta = out4(prog(t, 37.2, 37.9));
    cta.style.opacity = String(pcta);
    cta.style.transform = `translateY(${(1 - pcta) * 28}px)`;
    const fine = end.querySelector('.fine');
    fine.style.opacity = String(out3(prog(t, 37.7, 38.3)));
    $('fade').style.opacity = String(io(prog(t, 40.0, 40.6)) * 0.0);
  }
}
window.render = render;
window.DURATION = DURATION;
render(0);
