const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM, VirtualConsole } = require('jsdom');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'styles.css'), 'utf8');

function page({ reducedMotion = false, mobile = false, compact = mobile, observer = true } = {}) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(html, { url: 'https://kriko.example/', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole });
  const { window } = dom;
  const media = new Map();
  window.matchMedia = query => {
    if (!media.has(query)) {
      const item = new window.EventTarget();
      item.matches = query.includes('reduced-motion') ? reducedMotion : query.includes('560px') ? mobile : compact;
      item.media = query;
      item.change = matches => { item.matches = matches; item.dispatchEvent(new window.Event('change')); };
      media.set(query, item);
    }
    return media.get(query);
  };
  let timerID = 0;
  const timers = new Map();
  window.setTimeout = (callback, delay) => { const id = ++timerID; timers.set(id, { callback, delay }); return id; };
  window.clearTimeout = id => timers.delete(id);
  window.requestAnimationFrame = callback => callback();
  const observers = [];
  if (observer) {
    window.IntersectionObserver = class {
      constructor(callback) { this.callback = callback; this.targets = new Set(); observers.push(this); }
      observe(element) { this.targets.add(element); }
      unobserve(element) { this.targets.delete(element); }
      trigger(element, isIntersecting) { this.callback([{ target: element, isIntersecting }]); }
    };
  }
  window.eval(script);
  const document = window.document;
  const select = selector => document.querySelector(selector);
  const all = selector => [...document.querySelectorAll(selector)];
  const tick = () => {
    const next = timers.entries().next().value;
    assert.ok(next, 'a walkthrough timer is scheduled');
    timers.delete(next[0]);
    assert.equal(next[1].delay, 6500);
    next[1].callback();
  };
  const active = () => all('.tour-tab').findIndex(tab => tab.getAttribute('aria-selected') === 'true');
  return { window, document, select, all, media, timers, observers, tick, active, errors, close: () => dom.window.close() };
}

test('walkthrough starts with a new-product example, one selected tab and one visible panel', () => {
  const p = page();
  assert.equal(p.active(), 0);
  assert.equal(p.select('.listing-heading h2').textContent, 'MacBook Air M2');
  assert.match(p.select('.listing-specs').textContent, /Buying new/);
  assert.equal(p.all('.tour-panel:not([hidden])').length, 1);
  assert.equal(p.all('.tour-tab[tabindex="0"]').length, 1);
  assert.equal(p.timers.size, 0, 'playback is opt-in');
  assert.equal(p.errors.length, 0);
  p.close();
});

test('tabs and next buttons change content and keep focus out of hidden panels', () => {
  const p = page();
  p.select('[data-step="1"]').click();
  assert.equal(p.active(), 1);
  assert.equal(p.select('#tour-panel-0').hidden, true);
  assert.equal(p.select('#tour-panel-1').hidden, false);
  p.select('[data-next="2"]').click();
  assert.equal(p.active(), 2);
  assert.equal(p.document.activeElement.id, 'tour-panel-2');
  assert.equal(p.select('.tour-counter').textContent, '03 / 03');
  assert.equal(p.all('.demo-dots .active').length, 1);
  p.close();
});

test('desktop tabs support vertical arrows, wrapping, Home and End', () => {
  const p = page();
  function key(value) { p.all('.tour-tab')[p.active()].dispatchEvent(new p.window.KeyboardEvent('keydown', { key: value, bubbles: true })); }
  key('ArrowDown'); assert.equal(p.active(), 1); assert.equal(p.document.activeElement.id, 'tour-tab-1');
  key('End'); assert.equal(p.active(), 2);
  key('ArrowDown'); assert.equal(p.active(), 0);
  key('ArrowUp'); assert.equal(p.active(), 2);
  key('Home'); assert.equal(p.active(), 0);
  p.close();
});

test('compact tabs expose horizontal orientation and use left/right keys', () => {
  const p = page({ compact: true });
  assert.equal(p.select('.tour-tabs').getAttribute('aria-orientation'), 'horizontal');
  p.select('#tour-tab-0').dispatchEvent(new p.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  assert.equal(p.active(), 1);
  p.media.get('(max-width: 800px)').change(false);
  assert.equal(p.select('.tour-tabs').getAttribute('aria-orientation'), 'vertical');
  p.close();
});

test('requested playback advances through every step once and stops', () => {
  const p = page();
  p.select('#play-tour').click();
  assert.equal(p.select('#play-tour').getAttribute('aria-pressed'), 'true');
  assert.equal(p.select('#play-tour use').getAttribute('href'), '#pause-icon');
  p.tick(); assert.equal(p.active(), 1);
  p.tick(); assert.equal(p.active(), 2);
  p.tick();
  assert.equal(p.timers.size, 0);
  assert.equal(p.select('#play-tour').getAttribute('aria-pressed'), 'false');
  p.close();
});

test('manual selection cancels playback, and pause leaves the current step in place', () => {
  const p = page();
  p.select('#play-tour').click(); p.tick(); p.select('#play-tour').click();
  assert.equal(p.active(), 1);
  assert.equal(p.timers.size, 0);
  p.select('#play-tour').click();
  p.select('[data-step="2"]').click();
  assert.equal(p.active(), 2);
  assert.equal(p.timers.size, 0);
  p.close();
});

test('playback never hides a panel containing keyboard focus', () => {
  const p = page();
  p.select('#play-tour').click();
  p.select('#tour-panel-0 .demo-next').focus();
  p.tick(); assert.equal(p.active(), 0);
  assert.equal(p.document.activeElement.closest('.tour-panel').hidden, false);
  p.select('#play-tour').focus();
  p.tick(); assert.equal(p.active(), 1);
  p.close();
});

test('reduced-motion preference prevents timed playback and makes the control manual', () => {
  const p = page({ reducedMotion: true });
  p.select('[data-start-tour]').click();
  assert.equal(p.timers.size, 0);
  assert.equal(p.document.documentElement.classList.contains('motion-ready'), false);
  assert.equal(p.select('#play-tour span').textContent, 'Next walkthrough step');
  p.select('#play-tour').click(); assert.equal(p.active(), 1); assert.equal(p.timers.size, 0);
  p.select('#play-tour').click(); assert.equal(p.active(), 2);
  p.close();
});

test('changing reduced-motion preference cancels a running tour', () => {
  const p = page();
  p.select('#play-tour').click();
  p.media.get('(prefers-reduced-motion: reduce)').change(true);
  assert.equal(p.timers.size, 0);
  assert.equal(p.select('#play-tour span').textContent, 'Next walkthrough step');
  p.close();
});

test('mobile menu closes on navigation, Escape, outside click and breakpoint changes', () => {
  const p = page({ mobile: true });
  const button = p.select('.menu-toggle');
  button.click(); assert.equal(button.getAttribute('aria-expanded'), 'true');
  assert.equal(p.select('.main-nav').classList.contains('is-open'), true);
  p.document.dispatchEvent(new p.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  assert.equal(p.document.activeElement, button);
  button.click(); p.select('.main-nav a').click(); assert.equal(button.getAttribute('aria-expanded'), 'false');
  button.click(); p.select('#hero-title').click(); assert.equal(button.getAttribute('aria-expanded'), 'false');
  button.click(); p.media.get('(max-width: 560px)').change(false); assert.equal(button.getAttribute('aria-expanded'), 'false');
  p.close();
});

test('motion pause control updates its state and stops a running walkthrough', () => {
  const p = page();
  p.select('#play-tour').click();
  p.select('.motion-toggle').click();
  assert.equal(p.document.body.classList.contains('motion-paused'), true);
  assert.equal(p.select('.motion-toggle').getAttribute('aria-pressed'), 'true');
  assert.equal(p.select('.motion-toggle span').textContent, 'Resume motion');
  assert.equal(p.timers.size, 0);
  p.select('.motion-toggle').click();
  assert.equal(p.document.body.classList.contains('motion-paused'), false);
  p.close();
});

test('off-screen examples pause ambient motion and off-screen walkthroughs stop playback', () => {
  const p = page();
  const visual = p.select('.hero-visual');
  p.observers.find(item => item.targets.has(visual)).trigger(visual, false);
  assert.equal(visual.classList.contains('is-paused'), true);
  p.observers.find(item => item.targets.has(visual)).trigger(visual, true);
  assert.equal(visual.classList.contains('is-paused'), false);
  p.select('#play-tour').click();
  const tour = p.select('.walkthrough-layout');
  p.observers.findLast(item => item.targets.has(tour)).trigger(tour, false);
  assert.equal(p.timers.size, 0);
  p.close();
});

test('background tabs stop playback even without IntersectionObserver', () => {
  const p = page({ observer: false });
  assert.equal(p.document.documentElement.classList.contains('motion-ready'), false);
  p.select('#play-tour').click();
  Object.defineProperty(p.document, 'hidden', { configurable: true, value: true });
  p.document.dispatchEvent(new p.window.Event('visibilitychange'));
  assert.equal(p.timers.size, 0);
  p.select('[data-step="2"]').click(); assert.equal(p.active(), 2);
  p.close();
});

test('scroll reveals are progressive and active navigation reflects the observed section', () => {
  const p = page();
  const reveal = p.select('.reveal');
  const revealObserver = p.observers.find(item => item.targets.has(reveal));
  revealObserver.trigger(reveal, true);
  assert.equal(reveal.classList.contains('is-visible'), true);
  assert.equal(revealObserver.targets.has(reveal), false);
  const section = p.select('#catalogs');
  const navigationObserver = p.observers.find(item => item.targets.has(section));
  navigationObserver.trigger(section, true);
  assert.equal(p.select('.main-nav a[href="#catalogs"]').getAttribute('aria-current'), 'location');
  navigationObserver.trigger(section, false);
  assert.equal(p.select('.main-nav a[href="#catalogs"]').hasAttribute('aria-current'), false);
  p.close();
});

test('all local assets, anchors, icon references and ARIA relationships resolve', () => {
  const p = page();
  const ids = p.all('[id]').map(element => element.id);
  assert.equal(ids.length, new Set(ids).size, 'no duplicate IDs');
  for (const element of p.all('[href], [src]')) {
    const value = element.getAttribute('href') || element.getAttribute('src');
    if (value.startsWith('#')) assert.ok(p.document.getElementById(value.slice(1)), `missing target ${value}`);
    else if (!/^https?:/.test(value)) assert.ok(fs.existsSync(path.join(root, value)), `missing asset ${value}`);
  }
  for (const element of p.all('[aria-controls], [aria-labelledby]')) {
    const value = element.getAttribute('aria-controls') || element.getAttribute('aria-labelledby');
    for (const id of value.split(/\s+/)) assert.ok(p.document.getElementById(id), `missing ARIA target ${id}`);
  }
  for (const image of p.all('img')) assert.ok(image.alt);
  for (const link of p.all('[target="_blank"]')) assert.match(link.rel, /noopener/);
  assert.equal(p.all('h1').length, 1);
  assert.ok(p.select('main'));
  p.close();
});

test('stylesheet parses and provides breakpoints, motion preferences and hidden-panel layout', () => {
  const p = page();
  const style = p.document.createElement('style');
  style.textContent = css;
  p.document.head.append(style);
  assert.ok(style.sheet.cssRules.length > 150);
  assert.equal(p.errors.length, 0);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /max-width:\s*560px/);
  assert.match(css, /max-width:\s*800px/);
  assert.match(css, /\.tour-panel\[hidden\][^}]*visibility:\s*hidden/);
  assert.match(html, /<noscript>[\s\S]*\.tour-panel\[hidden\][^}]*visibility:visible/);
  const assetCSS = css.replace(/url\("data:[^"]*"\)/g, '');
  for (const match of assetCSS.matchAll(/url\(['"]?([^)'"\s]+)['"]?\)/g)) {
    assert.ok(fs.existsSync(path.join(root, match[1])), `missing CSS asset ${match[1]}`);
  }
  p.close();
});

test('without JavaScript, every walkthrough panel and navigation link remains readable', () => {
  // Inject the stylesheet at its original position, before the noscript override.
  const dom = new JSDOM(html.replace('<link rel="stylesheet" href="styles.css">', `<style>${css}</style>`));
  const { window } = dom;
  for (const panel of window.document.querySelectorAll('.tour-panel')) {
    const computed = window.getComputedStyle(panel);
    assert.equal(computed.display, 'block');
    assert.equal(computed.visibility, 'visible');
  }
  assert.equal(window.getComputedStyle(window.document.querySelector('.tour-tabs')).display, 'none');
  assert.equal(window.getComputedStyle(window.document.querySelector('.menu-toggle')).display, 'none');
  assert.equal(window.getComputedStyle(window.document.querySelector('.main-nav')).display, 'flex');
  assert.equal(window.getComputedStyle(window.document.querySelector('.product-picker')).display, 'none');
  for (const key of ['laptop', 'headphones', 'coffee']) {
    assert.match(window.document.querySelector(`.product-example[data-product="${key}"]`).href, /^https:\/\//);
  }
  dom.window.close();
});

test('every product selector updates the illustration, listing and complete walkthrough', () => {
  const p = page();
  const examples = [
    ['laptop', 'MacBook Air M2', 'nand', ['www.ifixit.com', 'support.apple.com']],
    ['headphones', 'Sony WH-1000XM5', 'hinge', ['www.reddit.com', 'www.sony.com']],
    ['coffee', 'Breville Barista Express', 'noise', ['www.reddit.com', 'www.reddit.com']],
  ];
  for (const [key, name, topic, domain] of examples) {
    p.select(`.product-option[data-product="${key}"]`).click();
    assert.equal(p.select('.listing-heading h2').textContent, name);
    assert.equal(p.select('#tour-panel-0 h3').textContent, name);
    assert.equal(p.select('.tour-stage-bar > span:last-child').textContent, name);
    assert.equal(p.select('.hero-product-art:not([hidden])').dataset.art, key);
    assert.equal(p.all('.hero-product-art:not([hidden])').length, 1);
    assert.match(p.select('#tour-panel-1').textContent.toLowerCase(), new RegExp(topic));
    assert.deepEqual(p.all('.evidence-source').map(source => new URL(source.href).hostname), domain);
    assert.equal(p.select('#tour-panel-0 .demo-tag').textContent, 'Quick look example');
    assert.match(p.select('.tour-disclaimer').textContent, /no live research/);
    assert.match(p.select('#product-status').textContent, new RegExp(name));
    assert.equal(p.all('.product-option[aria-pressed="true"]').length, 1);
    assert.equal(p.all('.product-example.is-selected').length, 1);
    assert.equal(p.errors.length, 0);
  }
  p.close();
});

test('returning to Cars restores the real finding, specs and original source links', () => {
  const p = page();
  p.select('.product-option[data-product="cars"]').click();
  const originalSources = p.all('.evidence-source').map(link => link.href);
  const originalFinding = p.select('#tour-panel-1 h3').textContent;
  p.select('.product-option[data-product="coffee"]').click();
  p.select('.product-option[data-product="cars"]').click();
  assert.equal(p.select('.listing-heading h2').textContent, 'Volkswagen Golf 7');
  assert.equal(p.select('#tour-panel-1 h3').textContent, originalFinding);
  assert.deepEqual(p.all('.evidence-source').map(link => link.href), originalSources);
  assert.deepEqual(p.all('.listing-specs span').map(span => span.textContent), ['2015', 'Petrol', 'Manual', 'Hatchback']);
  assert.equal(p.select('.hero-product-art:not([hidden])').dataset.art, 'cars');
  assert.equal(p.select('#tour-panel-0 .demo-tag').textContent, 'Cars catalog');
  p.close();
});

test('switching products stops playback and resets the walkthrough to its first step', () => {
  const p = page();
  p.select('#play-tour').click(); p.tick();
  assert.equal(p.active(), 1);
  p.select('.product-option[data-product="headphones"]').click();
  assert.equal(p.active(), 0);
  assert.equal(p.timers.size, 0);
  assert.equal(p.select('#play-tour').getAttribute('aria-pressed'), 'false');
  p.select('#play-tour').click(); p.tick();
  assert.match(p.select('#tour-panel-1 h3').textContent, /Hinge reports/);
  p.close();
});

test('product cards open the matching walkthrough and move keyboard focus to it', () => {
  const p = page();
  let scrollOptions;
  p.select('#how').scrollIntoView = options => { scrollOptions = options; };
  p.select('.product-example[data-product="laptop"]').click();
  assert.equal(p.select('#tour-panel-0 h3').textContent, 'MacBook Air M2');
  assert.equal(p.document.activeElement.id, 'tour-tab-0');
  assert.equal(scrollOptions.behavior, 'smooth');
  p.close();
});

test('product switching respects reduced motion and never starts autoplay', () => {
  const p = page({ reducedMotion: true });
  let scrollOptions;
  p.select('#how').scrollIntoView = options => { scrollOptions = options; };
  p.select('.product-example[data-product="coffee"]').click();
  assert.equal(scrollOptions.behavior, 'auto');
  assert.equal(p.select('.hero-product-art:not([hidden])').dataset.art, 'coffee');
  assert.equal(p.timers.size, 0);
  p.close();
});

test('new and used purchase paths open different checks with the correct sources', () => {
  const p = page();
  let scrollCount = 0;
  p.select('#how').scrollIntoView = () => { scrollCount++; };
  p.select('.purchase-path[data-product="cars"]').click();
  assert.equal(p.select('.listing-heading h2').textContent, 'Volkswagen Golf 7');
  assert.match(p.select('#tour-panel-1 h3').textContent, /Rear seals/);
  p.select('.purchase-path[data-product="laptop"]').click();
  assert.match(p.select('#tour-panel-1 h3').textContent, /base model/);
  assert.equal(new URL(p.select('.evidence-source').href).hostname, 'www.ifixit.com');
  assert.equal(scrollCount, 2);
  assert.equal(p.document.activeElement.id, 'tour-tab-0');
  p.close();
});

test('new-product examples investigate overlooked concerns rather than prior wear', () => {
  const p = page();
  for (const key of ['laptop', 'headphones', 'coffee']) {
    p.select(`.product-option[data-product="${key}"]`).click();
    assert.match(p.select('.listing-specs').textContent, /Buying new/);
    assert.doesNotMatch(p.select('#tour-panel-1').textContent, /worn battery|peeling earpads|maintenance history|last cleaned/i);
  }
  assert.match(p.select('.hero-description').textContent, /Brand-new or pre-owned/);
  assert.match(p.select('#questions').textContent, /new and used products/i);
  p.close();
});

test('each research lead separates sourced evidence, uncertainty and the next investigation', () => {
  const p = page();
  const evidence = {
    laptop: [/NAND chip/, /exact configuration/, /storage configuration/],
    headphones: [/Owner accounts/, /failure rate/, /independent reports/],
    coffee: [/different timing/, /do not diagnose/, /pressure change/],
  };
  for (const [key, [supported, unresolved, question]] of Object.entries(evidence)) {
    p.select(`.product-option[data-product="${key}"]`).click();
    assert.match(p.select('.evidence-supported').textContent, supported);
    assert.match(p.select('.evidence-gap').textContent, unresolved);
    assert.match(p.select('.inspection-note strong').textContent, question);
    assert.match(p.select('#product-status').textContent, /Research lead with evidence and an open question/);
  }
  p.select('.product-option[data-product="cars"]').click();
  assert.match(p.select('.evidence-supported').textContent, /leak paths/);
  assert.match(p.select('.evidence-gap').textContent, /particular vehicle/);
  p.close();
});
