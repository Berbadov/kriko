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
  // The additional examples follow sourced leads and keep unresolved questions explicit.
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
  const carExample = {
    fields: Object.fromEntries(Object.entries(productFields).map(([key, selectors]) => [key, document.querySelector(selectors[0]).textContent])),
    specs: [...document.querySelectorAll('.listing-specs span')].map(element => element.textContent),
    sources: sourceLinks.map(link => ({ url: link.href, initial: link.querySelector('.source-initial').textContent, label: link.querySelector('strong').textContent, detail: link.querySelector('strong + span').textContent })),
  };
  const researchFields = {
    mode: 'Quick look example', status: 'Discovery preview', caption: 'Illustrative listing · Sourced research lead',
    overview: 'Quick look can search beyond the product page: owner reports, teardowns and repair evidence. A lead can reveal a question you did not know to ask.',
    matchTitle: 'A lead worth following', matchSummary: 'Evidence, context and the question still open.', matchStatus: 'Lead',
    type: 'Research lead', sourceCount: '2 source pages',
    caution: 'A research lead is a starting point. The evidence and open question above show what is supported and what still needs investigation.',
    sellerNote: "There's more to a product than the description.",
  };
  const products = {
    cars: carExample,
    laptop: {
      fields: { ...researchFields, name: 'MacBook Air M2', address: 'your-next-laptop / macbook-air', breadcrumb: 'Laptops / Apple / MacBook Air', quote: '“Ready for your next big idea.”',
        category: 'Storage layout · Teardown lead', title: 'Same name. Same internals?', summary: 'A teardown found one NAND chip in the 256 GB unit. Which configuration did the review actually test?',
        disclaimer: 'Illustrative Quick look using a teardown and model specifications; no live research is running.',
        topic: 'Configuration differences', type: 'Teardown lead', finding: 'Could the base model behave differently from the reviews?',
        explanation: 'iFixit found a single 256 GB NAND chip in the M2 Air it opened. That raises a less obvious question: does a review of another storage configuration describe the one you are buying?',
        supported: 'One NAND chip was observed in the 256 GB teardown unit.',
        unresolved: 'The effect on your workload needs tests of the exact configuration.',
        question: '“Which storage configuration was actually tested?”', inspection: 'Look for tests of the exact capacity and workload. Compare the teardown with those results before carrying a review’s conclusions across configurations.',
      },
      specs: ['Laptop', 'M2', '256 GB', 'Buying new'],
      sources: [
        { url: 'https://www.ifixit.com/News/62674/m2-macbook-air-teardown-apple-forgot-the-heatsink', initial: 'i', label: 'iFixit · Teardown', detail: 'First-hand observation of the 256 GB storage layout' },
        { url: 'https://support.apple.com/en-us/111867', initial: 'A', label: 'Apple · Model specifications', detail: 'Identify the model and available storage configurations' },
      ],
    },
    headphones: {
      fields: { ...researchFields, name: 'Sony WH-1000XM5', address: 'your-next-listen / wh-1000xm5', breadcrumb: 'Audio / Sony / WH-1000XM5', quote: '“Your favourite tracks. A little closer.”',
        category: 'Hinge durability · Owner reports', title: 'What happens after the reviews?', summary: 'Owners describe hinge breakage. Is there a pattern worth investigating before you buy?',
        disclaimer: 'Illustrative Quick look using owner reports and a repair page; no live research is running.',
        topic: 'Hinge durability', type: 'Owner-reported lead', finding: 'Hinge reports raise a question the spec sheet cannot answer.',
        explanation: 'Owners describe breaks around the hinge and swivel. Sony also publishes headband repair information. These sources open a durability question; they do not establish how often it happens or why.',
        supported: 'Owner accounts describe breakage; Sony lists a headband repair route.',
        unresolved: 'Cause, affected revisions and the failure rate are not established here.',
        question: '“Do independent reports describe the same failure?”', inspection: 'Compare the failure location, model revision, time in use and repair findings. Look for corroboration and the manufacturer’s response before treating reports as a pattern.',
      },
      specs: ['Over-ear', 'Wireless', 'Durability lead', 'Buying new'],
      sources: [
        { url: 'https://www.reddit.com/r/SonyHeadphones/comments/1fnr6i3/sony_wh1000xm5_hinge_breakage/', initial: 'R', label: 'Owner discussion · Reddit', detail: 'First-hand hinge reports and questions about failure locations' },
        { url: 'https://www.sony.com/electronics/support/wireless-headphones-bluetooth-headphones/wh-1000xm5/articles/00346233', initial: 'S', label: 'Sony · Repair information', detail: 'Manufacturer information on headband repairs' },
      ],
    },
    coffee: {
      fields: { ...researchFields, name: 'Breville Barista Express', address: 'your-next-coffee / barista-express', breadcrumb: 'Kitchen / Breville / Barista Express', quote: '“Your morning ritual, upgraded.”',
        category: 'Pressure & noise · Conflicting reports', title: 'Same buzz. Different explanations.', summary: 'Owners report buzzing at different points in brewing. The timing could change the question entirely.',
        disclaimer: 'Illustrative Quick look comparing owner accounts; no live research is running.',
        topic: 'Pressure & noise', type: 'Unresolved reports', finding: 'A symptom is a lead. The cause still needs work.',
        explanation: 'One owner describes buzzing during extraction, with replies suggesting normal pump noise. Another describes persistent buzzing after water flow and pressure trouble. Similar words may describe different problems.',
        supported: 'The accounts describe different timing and accompanying symptoms.',
        unresolved: 'These accounts do not diagnose a failed pump or solenoid.',
        question: '“When does it buzz—and does pressure change too?”', inspection: 'Compare when the noise starts, when it stops and whether pressure changes. Seek model-specific repair evidence rather than assigning one cause to every mention of buzzing.',
      },
      specs: ['Espresso', 'BES870', 'Unresolved lead', 'Buying new'],
      sources: [
        { url: 'https://www.reddit.com/r/espresso/comments/1rpidos/buzzing_noise_while_pressure_gauge_rises_breville/', initial: 'R', label: 'Owner discussion · During brewing', detail: 'A new owner asks about buzzing as pressure rises' },
        { url: 'https://www.reddit.com/r/espresso/comments/17z1e65/help_buzzing_noise_on_bbe_after_running_the_water/', initial: 'R', label: 'Owner account · After water flow', detail: 'Persistent noise and pressure symptoms in another machine' },
      ],
    },
  };
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
      link.href = source.url;
      link.querySelector('.source-initial').textContent = source.initial;
      link.querySelector('strong').textContent = source.label;
      link.querySelector('strong + span').textContent = source.detail;
    });
    document.querySelectorAll('.product-option').forEach(button => { button.setAttribute('aria-pressed', String(button.dataset.product === key)); });
    document.querySelectorAll('.product-example').forEach(card => { card.classList.toggle('is-selected', card.dataset.product === key); });
    visual.setAttribute('aria-label', `Illustrative Kriko preview for ${product.fields.name}`);
    document.querySelector('#product-status').textContent = `${product.fields.name} example selected. ${key === 'cars' ? 'Cars catalog finding.' : 'Research lead with evidence and an open question.'}`;
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
    motionButton.querySelector('span').textContent = paused ? 'Resume motion' : 'Pause motion';
    motionButton.querySelector('use').setAttribute('href', paused ? '#play-icon' : '#pause-icon');
    if (paused) stopTour();
  });

  function closeMenu(returnFocus = false) {
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', 'Open navigation');
    navigation.classList.remove('is-open');
    if (returnFocus) menuButton.focus();
  }
  menuButton.addEventListener('click', () => {
    const open = menuButton.getAttribute('aria-expanded') !== 'true';
    menuButton.setAttribute('aria-expanded', String(open));
    menuButton.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
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
    playButton.querySelector('span').textContent = reducedMotion.matches ? 'Next walkthrough step' : 'Play walkthrough';
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
    playButton.querySelector('span').textContent = 'Pause walkthrough';
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
