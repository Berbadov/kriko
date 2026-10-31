// What the site needs from script: the menu on a narrow screen, and a pause button on each
// film in the guide. Every part of every page works without JavaScript.
(() => {
  const lang = document.documentElement.lang;
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.getElementById('main-nav');
  if (!toggle || !nav) return;
  const words = lang === 'tr' ? { open: 'Menü', close: 'Kapat' } : { open: 'Menu', close: 'Close' };
  const set = (open) => {
    nav.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open ? words.close : words.open;
  };
  toggle.addEventListener('click', () => set(!nav.classList.contains('is-open')));
  nav.addEventListener('click', (event) => { if (event.target.closest('a')) set(false); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && nav.classList.contains('is-open')) {
      set(false);
      toggle.focus();
    }
  });
  document.addEventListener('pointerdown', (event) => {
    if (!nav.contains(event.target) && !toggle.contains(event.target)) set(false);
  });
  // Collapse only once the controls work. Without script the links stay visible.
  document.documentElement.classList.add('menu-ready');
})();

// A film is a GIF, and a GIF cannot be paused, so pausing swaps in its still. The markup already
// shows the still to a reader who asked for less motion (a <source> in the picture), so the button
// starts as Play for them and as Pause for everyone else.
(() => {
  const lang = document.documentElement.lang;
  const demos = document.querySelectorAll('[data-demo]');
  const words = lang === 'tr'
    ? { pause: 'Duraklat', play: 'Oynat', pauseLabel: 'Animasyonu duraklat', playLabel: 'Animasyonu oynat' }
    : { pause: 'Pause', play: 'Play', pauseLabel: 'Pause the animation', playLabel: 'Play the animation' };
  for (const demo of demos) {
    const picture = demo.querySelector('picture');
    const image = picture && picture.querySelector('img');
    const still = picture && picture.querySelector('source');
    const caption = demo.querySelector('figcaption');
    if (!image || !still || !caption) continue;
    const film = image.getAttribute('src');
    const poster = still.getAttribute('srcset');
    let playing = !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'demo-toggle';
    const draw = () => {
      button.textContent = playing ? words.pause : words.play;
      button.setAttribute('aria-label', `${playing ? words.pauseLabel : words.playLabel}: ${demo.getAttribute('data-demo')}`);
    };
    button.addEventListener('click', () => {
      playing = !playing;
      if (playing) { still.remove(); image.src = film; } else { image.src = poster; }
      draw();
    });
    draw();
    caption.append(button);
  }
})();

// Scroll-in reveals, the header's shadow, the link of the section in view and the
// light that follows the pointer over a card. All of it is added as classes or
// custom properties, so a page without script (or a reader who asked for less
// motion) sees everything at once and still. The hero animates on load through
// CSS alone.
(() => {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const bar = document.querySelector('.topbar');
  if (bar) {
    const onScroll = () => bar.classList.toggle('is-scrolled', window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }
  if (window.matchMedia && window.matchMedia('(hover: hover)').matches) {
    for (const card of document.querySelectorAll('.card, .step, .gallery li, .setup li, .download-card, .promise-list li')) {
      card.classList.add('spot');
      card.addEventListener('pointermove', (event) => {
        const box = card.getBoundingClientRect();
        card.style.setProperty('--mx', `${event.clientX - box.left}px`);
        card.style.setProperty('--my', `${event.clientY - box.top}px`);
      }, { passive: true });
    }
  }
  if (!('IntersectionObserver' in window)) return;
  const targets = document.querySelectorAll('.section .label, .section h2, .section-lead, .gallery li, .step, .setup li, .download-card, .window, .shot, .stats li, .statement-line, .cta-panel, .split-copy > div');
  const seen = new WeakSet();
  const io = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting || seen.has(entry.target)) continue;
      seen.add(entry.target);
      // A row of siblings arrives left to right, a beat apart.
      const index = Array.prototype.indexOf.call(entry.target.parentElement.children, entry.target);
      entry.target.style.setProperty('--reveal-delay', `${Math.min(index, 4) * 80}ms`);
      entry.target.classList.add('is-in');
      io.unobserve(entry.target);
    }
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
  for (const el of targets) {
    el.classList.add('will-animate');
    io.observe(el);
  }
})();

// A card catches a little light where the pointer is: the sheet knows where you are
// looking. Only for a fine pointer, so a thumb on a phone never triggers it.
(() => {
  const fine = window.matchMedia && window.matchMedia('(pointer: fine)').matches;
  if (!fine) return;
  for (const card of document.querySelectorAll('.gallery li, .download-card')) {
    card.addEventListener('pointermove', (event) => {
      const box = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${event.clientX - box.left}px`);
      card.style.setProperty('--my', `${event.clientY - box.top}px`);
    });
  }
})();

// The hero's panel drifts a touch slower than the page while the first screen
// scrolls away: depth, and nothing else. The entrance animation rides on the
// card inside, so this transform is the figure's alone to move.
(() => {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const panel = document.querySelector('.hero .stage');
  if (!panel) return;
  let ticking = false;
  const place = () => {
    const y = Math.min(window.scrollY, window.innerHeight);
    panel.style.transform = `translateY(${y * -0.05}px)`;
    ticking = false;
  };
  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; requestAnimationFrame(place); }
  }, { passive: true });
})();


// The hero's aurora: a slow blue shader drawn on a canvas behind the hero copy.
// One static frame for a reader who asked for less motion, and the loop stops
// while the tab is hidden or the hero is off screen. Without WebGL the canvas
// removes itself and the sky wash alone carries the hero.
(() => {
  const canvas = document.querySelector('.hero-shader');
  if (!canvas) return;
  const gl = canvas.getContext('webgl', { alpha: true, antialias: true, depth: false, stencil: false, powerPreference: 'low-power' });
  if (!gl) { canvas.remove(); return; }
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const vert = 'attribute vec2 p; void main() { gl_Position = vec4(p, 0.0, 1.0); }';
  const frag = [
    'precision highp float;',
    'uniform vec2 u_res; uniform float u_time; uniform float u_dark;',
    'float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }',
    'float noise(vec2 p) { vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);',
    '  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y); }',
    'float fbm(vec2 p) { float v = 0.0; float a = 0.5; for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; } return v; }',
    'void main() {',
    '  vec2 uv = gl_FragCoord.xy / u_res;',
    '  vec2 p = vec2(uv.x * u_res.x / u_res.y, uv.y);',
    '  float t = u_time * 0.045;',
    '  float n = fbm(p * 2.1 + vec2(t, -t * 0.6));',
    '  float n2 = fbm(p * 3.3 + vec2(-t * 0.7, t * 0.4) + 5.2);',
    '  float band = smoothstep(0.25, 0.85, n) * smoothstep(0.9, 0.3, n2);',
    '  vec3 deep = vec3(0.05, 0.09, 0.35);',
    '  vec3 mid = vec3(0.18, 0.36, 1.0);',
    '  vec3 lite = vec3(0.62, 0.72, 1.0);',
    '  vec3 col = mix(deep, mid, band);',
    '  col = mix(col, lite, smoothstep(0.55, 0.95, n2) * 0.6);',
    '  float alpha = (0.14 + band * 0.5) * mix(0.55, 1.0, u_dark);',
    '  gl_FragColor = vec4(col, alpha);',
    '}',
  ].join('\n');
  const compile = (type, src) => {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) { canvas.remove(); throw new Error(gl.getShaderInfoLog(sh)); }
    return sh;
  };
  let prog;
  try {
    prog = gl.createProgram();
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, vert));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, frag));
    gl.linkProgram(prog);
    gl.useProgram(prog);
  } catch (e) { return; }
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const uRes = gl.getUniformLocation(prog, 'u_res');
  const uTime = gl.getUniformLocation(prog, 'u_time');
  const uDark = gl.getUniformLocation(prog, 'u_dark');
  const dark = () => window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const w = Math.max(1, Math.floor(canvas.clientWidth * dpr));
    const h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); }
  };
  const draw = (t) => {
    resize();
    gl.uniform2f(uRes, canvas.width, canvas.height);
    gl.uniform1f(uTime, t);
    gl.uniform1f(uDark, dark() ? 1 : 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
  if (reduced) { draw(0); window.addEventListener('resize', () => draw(0), { passive: true }); return; }
  let raf = 0, visible = true, inView = true;
  const start = performance.now();
  const loop = (now) => {
    if (visible && inView) draw((now - start) / 1000);
    raf = requestAnimationFrame(loop);
  };
  document.addEventListener('visibilitychange', () => { visible = !document.hidden; });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver((entries) => { inView = entries[0].isIntersecting; }, { threshold: 0 }).observe(canvas);
  }
  window.addEventListener('resize', resize, { passive: true });
  raf = requestAnimationFrame(loop);
})();
