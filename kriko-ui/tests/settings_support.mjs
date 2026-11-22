import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { createRequire } from 'node:module'
import ts from 'typescript'
import React from 'react'
import { JSDOM } from 'jsdom'

/** Shared by the settings tests. The sources are compiled for real; only the
 *  engine hooks (the things that would call the local API) are stubbed. */

const nodeRequire = createRequire(import.meta.url)
export const h = React.createElement

/** Compile one TSX or TS source to CommonJS, the way the app's build does. */
export const compile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText

function resolveFile(from, request) {
  const base = resolve(dirname(from), request)
  for (const candidate of [base, `${base}.tsx`, `${base}.ts`, join(base, 'index.tsx'), join(base, 'index.ts')]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate
  }
  throw new Error(`settings test cannot resolve ${request} from ${from}`)
}

/**
 * Load a source file with its own relative imports compiled for real. `stubs` is
 * keyed by the import text a file uses (`'../../engine/settings'`), so a stub
 * replaces that import in every file of the graph. Stylesheets load as nothing.
 * Each call is a fresh graph, so two calls can hold two different stubs.
 */
export function loadSource(entry, stubs = {}) {
  const cache = new Map()
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports
    const module = { exports: {} }
    cache.set(file, module)
    const code = compile(readFileSync(file, 'utf8'))
    new Function('require', 'module', 'exports', code)(requireFrom(file), module, module.exports)
    return module.exports
  }
  const requireFrom = (from) => (request) => {
    if (Object.hasOwn(stubs, request)) return stubs[request]
    if (request.endsWith('.css')) return {}
    if (request.startsWith('.')) return load(resolveFile(from, request))
    return nodeRequire(request)
  }
  return load(resolve(entry))
}

export const prefsDoc = {
  chosen: {},
  research: { thoroughness: 50, validation_sensitivity: 50, sources: 0, kinds: ['forums'] },
  source_kinds: [{ id: 'forums', label: 'Forums' }, { id: 'reviews', label: 'Reviews' }],
  classification_providers: [{ id: 'agent', label: 'Agent', ready: true }],
  market_regions: [{ id: 'auto', label: 'Automatic' }],
  providers: [],
}

export const sharedDoc = {
  bound: true,
  device: '',
  grant: { present: false, label: '', providers: [], state: '' },
  trial: { limit: 10, used: 0, left: 10, available: false },
  providers: [],
}

/** The local model hooks, idle: no runtime, no machine, no models. A test passes `local` to change them. */
const LOCAL_IDLE = { machine: null, machineProblem: '', runtime: null, models: [], modelsLoaded: true, recommended: { model: 'rec:2b', installed: false }, library: null, libraryProblem: '', pull: null, problem: '', starting: false, vllm: null, checking: false }

/** The engine hooks every settings section reads, stubbed. `options` picks the data. */

export function screenStubs(options = {}) {
  const usePrefsDoc = () => ({ doc: 'doc' in options ? options.doc : prefsDoc, problem: options.problem ?? '', save: options.save ?? (async () => {}) })
  return {
    '../../prefs': {
      usePrefs: () => ({ theme: options.theme ?? 'system', setTheme() {}, profile: 'standard', setProfile() {}, reduce: false, setReduce() {} }),
    },
    '../../engine/sensitivity': { useSensitivity: () => ({ sensitivity: 'all', choose: async () => '' }) },
    '../../tour/Tour': { startTour() {} },
    '../../engine/settings': {
      usePrefsDoc,
      useKeys: () => ({ doc: { providers: options.providers ?? [] }, problem: '', tested: {}, set: options.setKey ?? (async () => {}), remove: options.removeKey ?? (() => {}), test: options.testKey ?? (() => {}) }),
      useSharedAccess: () => ({ doc: 'shared' in options ? options.shared : sharedDoc, problem: '', code: '', unlock() {}, forget() {}, make() {} }),
      useAbout: () => ({ version: '0.4.0', folder: '/data' }),
      usePresence: () => ({ presence: null, reload: async () => {} }),
      useSpent: () => options.spent ?? null,
    },
    '../../engine/appupdate': {
      useAppUpdate: () => ({ phase: 'idle', checked: false, release: null, problem: '', canInstall: false, check() {}, install() {} }),
    },
    '../../arc/checkbox/checkbox': {
      Checkbox: ({ checked, label, description }) =>
        h('div', null, h('button', { role: 'checkbox', 'aria-checked': checked, 'aria-label': label }), h('label', null, label), h('span', null, description)),
    },
    '../../engine/caps': {
      CAP_ORDER: ['llm_api', 'web_search'],
      CAP_WORDS: {
        llm_api: { title: 'Model calls', unit: 'calls', money: false },
        web_search: { title: 'Web searches', unit: 'searches', money: false },
      },
      usedToday: () => null,
      useCaps: () => ({ caps: {}, setCap() {} }),
    },
    '../../engine/usage': { useUsage: () => ({ meters: null, demo: !!options.demo }) },
    // The sections that are not under test reach the engine's API client (which reads import.meta)
    // through these; the screen tests draw no effects, so a plain link and a plain group stand in.
    '../panels/Local': {
      Loading: () => h('div', null, 'Loading'),
      InstalledModels: () => h('section', null, h('h3', null, 'Models on this computer')),
      FitModels: () => h('section', null, h('h3', null, 'Models that fit this computer')),
      VllmRow: () => h('div', null, 'vLLM'),
    },
    '../panels/Agents': { AgentsSection: () => h('section', null, h('h3', null, 'Agents')) },
    '../panels/Chat': { ChatSettings: () => h('section', null, h('h3', null, 'Chat')) },
    '../ExternalLink': { ExternalLink: ({ children, className }) => h('a', { className }, children), openLink() {} },
    '../../engine/local': {
      useLocal: () => ({ ...LOCAL_IDLE, recheck() {}, readMachine() {}, readModels() {}, readVllm() {}, openLibrary() {}, startPull() {}, stopPull() {}, dismissPull() {}, remove() {}, startRuntime() {}, ...options.local }),
      useTryLocal: () => ({ busy: false, answer: null, problem: '', ask() {}, ...options.trial }),
    },
    '../../engine/runtimes': { useLocalRuntimes: () => ({ doc: null, problem: '', checked: null, save() {}, check() {}, reload() {}, ...options.runtimes }) },
    '../../engine/hfstore': {
      NO_FILTERS: { query: '', sort: 'downloads', min: null, max: null, license: '' },
      useHfStore: () => ({ items: null, problem: '', busy: false, quants: {}, search() {}, openRepo() {} }),
    },
    '../Disclosure': { Disclosure: ({ title, children }) => h('details', null, h('summary', null, title), children) },
    '../controls': {
      ProgressBar: ({ value }) => h('span', { role: 'progressbar', 'aria-valuenow': Math.round(value * 100) }),
      Select: ({ label, value, options, onChange }) =>
        h('select', { 'aria-label': label, value, onChange: (event) => onChange(event.target.value) }, options.map((option) => h('option', { key: option.value, value: option.value }, option.label))),
    },
    '../panels/Setup': { SetupGroup: () => h('section', null, h('h3', null, 'Browser extension and set-up')), SharedAccessGroup: () => h('section', null, h('h3', null, 'Access code')) },
    '../panels/McpClients': { McpClientsGroup: () => h('section', null, h('h3', null, 'Chat clients')) },
    '../panels/Proxies': { ProxiesGroup: () => h('section', null, h('h3', null, 'Proxies')) },
    '../panels/SearchProviders': { SearchProvidersGroup: () => h('section', null, h('h3', null, 'Web search')) },
  }
}

/** An icon-only control has to carry its name: a button with no text and no
 *  aria-label is a control a screen reader cannot say. */
export function unnamedButtons(document) {
  return [...document.querySelectorAll('button, [role="radio"], [role="checkbox"], [role="switch"]')]
    .filter((node) => !node.textContent.trim() && !node.getAttribute('aria-label'))
    .map((node) => node.outerHTML.slice(0, 90))
}

/** The markup of a component as a reader's browser would hold it. */
export function domOf(html) {
  return new JSDOM(html).window.document
}

/** Mount a component in a jsdom window for interaction tests. The globals React
 *  and the settings code read are set for the life of the mount, then restored. */
export async function mount(element) {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { pretendToBeVisual: true })
  const names = ['window', 'document', 'HTMLElement', 'HTMLInputElement', 'HTMLSelectElement', 'HTMLTextAreaElement', 'Node', 'Element', 'MutationObserver', 'Event', 'CustomEvent', 'MouseEvent', 'KeyboardEvent', 'getComputedStyle']
  const saved = Object.fromEntries(names.map((name) => [name, globalThis[name]]))
  for (const name of names) globalThis[name] = dom.window[name]
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  // react-dom decides once, when it loads, whether a DOM exists; the globals come first.
  const { createRoot } = await import('react-dom/client')
  const { act } = React
  const container = dom.window.document.getElementById('root')
  const root = createRoot(container)
  await act(async () => root.render(element))
  return {
    document: dom.window.document,
    container,
    /** Click the element found by `select`, inside act. */
    click: async (node) => {
      await act(async () => node.click())
    },
    /** Type into an input the way a reader does: the value, then its input event. */
    type: async (node, text) => {
      const proto = node.tagName === 'TEXTAREA' ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
      await act(async () => {
        setter.call(node, text)
        node.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
        // A mutation observer reads the page after a turn of the event loop.
        await new Promise((resolveTurn) => setTimeout(resolveTurn, 10))
      })
    },
    flush: () => act(async () => new Promise((resolveTurn) => setTimeout(resolveTurn, 10))),
    unmount: async () => {
      await act(async () => root.unmount())
      for (const name of names) globalThis[name] = saved[name]
      delete globalThis.IS_REACT_ACT_ENVIRONMENT
      dom.window.close()
    },
  }
}
