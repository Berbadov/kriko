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
