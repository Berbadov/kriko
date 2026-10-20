// The only interaction the site needs: the menu on a narrow screen. Every other
// part of both pages works without JavaScript.
(() => {
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.getElementById('main-nav');
  if (!toggle || !nav) return;
  const lang = document.documentElement.lang;
  const words = lang === 'tr' ? { open: 'Menü', close: 'Kapat' } : { open: 'Menu', close: 'Close' };
  const set = (open) => {
    nav.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open ? words.close : words.open;
  };
  toggle.addEventListener('click', () => set(!nav.classList.contains('is-open')));
  nav.addEventListener('click', (event) => { if (event.target.closest('a')) set(false); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') set(false); });
})();
