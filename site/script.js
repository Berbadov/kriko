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
  const targets = document.querySelectorAll('.section .label, .section h2, .section-lead, .gallery li, .step, .setup li, .download-card, .window, .shot, .stats li, .statement-line, .cta-panel, .split-copy > div');
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
