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

  // The link of the section being read gets a mark. Links to another page have no section here.
  const links = new Map();
  for (const link of document.querySelectorAll('.main-nav a[href^="#"]')) {
    const section = document.getElementById(link.getAttribute('href').slice(1));
    if (section) links.set(section, link);
  }
  if (links.size) {
    const current = new Set();
    const mark = () => {
      let last = null;
      for (const section of links.keys()) if (current.has(section)) last = section;
      for (const [section, link] of links) link.classList.toggle('is-active', section === last);
    };
    const spy = new IntersectionObserver((entries) => {
      for (const entry of entries) entry.isIntersecting ? current.add(entry.target) : current.delete(entry.target);
      mark();
    }, { rootMargin: '-40% 0px -55% 0px' });
    for (const section of links.keys()) spy.observe(section);
  }

  // On a phone a row of cards is a strip to swipe, and a card past the edge would
  // wait for a sideways scroll to appear, so the strip arrives as one piece.
  const strip = window.matchMedia && window.matchMedia('(max-width: 760px)').matches;
  const targets = document.querySelectorAll('.section .label, .section h2, .section-lead, .promise-list li, .step, .setup li, .download-card, .card, .window, .shot.plain, .faq details, ' + (strip ? '.gallery, .bento' : '.gallery li'));
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

// The art: the app's own dithered sky, drawn live; the headline rising word by word;
// the panel leaning toward the pointer; buttons that lean in. None of it is needed to
// read the page, so all of it waits for a browser that can draw it and a reader who
// has not asked for less motion, and every picture it replaces stays underneath.
(() => {
  if (!window.matchMedia || !('IntersectionObserver' in window)) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const root = document.documentElement;

  // ----- The sky. A cloud field is made once, then drawn through an 8x8 ordered dither into a
  // small palette, the way tools/dither_sky.py and the app draw it, and it drifts.
  const FW = 352, FH = 196;
  const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const PALETTES = {
    light: { sky: ['#3f6be9', '#6a8cf0', '#9db2f6'].map(rgb), cloud: ['#8f82e6', '#c28fe8', '#f58fb2', '#ffbf9f', '#fff0d4'].map(rgb) },
    dark: { sky: ['#03030c', '#0c1038', '#1d2a7a'].map(rgb), cloud: ['#1d2260', '#43347f', '#8a4a97', '#d97aa0', '#f5b9a8'].map(rgb) },
    // Black with an ember at the edges: the film's backdrop.
    ember: { sky: ['#000000', '#050507', '#0b0b10'].map(rgb), cloud: ['#14101f', '#2d1747', '#7a2f6e', '#d4574f', '#ffa96b'].map(rgb) },
  };
  const bayer = (() => {
    let m = [[0]];
    for (let size = 1; size < 8; size *= 2) {
      const next = Array.from({ length: size * 2 }, () => new Array(size * 2).fill(0));
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
        const v = m[y][x] * 4;
        next[y][x] = v; next[y][x + size] = v + 2; next[y + size][x] = v + 3; next[y + size][x + size] = v + 1;
      }
      m = next;
    }
    return m.map((row) => row.map((v) => (v + 0.5) / 64));
  })();
  const hash = (x, y, seed) => {
    let h = (Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(seed, 2147483647)) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
  };
  const noise = (x, y, period, seed) => {
    const x0 = Math.floor(x), y0 = Math.floor(y), fx = x - x0, fy = y - y0;
    const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    const xa = ((x0 % period) + period) % period, xb = (((x0 + 1) % period) + period) % period;
    const a = hash(xa, y0, seed), b = hash(xb, y0, seed), c = hash(xa, y0 + 1, seed), d = hash(xb, y0 + 1, seed);
    return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
  };
  let field = null;
  const makeField = () => {
    field = new Float32Array(FW * FH);
    for (let y = 0; y < FH; y++) for (let x = 0; x < FW; x++) {
      let value = 0, amp = 0.55, total = 0;
      for (let octave = 0; octave < 5; octave++) {
        const cells = 6 * 2 ** octave;
        value += amp * noise((x / FW) * cells, (y / FH) * cells * 0.62, cells, octave + 3);
        total += amp; amp *= 0.5;
      }
      field[y * FW + x] = value / total;
    }
  };
  const dark = window.matchMedia('(prefers-color-scheme: dark)');
  const skies = [];
  const paint = (sky, offset) => {
    const { canvas, ctx, image, w, h } = sky;
    const palette = PALETTES[sky.palette || (dark.matches ? 'dark' : 'light')];
    const clouds = palette.cloud.slice(0, sky.maxCloud || 5);
    const data = image.data, ox = Math.floor(offset);
    for (let y = 0; y < h; y++) {
      const fy = y / h, row = Math.floor((y / h) * FH) * FW;
      for (let x = 0; x < w; x++) {
        const fx = x / w, edge = Math.abs(fx - 0.5) * 2;
        const density = field[row + ((Math.floor(fx * (FW / 2)) + ox) % FW)] * (0.18 + 1.05 * edge ** 1.4) * (0.35 + Math.max(0, 1 - fy * 1.12));
        const b = bayer[y & 7][x & 7];
        let c;
        if (density < 0.36) c = palette.sky[Math.min(2, Math.floor(fy * 2.2 + b * 1.15))];
        else c = clouds[Math.max(0, Math.min(clouds.length - 1, Math.floor(((density - 0.36) / 0.34) * (clouds.length - 1) + b)))];
        const i = (y * w + x) * 4;
        data[i] = c[0]; data[i + 1] = c[1]; data[i + 2] = c[2]; data[i + 3] = 255;
      }
    }
    ctx.putImageData(image, 0, 0);
  };
  const addSky = (host, options) => {
    const canvas = document.createElement('canvas');
    canvas.className = 'dither';
    canvas.setAttribute('aria-hidden', 'true');
    canvas.width = options.w; canvas.height = options.h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    host.insertBefore(canvas, host.firstChild);
    skies.push({ canvas, ctx, image: ctx.createImageData(options.w, options.h), seen: false, ...options });
    host.classList.add('has-dither');
  };
  const sky = (selector, options) => { const host = document.querySelector(selector); if (host) addSky(host, options); };
  sky('.hero.home .stage', { w: 176, h: 196 });
  sky('.band.sky', { w: 384, h: 54 });
  sky('.section.film', { w: 192, h: 108, palette: 'ember', maxCloud: 4 });
  if (skies.length) {
    makeField();
    const watch = new IntersectionObserver((entries) => {
      for (const entry of entries) { const one = skies.find((s) => s.canvas.parentElement === entry.target); if (one) one.seen = entry.isIntersecting; }
    });
    for (const one of skies) watch.observe(one.canvas.parentElement);
    let offset = Math.random() * FW, last = 0;
    const tick = (now) => {
      requestAnimationFrame(tick);
      if (document.hidden || now - last < 1000 / 12) return;
      offset = (offset + (now - last > 500 ? 0 : (now - last) * 0.008)) % FW;
      last = now;
      for (const one of skies) if (one.seen) paint(one, offset);
    };
    for (const one of skies) paint(one, offset);
    requestAnimationFrame(tick);
  }

  // ----- The headline rises word by word, each word out of its own slot.
  const title = document.querySelector('.hero.home h1');
  if (title) {
    let n = 0;
    const split = (node) => {
      for (const child of [...node.childNodes]) {
        if (child.nodeType === 3) {
          const frag = document.createDocumentFragment();
          for (const part of child.textContent.split(/(\s+)/)) {
            if (!part) continue;
            if (/^\s+$/.test(part)) { frag.append(part); continue; }
            const slot = document.createElement('span'), word = document.createElement('span');
            slot.className = 'w'; word.textContent = part; word.style.setProperty('--i', String(n++));
            slot.append(word); frag.append(slot);
          }
          node.replaceChild(frag, child);
        } else if (child.nodeType === 1) split(child);
      }
    };
    split(title);
    title.classList.add('split');
  }

  // ----- The panel leans toward the pointer and the sky slides the other way, a little.
  const stage = document.querySelector('.hero.home .stage');
  if (stage && window.matchMedia('(hover: hover)').matches) {
    stage.addEventListener('pointermove', (event) => {
      const box = stage.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width - 0.5, y = (event.clientY - box.top) / box.height - 0.5;
      stage.style.setProperty('--ry', `${(x * 7).toFixed(2)}deg`);
      stage.style.setProperty('--rx', `${(-y * 5).toFixed(2)}deg`);
      stage.style.setProperty('--px', `${(-x * 22).toFixed(1)}px`);
      stage.style.setProperty('--py', `${(-y * 16).toFixed(1)}px`);
    }, { passive: true });
    stage.addEventListener('pointerleave', () => { for (const name of ['--rx', '--ry', '--px', '--py']) stage.style.removeProperty(name); });

    // The main buttons lean toward the pointer when it comes near.
    for (const button of document.querySelectorAll('.hero.home .button:not(.quiet), .bar-cta')) {
      button.addEventListener('pointermove', (event) => {
        const box = button.getBoundingClientRect();
        const x = event.clientX - (box.left + box.width / 2), y = event.clientY - (box.top + box.height / 2);
        button.style.translate = `${(x * 0.12).toFixed(1)}px ${(y * 0.25).toFixed(1)}px`;
      }, { passive: true });
      button.addEventListener('pointerleave', () => { button.style.translate = ''; });
    }
  }
  root.classList.add('art-ready');
})();
