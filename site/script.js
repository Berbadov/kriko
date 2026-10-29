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

// The hero's animated gradient field: a few slow-drifting radial blooms in the
// app's blues on a canvas. Off entirely for reduced-motion readers, when the
// tab is hidden, and when the canvas is not there (guide, problems pages).
(() => {
  const canvas = document.querySelector('.hero-canvas');
  if (!canvas) return;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const blooms = dark
    ? ['#2447e6', '#5a7bff', '#16277e', '#7c93ff']
    : ['#2447e6', '#7c93ff', '#a9bcff', '#dfe7ff'];
  let w = 0, h = 0, raf = 0, t = Math.random() * 1000;
  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  const draw = () => {
    t += 0.0016;
    ctx.clearRect(0, 0, w, h);
    for (let i = 0; i < 4; i++) {
      const x = w * (0.5 + 0.42 * Math.sin(t * (0.7 + i * 0.23) + i * 1.9));
      const y = h * (0.5 + 0.4 * Math.cos(t * (0.55 + i * 0.17) + i * 2.6));
      const r = Math.max(w, h) * (0.34 + 0.1 * Math.sin(t * 0.9 + i));
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, blooms[i] + '59');
      g.addColorStop(0.55, blooms[i] + '1f');
      g.addColorStop(1, blooms[i] + '00');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
  };
  const loop = () => { draw(); raf = requestAnimationFrame(loop); };
  resize();
  window.addEventListener('resize', resize, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) cancelAnimationFrame(raf);
    else raf = requestAnimationFrame(loop);
  });
  raf = requestAnimationFrame(loop);
})();

// Scroll-in reveals and the header's shadow. Both are added as classes, so a
// page without script (or a reader who asked for less motion) sees everything
// at once and still. The hero animates on load through CSS alone.
(() => {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const bar = document.querySelector('.topbar');
  if (bar) {
    const onScroll = () => bar.classList.toggle('is-scrolled', window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }
  if (!('IntersectionObserver' in window)) return;
  const targets = document.querySelectorAll('.section .label, .section h2, .section-lead, .gallery li, .step, .setup li, .download-card, .window');
  const seen = new WeakSet();
  const io = new IntersectionObserver((entries) => {
    let delay = 0;
    for (const entry of entries) {
      if (!entry.isIntersecting || seen.has(entry.target)) continue;
      seen.add(entry.target);
      entry.target.style.setProperty('--reveal-delay', `${Math.min(delay, 240)}ms`);
      delay += 60;
      entry.target.classList.add('is-in');
      io.unobserve(entry.target);
    }
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
  for (const el of targets) {
    el.classList.add('will-animate');
    io.observe(el);
  }
})();

// Scroll-driven motion, all in one rAF-throttled handler: the header's reading
// progress bar, the hero canvas drifting up as you scroll away, and parallax
// on elements carrying data-depth (gallery shots, the hero stage). Off for
// reduced-motion readers; without script nothing moves and nothing is hidden.
(() => {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const progress = document.querySelector('.scroll-progress');
  const canvas = document.querySelector('.hero-canvas');
  const stage = document.querySelector('.stage[data-depth]');
  const layers = [...document.querySelectorAll('[data-depth]')].filter((el) => el !== stage);
  if (!progress && !canvas && !stage && !layers.length) return;
  let ticking = false;
  const update = () => {
    ticking = false;
    const y = window.scrollY;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    if (progress) progress.style.transform = `scaleX(${max > 0 ? Math.min(1, y / max) : 0})`;
    if (canvas && y < window.innerHeight * 1.2) canvas.style.transform = `translateY(${y * 0.18}px)`;
    if (stage) stage.style.transform = `translateY(${y * -0.06}px)`;
    for (const el of layers) {
      const rect = el.getBoundingClientRect();
      if (rect.bottom < -80 || rect.top > window.innerHeight + 80) continue;
      const center = rect.top + rect.height / 2 - window.innerHeight / 2;
      el.style.transform = `translateY(${center * -Number(el.dataset.depth)}px)`;
    }
  };
  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  update();
})();
