import test from 'node:test'
import assert from 'node:assert/strict'
import { loadSource } from './settings_support.mjs'

/** Whether a model fits this computer, and what a speed means. Pure functions, run as the app compiles them. */
const fit = loadSource('src/engine/fit.ts')
const GB = 1024
const gb = (n) => n * 1e9

test('the facts of a machine leave out a card that reports no memory', () => {
  assert.deepEqual(fit.factsOf({ gpu: { vram_total_mb: 8192 }, ram_total_mb: 16384 }), { vramMb: 8192, ramMb: 16384 })
  assert.deepEqual(fit.factsOf({ gpu: { name: 'X', vram_total_mb: null }, ram_total_mb: null }), { vramMb: null, ramMb: null })
  assert.deepEqual(fit.factsOf({ gpu: { vram_total_mb: 0 } }), { vramMb: null, ramMb: null })
  assert.deepEqual(fit.factsOf(null), { vramMb: null, ramMb: null })
})

test('a size is read from the name, MoE counted whole, and a name without one has none', () => {
  assert.equal(fit.parametersB('qwen2.5:7b'), 7)
  // An effective-size tag understates the file, so it carries no size: the verdict is unknown, never a guess.
  assert.equal(fit.parametersB('gemma4:e2b'), null)
  assert.equal(fit.parametersB('phi4-mini:3.8b'), 3.8)
  assert.equal(fit.parametersB('mixtral:8x7b'), 56)
  assert.equal(fit.parametersB('tiny:270m'), 0.27)
  assert.equal(fit.parametersB('hf.co/Qwen/Qwen3-8B-GGUF:Q4_K_M'), 8)
  assert.equal(fit.parametersB('llama3.1'), null)
  assert.equal(fit.estimateBytes('llama3.1'), null)
  assert.equal(fit.estimateBytes('qwen2.5:7b'), 7 * fit.BYTES_PER_BILLION)
})

test('with a card, a model that fits it with 20% to spare runs well; one that fits memory only is slow', () => {
  const facts = { vramMb: 8 * GB, ramMb: 32 * GB }
  assert.equal(fit.fitOf(gb(6), facts), 'well') // 7.2 GB needed of 8.59 GB
  assert.equal(fit.fitOf(gb(7.5), facts), 'slow') // 9 GB does not fit the card, fits RAM
  assert.equal(fit.fitOf(gb(40), facts), 'big')
})

test('with no card reported, a model needs twice its size in memory to run well', () => {
  const facts = { vramMb: null, ramMb: 16 * GB }
  assert.equal(fit.fitOf(gb(4), facts), 'well') // 8 GB of 17.18
  assert.equal(fit.fitOf(gb(9), facts), 'slow') // 18 > 17.18 but 10.8 fits
  assert.equal(fit.fitOf(gb(15), facts), 'big')
})

test('a missing fact is "unknown", never a guess', () => {
  assert.equal(fit.fitOf(null, { vramMb: 8 * GB, ramMb: 16 * GB }), 'unknown')
  assert.equal(fit.fitOf(0, { vramMb: 8 * GB, ramMb: 16 * GB }), 'unknown')
  assert.equal(fit.fitOf(gb(4), { vramMb: null, ramMb: null }), 'unknown')
  // does not fit the card and memory is not reported: it may still run on the processor
  assert.equal(fit.fitOf(gb(20), { vramMb: 8 * GB, ramMb: null }), 'unknown')
  assert.equal(fit.fitOf(gb(2), { vramMb: 8 * GB, ramMb: null }), 'well')
  assert.equal(fit.FIT_WORDS.unknown, 'Fit unknown')
})

test('library rows come one per size, what fits first, the recommended model on top', () => {
  const facts = { vramMb: 8 * GB, ramMb: 16 * GB }
  const rows = fit.fitRows(
    [
      { name: 'huge', sizes: ['70b'], about: '' },
      { name: 'qwen2.5', sizes: ['3b', '7b', '14b'], about: 'Many languages.' },
      { name: 'gemma4', sizes: ['e2b', 'e4b'], about: '' },
      { name: 'plain', sizes: [], about: '' },
    ],
    facts,
    'gemma4:e2b',
  )
  assert.equal(rows[0].name, 'gemma4:e2b', 'the recommended model leads')
  const verdicts = rows.map((row) => row.fit)
  const rank = { well: 0, slow: 1, unknown: 2, big: 3 }
  assert.deepEqual(verdicts.slice(1), [...verdicts.slice(1)].sort((a, b) => rank[a] - rank[b]), 'then by verdict')
  assert.deepEqual(rows.filter((row) => row.family === 'qwen2.5').map((row) => row.size), ['7b', '3b', '14b'], 'largest first within a verdict; the one that is only slow comes after')
  assert.equal(rows.find((row) => row.name === 'huge:70b').fit, 'big')
  assert.equal(rows.find((row) => row.name === 'plain').fit, 'unknown')
  assert.equal(rows.at(-1).fit, 'big', 'what does not fit comes last')
})

test('a recommended model that is too big is not lifted above what runs well', () => {
  const rows = fit.fitRows([{ name: 'a', sizes: ['3b'], about: '' }, { name: 'b', sizes: ['70b'], about: '' }], { vramMb: 8 * GB, ramMb: 16 * GB }, 'b:70b')
  assert.equal(rows[0].name, 'a:3b')
})

test('the recommended model is matched as the engine does, by name or a quantisation of it', () => {
  assert.equal(fit.isRecommended('gemma4:e2b', 'gemma4:e2b'), true)
  assert.equal(fit.isRecommended('gemma4:e2b-it-q4_K_M', 'gemma4:e2b'), true)
  assert.equal(fit.isRecommended('gemma4:e2b2', 'gemma4:e2b'), false)
  assert.equal(fit.isRecommended('anything', ''), false)
})

test('the largest model that runs well follows the card, else half of memory', () => {
  assert.equal(fit.largestThatRunsWell({ vramMb: 8 * GB, ramMb: 32 * GB }), Math.floor((8 * GB * 1048576) / 1.2 / 0.6e9))
  assert.equal(fit.largestThatRunsWell({ vramMb: null, ramMb: 16 * GB }), Math.floor((16 * GB * 1048576) / 2 / 0.6e9))
  assert.equal(fit.largestThatRunsWell({ vramMb: null, ramMb: null }), null)
})

test('speed in words has fixed thresholds, and no count means no claim', () => {
  assert.deepEqual(fit.SPEED, { fast: 10, usable: 3 })
  assert.deepEqual(fit.speedWords(12), { tone: 'ok', text: '12 tokens per second: fast enough for research' })
  assert.equal(fit.speedWords(10).tone, 'ok')
  assert.equal(fit.speedWords(5).tone, 'warn')
  assert.deepEqual(fit.speedWords(1.5), { tone: 'risk', text: '1.5 tokens per second: slow, expect long research runs' })
  assert.equal(fit.speedWords(null), null)
  assert.equal(fit.speedWords(0), null)
})
