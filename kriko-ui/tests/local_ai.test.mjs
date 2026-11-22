import test from 'node:test'
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import { domOf, h, loadSource, mount, prefsDoc, screenStubs, unnamedButtons } from './settings_support.mjs'

/**
 * Local AI. The section explains the computer, walks four steps, shows what fits,
 * and tries the model. What is pinned: a fact the machine did not report says so,
 * nothing downloads, starts or asks unless a button is pressed, a verdict follows
 * the computer, and the step buttons write the preferences the research reads.
 */

const SECTION = 'src/ui/settings/LocalAI.tsx'

/** The real model panels and section, with only the engine hooks stubbed. */
function load(options = {}) {
  const stubs = screenStubs(options)
  delete stubs['../panels/Local']
  return loadSource(SECTION, stubs)
}

const label = (document, text) => [...document.querySelectorAll('[data-setting]')].find((row) => row.querySelector('[data-setting-label]')?.textContent === text)
const value = (document, text) => label(document, text)?.querySelector('.k-row-value')?.textContent.trim()
const press = (document, text) => [...document.querySelectorAll('button')].find((node) => node.textContent === text)
const render = (options) => domOf(renderToStaticMarkup(h(load(options).LocalAI)))

const GPU = { name: 'RTX 4090', vram_total_mb: 24576, vram_used_mb: 800 }
const machine = (over = {}) => ({
  gpu: GPU,
  ram_total_mb: 32768,
  cpu: { name: 'Fast CPU', cores: 16 },
  runtimes: [
    { id: 'ollama', name: 'Ollama', installed: true, can_pull: true },
    { id: 'lmstudio', name: 'LM Studio', installed: false, can_pull: false },
  ],
  ...over,
})
const running = { runtime: 'ollama', url: 'http://127.0.0.1:11434' }
const gemma = { name: 'gemma4:e2b', size_bytes: 4587156505, params: '4.6B', quant: 'Q4_K_M' }

test('while the computer is being read, rows are drawn as loading and nothing is guessed', () => {
  const document = render({ local: { machine: null, modelsLoaded: false } })
  assert.ok(document.querySelectorAll('[role="status"][aria-label="Loading"]').length >= 2, 'skeleton rows, not a blank page')
  assert.equal(label(document, 'Graphics card'), undefined)
  assert.doesNotMatch(document.body.textContent, /Not reported/)
})

test('a failed read of the computer says so in a sentence and offers to try again', async () => {
  let again = 0
  const { LocalAI } = load({ local: { machine: null, machineProblem: 'The engine answered 500.', readMachine: () => again++ } })
  const view = await mount(h(LocalAI))
  try {
    assert.match(view.document.body.textContent, /Could not read this computer\. The engine answered 500\./)
    await view.click(press(view.document, 'Try again'))
    assert.equal(again, 1)
  } finally {
    await view.unmount()
  }
})

test('a field the machine did not report says "Not reported", never a number', () => {
  const document = render({ local: { machine: machine({ gpu: { name: null, vram_total_mb: null, vram_used_mb: null }, ram_total_mb: null, cpu: { name: null, cores: null } }), runtime: running } })
  for (const row of ['Graphics card', 'Graphics memory', 'Memory', 'Processor', 'What fits']) assert.equal(value(document, row), 'Not reported', row)
  const known = render({ local: { machine: machine(), runtime: running } })
  assert.equal(value(known, 'Graphics card'), 'RTX 4090')
  assert.equal(value(known, 'Graphics memory'), '24 GB')
  assert.equal(value(known, 'Memory'), '32 GB')
  assert.match(label(known, 'Processor').textContent, /16 cores/)
})

test('every setting says what it is in a sentence, and every button has a word', () => {
  const document = render({ local: { machine: machine(), runtime: running, models: [gemma] }, doc: { ...prefsDoc, chosen: {} } })
  for (const row of document.querySelectorAll('[data-setting]')) {
    assert.ok(row.querySelector('.k-row-note')?.textContent.trim(), `${row.querySelector('[data-setting-label]').textContent} has no sentence under it`)
  }
  assert.deepEqual(unnamedButtons(document), [])
  assert.equal(document.querySelectorAll('.k-btn[data-kind="primary"]').length <= 2, true, 'one blue press for the steps, the Get form aside')
})

test('the four steps show Done or To do from what Kriko can see', () => {
  const steps = (options) => {
    const document = render(options)
    return ['1. Runtime', '2. Model', '3. Try it', '4. Use it for research'].map((name) => label(document, name).querySelector('.k-pill').textContent)
  }
  assert.deepEqual(steps({ local: { machine: machine(), runtime: null } }), ['To do', 'To do', 'To do', 'To do'])
  assert.deepEqual(steps({ local: { machine: machine(), runtime: running, models: [gemma] }, doc: { ...prefsDoc, chosen: { local_model: 'gemma4:e2b' } } }), ['Done', 'Done', 'To do', 'To do'])
  assert.deepEqual(
    steps({ local: { machine: machine(), runtime: running, models: [gemma] }, trial: { answer: { text: 'hi', model: 'gemma4:e2b', seconds: 1, output_tokens: 5, tokens_per_second: 5, truncated: false } }, doc: { ...prefsDoc, chosen: { local_model: 'gemma4:e2b', preferred_harness: 'local' } } }),
    ['Done', 'Done', 'Done', 'Done'],
  )
  assert.match(render({ local: { machine: machine(), runtime: running, models: [gemma] } }).body.textContent, /4 of 4 done|0 of 4 done|\d of 4 done/)
})

test('with Ollama not installed, step 1 says where to get it and offers Check again', async () => {
  const { LocalAI } = load({ local: { machine: machine({ runtimes: [{ id: 'ollama', name: 'Ollama', installed: false, can_pull: true }] }), runtime: null } })
  const view = await mount(h(LocalAI))
  try {
    const row = label(view.document, '1. Runtime')
    assert.match(row.textContent, /Get Ollama/)
    assert.match(row.textContent, /Check again/)
    assert.match(row.textContent, /None found yet/)
  } finally {
    await view.unmount()
  }
})

test('Start Ollama runs only when pressed, and is the step 1 press when it is installed and closed', async () => {
  let started = 0
  const { LocalAI } = load({ local: { machine: machine(), runtime: null, startRuntime: () => started++ } })
  const view = await mount(h(LocalAI))
  try {
    assert.equal(started, 0, 'nothing starts on its own')
    const step = label(view.document, '1. Runtime')
    const button = [...step.querySelectorAll('button')].find((node) => node.textContent === 'Start Ollama')
    assert.equal(button.getAttribute('data-kind'), 'primary')
    await view.click(button)
    assert.equal(started, 1)
  } finally {
    await view.unmount()
  }
})

test('step 4 writes the research preference with the model in use, and step 2 uses the recommended one', async () => {
  const saves = []
  const base = { local: { machine: machine(), runtime: running, models: [gemma], recommended: { model: 'gemma4:e2b', installed: true } }, save: async (patch) => saves.push(patch) }
  const { LocalAI } = load({ ...base, doc: { ...prefsDoc, chosen: {} } })
  const view = await mount(h(LocalAI))
  try {
    await view.click([...label(view.document, '2. Model').querySelectorAll('button')].find((node) => node.textContent === 'Use it'))
    assert.deepEqual(saves.pop(), { local_model: 'gemma4:e2b' })
    await view.click([...label(view.document, '4. Use it for research').querySelectorAll('button')].find((node) => node.textContent === 'Use it'))
    assert.deepEqual(saves.pop(), { preferred_harness: 'local', local_model: 'gemma4:e2b' })
  } finally {
    await view.unmount()
  }
})

test('step 2 downloads the recommended model only on a press, and not while a download runs', async () => {
  const pulled = []
  const local = { machine: machine(), runtime: running, models: [], recommended: { model: 'gemma4:e2b', installed: false }, startPull: (name) => pulled.push(name) }
  const { LocalAI } = load({ local })
  const view = await mount(h(LocalAI))
  try {
    assert.deepEqual(pulled, [])
    await view.click([...label(view.document, '2. Model').querySelectorAll('button')].find((node) => node.textContent === 'Get it'))
    assert.deepEqual(pulled, ['gemma4:e2b'])
  } finally {
    await view.unmount()
  }
  const busy = render({ local: { ...local, pull: { model: 'gemma4:e2b', progress: 0.3, message: '1 GB of 3 GB', error: '' } } })
  assert.equal([...label(busy, '2. Model').querySelectorAll('button')].find((node) => node.textContent === 'Downloading…').disabled, true)
  assert.match(busy.body.textContent, /1 GB of 3 GB/)
})

test('the library shows a verdict per size, what fits first, the recommended one marked, and Get only on a press', async () => {
  const pulled = []
  const library = [
    { name: 'huge', sizes: ['70b'], about: 'Very large.' },
    { name: 'qwen2.5', sizes: ['3b', '7b'], about: 'Many languages.' },
    { name: 'gemma4', sizes: ['e2b'], about: 'Small.' },
  ]
  const local = { machine: machine({ gpu: { name: 'Card', vram_total_mb: 8192, vram_used_mb: 0 }, ram_total_mb: 16384 }), runtime: running, models: [], library, recommended: { model: 'gemma4:e2b', installed: false }, startPull: (name) => pulled.push(name) }
  const { LocalAI } = load({ local })
  const view = await mount(h(LocalAI))
  try {
    const names = [...view.document.querySelectorAll('.localai-fit strong')].map((node) => node.textContent)
    assert.equal(names[0], 'gemma4:e2b', 'the recommended model leads')
    assert.equal(names.at(-1), 'huge:70b', 'too big goes last')
    const first = view.document.querySelector('.localai-fit')
    assert.match(first.textContent, /Recommended/)
    assert.match(first.textContent, /Fit unknown/, 'an effective-size tag has no honest size, so the fit is unknown')
    const sized = view.document.querySelector('.localai-fit[data-fit="well"]')
    assert.match(sized.textContent, /Runs well/)
    assert.match(view.document.querySelector('.localai-fit[data-fit="big"]').textContent, /Too big/)
    assert.deepEqual(pulled, [])
    await view.click(view.document.querySelector('button[aria-label="Get qwen2.5:7b"]'))
    assert.deepEqual(pulled, ['qwen2.5:7b'])
  } finally {
    await view.unmount()
  }
})

test('the library is asked for only when the reader presses its button', async () => {
  let opened = 0
  const { LocalAI } = load({ local: { machine: machine(), runtime: running, library: null, openLibrary: () => opened++ } })
  const view = await mount(h(LocalAI))
  try {
    assert.equal(opened, 0)
    assert.equal(view.document.querySelector('input[aria-label="Search the library"]'), null)
    await view.click(press(view.document, 'Show models that fit'))
    assert.equal(opened, 1)
  } finally {
    await view.unmount()
  }
})

test('with the runtime closed, nothing offers a download', () => {
  const document = render({ local: { machine: machine(), runtime: null, library: [{ name: 'qwen2.5', sizes: ['7b'], about: '' }] } })
  assert.equal(document.querySelector('button[aria-label="Get qwen2.5:7b"]').disabled, true)
  assert.equal(press(document, 'Get').disabled, true)
  assert.match(document.body.textContent, /Start the runtime first/)
})

test('an installed model is listed with its size and verdict, used on a press and removed after a confirm', async () => {
  const saves = []
  const removed = []
  const { LocalAI } = load({ local: { machine: machine(), runtime: running, models: [gemma], remove: async (name) => removed.push(name) }, save: async (patch) => saves.push(patch), doc: { ...prefsDoc, chosen: {} } })
  const view = await mount(h(LocalAI))
  try {
    const row = view.document.querySelector('.keys-model')
    assert.match(row.textContent, /4\.6 GB/)
    assert.match(row.textContent, /Runs well/)
    await view.click(view.document.querySelector('button[aria-label="Use gemma4:e2b"]'))
    assert.deepEqual(saves.pop(), { local_model: 'gemma4:e2b' })
    await view.click(view.document.querySelector('button[aria-label="Remove gemma4:e2b"]'))
    assert.deepEqual(removed, [], 'nothing is removed on the first press')
    assert.match(view.document.body.textContent, /Remove\?/)
    await view.click([...view.document.querySelectorAll('button')].find((node) => node.textContent === 'Remove' && !node.getAttribute('aria-label')))
    assert.deepEqual(removed, ['gemma4:e2b'])
  } finally {
    await view.unmount()
  }
})

test('the Hugging Face block opens on a press', async () => {
  const { LocalAI } = load({ local: { machine: machine(), runtime: running } })
  const view = await mount(h(LocalAI))
  try {
    assert.equal(view.document.querySelector('input[aria-label="Search Hugging Face"]'), null, 'closed until pressed')
    await view.click(press(view.document, 'Browse Hugging Face'))
    assert.ok(view.document.querySelector('input[aria-label="Search Hugging Face"]'))
  } finally {
    await view.unmount()
  }
})

test('Try it asks only on Send, with the typed words and the model in use, and shows the speed in words', async () => {
  const asked = []
  const answer = { text: 'Hello there.', model: 'gemma4:e2b', seconds: 2, output_tokens: 24, tokens_per_second: 12, truncated: false }
  const options = { local: { machine: machine(), runtime: running, models: [gemma] }, doc: { ...prefsDoc, chosen: { local_model: 'gemma4:e2b' } }, trial: { ask: (...args) => asked.push(args) } }
  const { LocalAI } = load(options)
  const view = await mount(h(LocalAI))
  try {
    assert.deepEqual(asked, [], 'nothing is asked on its own')
    const send = press(view.document, 'Send')
    assert.equal(send.disabled, true, 'nothing to send yet')
    await view.type(view.document.querySelector('textarea[aria-label="Ask the local model something"]'), '  say hi  ')
    await view.click(press(view.document, 'Send'))
    assert.deepEqual(asked, [['say hi', 'gemma4:e2b']])
  } finally {
    await view.unmount()
  }
  const shown = render({ ...options, trial: { answer } })
  assert.match(shown.body.textContent, /Hello there\./)
  assert.match(shown.body.textContent, /12 tokens per second: fast enough for research/)
  const slow = render({ ...options, trial: { answer: { ...answer, tokens_per_second: 1.5 } } })
  assert.match(slow.body.textContent, /slow, expect long research runs/)
  const uncounted = render({ ...options, trial: { answer: { ...answer, output_tokens: null, tokens_per_second: null } } })
  assert.match(uncounted.body.textContent, /did not count tokens, so no speed is shown/)
})

test('Try it says why it cannot run, in a sentence, and is off while the runtime is closed', () => {
  const failed = render({ local: { machine: machine(), runtime: running, models: [gemma] }, trial: { problem: 'The model did not answer within 60 seconds.' } })
  assert.match(failed.querySelector('.error-note').textContent, /did not answer within 60 seconds/)
  const closed = render({ local: { machine: machine(), runtime: null } })
  assert.equal(closed.querySelector('textarea[aria-label="Ask the local model something"]').disabled, true)
  assert.equal(closed.querySelector('textarea').getAttribute('maxlength'), '2000')
})

test('Quick actions: check connection asks the address, start is off when running, and reset uses the recommended model', async () => {
  const checks = []
  const saves = []
  let rechecked = 0
  const runtimes = { doc: { runtimes: [], chosen: 'ollama', url: 'http://127.0.0.1:11434' }, check: (...args) => checks.push(args) }
  const options = { local: { machine: machine(), runtime: running, models: [gemma], recommended: { model: 'gemma4:e2b', installed: true }, recheck: () => rechecked++ }, runtimes, save: async (patch) => saves.push(patch), doc: { ...prefsDoc, chosen: {} } }
  const { LocalAI } = load(options)
  const view = await mount(h(LocalAI))
  try {
    await view.click(press(view.document, 'Check connection'))
    assert.deepEqual(checks, [['ollama', 'http://127.0.0.1:11434']])
    assert.equal(rechecked, 1)
    const start = label(view.document, 'Start Ollama')
    assert.equal(start.querySelector('button').disabled, true, 'already running')
    await view.click(press(view.document, 'Reset to recommended'))
    assert.deepEqual(saves, [{ local_model: 'gemma4:e2b' }])
    assert.ok(label(view.document, 'Device') && label(view.document, 'Context size'), 'device and context moved here')
  } finally {
    await view.unmount()
  }
})
