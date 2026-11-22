// The procurement read under Compare and the price watch figures say only what
// the data says. A figure is never converted across currencies, and a product
// with no comparable price is said to have none, not read as free.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory, figures

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.compare-figures-'))
  // figures.ts imports only a type and `count`; both are compiled alongside it, so the test runs the shipped code.
  const built = ts.transpileModule(await readFile('src/compare/figures.ts', 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const count = ts.transpileModule(await readFile('src/ui/format.ts', 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  await writeFile(join(directory, 'format.mjs'), count)
  await writeFile(join(directory, 'figures.mjs'), built.replace("'../ui/format'", "'./format.mjs'"))
  figures = await import(pathToFileURL(join(directory, 'figures.mjs')))
})

after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const line = (over = {}) => ({ estimateName: 'Kitchen', currency: 'USD', quotes: 1, bestLanded: null, risk: 'unknown', best: null, expiresInDays: null, ...over })

test('a comparable price is read in its own currency, and the cheaper product is named with the gap', () => {
  const read = figures.procurementRead([
    { name: 'Alpha', lines: [line({ bestLanded: 1200.5 })] },
    { name: 'Beta', lines: [line({ bestLanded: 1500 })] },
  ])
  assert.equal(read, 'Alpha has the lower landed cost, 1,200.5 USD per unit, which is 299.5 USD less than Beta.')
})

test('quotes in different currencies are said to be uncomparable, and no figure is converted', () => {
  const read = figures.procurementRead([
    { name: 'Alpha', lines: [line({ bestLanded: 1200, currency: 'USD' })] },
    { name: 'Beta', lines: [line({ bestLanded: 40000, currency: 'TRY' })] },
  ])
  assert.match(read, /USD and TRY/)
  assert.match(read, /cannot be compared/)
  assert.doesNotMatch(read, /lower|lowest|less than/)
})

test('a product with no comparable price is never read as free or as the cheapest', () => {
  const read = figures.procurementRead([
    { name: 'Alpha', lines: [line({ bestLanded: null })] },
    { name: 'Beta', lines: [line({ bestLanded: 900 })] },
  ])
  assert.equal(read, 'Only Beta has a comparable landed cost yet, at 900 USD per unit.')
})

test('with no estimate or no price the read says so plainly', () => {
  assert.match(figures.procurementRead([{ name: 'Alpha', lines: [] }, { name: 'Beta', lines: [] }]), /is in an estimate yet/)
  assert.match(figures.procurementRead([{ name: 'Alpha', lines: [line({ bestLanded: null })] }]), /none can be compared/)
})

test('equal landed costs are said to be the same', () => {
  const read = figures.procurementRead([
    { name: 'Alpha', lines: [line({ bestLanded: 700 })] },
    { name: 'Beta', lines: [line({ bestLanded: 700 })] },
  ])
  assert.equal(read, 'Alpha and Beta have the same landed cost, 700 USD per unit.')
})

test('an unknown amount is a dash, not a zero', () => {
  assert.equal(figures.moneyText(null, 'TRY'), '–')
  assert.equal(figures.moneyText(12, ''), '12')
})

test('an expiry is said in days, and a past one is said as past', () => {
  assert.equal(figures.expiryText(null), 'No date')
  assert.equal(figures.expiryText(0), 'Expires today')
  assert.equal(figures.expiryText(1), '1 day left')
  assert.equal(figures.expiryText(9), '9 days left')
  assert.equal(figures.expiryText(-3), 'Expired 3 days ago')
})

test('an absent delivery or warranty is not given, rather than a number', () => {
  assert.equal(figures.deliveryText(null), 'Not given')
  assert.equal(figures.deliveryText(1), '1 day')
  assert.equal(figures.warrantyText(12), '12 months')
})

test('a watch that fell is a negative move, and reaches its target at or below it', () => {
  assert.equal(figures.moveOf({ started_price: 100, last_price: 80 }), -0.2)
  assert.equal(figures.moveOf({ started_price: null, last_price: 80 }), null)
  assert.equal(figures.targetReached({ target: 80, last_price: 80 }), true)
  assert.equal(figures.targetReached({ target: 80, last_price: 81 }), false)
  assert.equal(figures.targetReached({ target: null, last_price: 1 }), false)
})

test('the first priced line wins a column, and the estimate order decides which', () => {
  const unpriced = line({ bestLanded: null })
  const priced = line({ bestLanded: 5 })
  assert.equal(figures.pricedLine([unpriced, priced]), priced)
  assert.equal(figures.pricedLine([unpriced]), null)
})
