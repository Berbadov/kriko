'use strict';

(() => {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const mobileLayout = window.matchMedia('(max-width: 560px)');
  const compactTour = window.matchMedia('(max-width: 800px)');
  const menuButton = document.querySelector('.menu-toggle');
  const navigation = document.querySelector('.main-nav');
  const tabs = [...document.querySelectorAll('.tour-tab')];
  const panels = [...document.querySelectorAll('.tour-panel')];
  const playButton = document.querySelector('#play-tour');
  const counter = document.querySelector('.tour-counter');
  const dots = [...document.querySelectorAll('.demo-dots i')];
  const visual = document.querySelector('.hero-visual');
  const motionButton = document.querySelector('.motion-toggle');
  let activeStep = 0;
  let tourTimer = null;
  let isPlaying = false;

  // Product switches update one shared preview rather than running a carousel.
  // All public demonstration evidence is fictional and labeled in both languages.
  const productFields = {
    name: ['.listing-heading h2', '.tour-stage-bar > span:last-child', '#tour-panel-0 h3'],
    address: ['.address-text'], breadcrumb: ['.listing-breadcrumb'], quote: ['.seller-note strong'],
    sellerNote: ['.seller-note div > span'], category: ['.finding-label'],
    title: ['.floating-finding h3'], summary: ['.floating-finding > p'],
    caption: ['.example-label'], disclaimer: ['.tour-disclaimer'],
    mode: ['#tour-panel-0 .demo-topline .demo-tag:first-child'],
    status: ['#tour-panel-0 .demo-tag.subtle'], overview: ['#tour-panel-0 .demo-lead'],
    matchTitle: ['.match-row strong'], matchSummary: ['.match-row div > span'], matchStatus: ['.match-check'],
    topic: ['#tour-panel-1 .demo-topline .demo-tag:first-child'], type: ['#tour-panel-1 .demo-tag.subtle'],
    finding: ['#tour-panel-1 h3'], explanation: ['#tour-panel-1 .demo-lead'],
    question: ['.inspection-note strong'], inspection: ['.inspection-note p'],
    supported: ['.evidence-supported'], unresolved: ['.evidence-gap'],
    sourceCount: ['#tour-panel-2 .demo-tag.subtle'], caution: ['.evidence-footnote'],
  };
  const sourceLinks = [...document.querySelectorAll('.evidence-source')];
  const lang = document.documentElement.lang === 'tr' ? 'tr' : 'en';
  const products = window.KRIKO_EXAMPLES[lang];
  const t = (en, tr) => lang === 'tr' ? tr : en;
  function selectProduct(key) {
    const product = products[key];
    if (!product) return;
    stopTour();
    showStep(0);
    for (const [field, selectors] of Object.entries(productFields)) {
      selectors.forEach(selector => { document.querySelector(selector).textContent = product.fields[field]; });
    }
    document.querySelectorAll('.listing-specs span').forEach((element, index) => { element.textContent = product.specs[index]; });
    document.querySelectorAll('[data-art]').forEach(art => { art.toggleAttribute('hidden', art.dataset.art !== key); });
    sourceLinks.forEach((link, index) => {
      const source = product.sources[index];
      link.querySelector('.source-initial').textContent = source.initial;
      link.querySelector('strong').textContent = source.label;
      link.querySelector('strong + span').textContent = source.detail;
      link.querySelector('.source-excerpt').textContent = source.excerpt;
    });
    document.querySelectorAll('.product-option').forEach(button => { button.setAttribute('aria-pressed', String(button.dataset.product === key)); });
    document.querySelectorAll('.product-example').forEach(card => { card.classList.toggle('is-selected', card.dataset.product === key); });
    visual.setAttribute('aria-label', t(`Illustrative Kriko preview for ${product.fields.name}`, `${product.fields.name} için temsili Kriko önizlemesi`));
    document.querySelector('#product-status').textContent = t(`${product.fields.name} example selected. Fictional demonstration with sample evidence and an open question.`, `${product.fields.name} örneği seçildi. Örnek kanıtlar ve açık bir soru içeren kurgusal tanıtım.`);
  }
  document.querySelectorAll('[data-product]').forEach(control => control.addEventListener('click', event => {
    event.preventDefault();
    selectProduct(control.dataset.product);
    if (control.classList.contains('product-example') || control.hasAttribute('data-open-tour')) {
      tabs[0].focus({ preventScroll: true });
      document.querySelector('#how').scrollIntoView?.({ behavior: reducedMotion.matches ? 'auto' : 'smooth', block: 'start' });
    }
  }));

  motionButton.addEventListener('click', () => {
    const paused = document.body.classList.toggle('motion-paused');
    motionButton.setAttribute('aria-pressed', String(paused));
    motionButton.querySelector('span').textContent = paused ? t('Resume motion', 'Hareketi sürdür') : t('Pause motion', 'Hareketi duraklat');
    motionButton.querySelector('use').setAttribute('href', paused ? '#play-icon' : '#pause-icon');
    if (paused) stopTour();
  });

  function closeMenu(returnFocus = false) {
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', t('Open navigation', 'Menüyü aç'));
    navigation.classList.remove('is-open');
    if (returnFocus) menuButton.focus();
  }
  menuButton.addEventListener('click', () => {
    const open = menuButton.getAttribute('aria-expanded') !== 'true';
    menuButton.setAttribute('aria-expanded', String(open));
    menuButton.setAttribute('aria-label', open ? t('Close navigation', 'Menüyü kapat') : t('Open navigation', 'Menüyü aç'));
    navigation.classList.toggle('is-open', open);
  });
  navigation.querySelectorAll('a').forEach(link => link.addEventListener('click', () => closeMenu()));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menuButton.getAttribute('aria-expanded') === 'true') closeMenu(true);
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.nav-wrap')) closeMenu();
  });
  document.addEventListener('focusin', event => {
    if (!event.target.closest('.nav-wrap')) closeMenu();
  });
  mobileLayout.addEventListener('change', () => closeMenu());

  function showStep(index, focus = false) {
    activeStep = index;
    tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
      dots[i].classList.toggle('active', i === index);
    });
    counter.textContent = `0${index + 1} / 03`;
    if (focus) tabs[index].focus();
  }
  function stopTour() {
    window.clearTimeout(tourTimer);
    tourTimer = null;
    isPlaying = false;
    playButton.setAttribute('aria-pressed', 'false');
    playButton.querySelector('span').textContent = reducedMotion.matches ? t('Next walkthrough step', 'Sonraki örnek adımı') : t('Play walkthrough', 'Örneği oynat');
    playButton.querySelector('use').setAttribute('href', '#play-icon');
  }
  function scheduleStep() {
    tourTimer = window.setTimeout(() => {
      if (activeStep === tabs.length - 1) { stopTour(); return; }
      // Never hide a panel that contains the visitor's keyboard focus.
      if (!panels[activeStep].contains(document.activeElement)) showStep(activeStep + 1);
      scheduleStep();
    }, 6500);
  }
  function startTour() {
    stopTour();
    showStep(0);
    if (reducedMotion.matches) return;
    isPlaying = true;
    playButton.setAttribute('aria-pressed', 'true');
    playButton.querySelector('span').textContent = t('Pause walkthrough', 'Örneği duraklat');
    playButton.querySelector('use').setAttribute('href', '#pause-icon');
    scheduleStep();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => { stopTour(); showStep(index); });
    tab.addEventListener('keydown', event => {
      const next = compactTour.matches ? 'ArrowRight' : 'ArrowDown';
      const previous = compactTour.matches ? 'ArrowLeft' : 'ArrowUp';
      let destination;
      if (event.key === next) destination = (index + 1) % tabs.length;
      else if (event.key === previous) destination = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') destination = 0;
      else if (event.key === 'End') destination = tabs.length - 1;
      if (destination !== undefined) { event.preventDefault(); stopTour(); showStep(destination, true); }
    });
  });
  document.querySelectorAll('[data-next]').forEach(button => button.addEventListener('click', () => {
    stopTour();
    showStep(Number(button.dataset.next));
    panels[activeStep].focus({ preventScroll: true });
  }));
  playButton.addEventListener('click', () => {
    if (reducedMotion.matches) { showStep((activeStep + 1) % tabs.length); return; }
    if (isPlaying) stopTour(); else startTour();
  });
  document.querySelectorAll('[data-start-tour]').forEach(link => link.addEventListener('click', startTour));
  function updateTourPreferences() {
    document.querySelector('.tour-tabs').setAttribute('aria-orientation', compactTour.matches ? 'horizontal' : 'vertical');
    stopTour();
  }
  compactTour.addEventListener('change', updateTourPreferences);
  reducedMotion.addEventListener('change', updateTourPreferences);
  updateTourPreferences();

  if ('IntersectionObserver' in window) {
    if (!reducedMotion.matches) {
      const reveals = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) { entry.target.classList.add('is-visible'); reveals.unobserve(entry.target); }
        });
      }, { threshold: 0.08 });
      document.documentElement.classList.add('motion-ready');
      document.querySelectorAll('.reveal').forEach(element => reveals.observe(element));
    }
    let visualVisible = true;
    const ambient = new IntersectionObserver(entries => {
      visualVisible = entries[0].isIntersecting;
      visual.classList.toggle('is-paused', !visualVisible || document.hidden);
    });
    ambient.observe(visual);
    document.addEventListener('visibilitychange', () => {
      visual.classList.toggle('is-paused', !visualVisible || document.hidden);
      if (document.hidden) stopTour();
    });
    const walkthroughVisibility = new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting) stopTour();
    });
    walkthroughVisibility.observe(document.querySelector('.walkthrough-layout'));
    const sectionLinks = [...navigation.querySelectorAll('a[href^="#"]')];
    const sectionObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        const link = sectionLinks.find(item => item.hash === `#${entry.target.id}`);
        if (!link) return;
        if (entry.isIntersecting) link.setAttribute('aria-current', 'location'); else link.removeAttribute('aria-current');
      });
    }, { rootMargin: '-15% 0px -55% 0px' });
    sectionLinks.forEach(link => { const section = document.querySelector(link.hash); if (section) sectionObserver.observe(section); });
  }
  // Stop playback in background tabs even without IntersectionObserver support.
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopTour(); });
  let scrollScheduled = false;
  const progress = document.querySelector('.scroll-progress');
  function updateProgress() {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    const ratio = scrollable > 0 ? Math.min(1, Math.max(0, window.scrollY / scrollable)) : 0;
    progress.style.transform = `scaleX(${ratio})`;
    scrollScheduled = false;
  }
  window.addEventListener('scroll', () => {
    if (!scrollScheduled) { scrollScheduled = true; window.requestAnimationFrame(updateProgress); }
  }, { passive: true });
  window.addEventListener('resize', updateProgress);
  updateProgress();
  // Start with a buying-new example; the car inspection remains one click away.
  selectProduct('laptop');
})();
