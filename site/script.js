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
