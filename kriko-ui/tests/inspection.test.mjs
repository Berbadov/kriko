// Before you buy used: the card on a secondhand listing is only ever as good
// as what the check already carries. These tests pin that it recognises the
// marketplaces it claims, that every cue maps to a finding or falls back to the
// finding's own words, and that a money line is never invented.

import test, { after, before } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory, used

before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-used-'))
  const code = await readFile('src/used/inspection.ts', 'utf8')
  const built = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  await writeFile(join(directory, 'inspection.mjs'), built)
  used = await import(pathToFileURL(join(directory, 'inspection.mjs')))
})

after(async () => {
  if (directory) await rm(directory, { recursive: true, force: true })
})

const risk = (title, level = 'medium', extra = {}) => ({
  title, body: '', level, disputed: false, sources: [], ...extra,
})

test('the secondhand marketplaces are recognised, and a shop is not', () => {
  const cases = [
    ['https://www.sahibinden.com/ilan/x', 'Sahibinden'],
    ['https://dolap.com/urun/1', 'Dolap'],
    ['https://www.letgo.com/tr-tr/ilan/1', 'Letgo'],
    ['https://www.facebook.com/marketplace/item/1', 'Facebook Marketplace'],
    ['https://www.facebook.com/shop/item/1', null],
    ['https://www.facebook.com/marketplace', 'Facebook Marketplace'],
    ['https://www.ebay.co.uk/itm/1', 'eBay'],
    ['https://ebay.de/itm/1', 'eBay'],
    ['https://berlin.craigslist.org/bik/1', 'Craigslist'],
    ['https://www.kleinanzeigen.de/s-anzeige/1', 'Kleinanzeigen'],
    ['https://www.subito.it/annunci/1', 'Subito'],
    ['https://www.leboncoin.fr/annonces/1', 'leboncoin'],
    ['https://www.marktplaats.nl/a/1', 'Marktplaats'],
    ['https://shop.example/p/1', null],
    ['not an address', null],
  ]
  for (const [url, name] of cases) {
    assert.equal(used.secondhandMarket(url)?.name ?? null, name, url)
  }
})

test('a new-product page draws nothing, and neither does a used page with nothing known', () => {
  assert.equal(used.beforeYouBuyUsed({ url: 'https://shop.example/p/1', name: 'Kettle', risks: [risk('Hinge cracks')] }), null)
  assert.equal(used.beforeYouBuyUsed({ url: 'https://www.ebay.co.uk/itm/1', name: 'Kettle', risks: [] }), null)
})

test('a finding becomes a concrete inspection cue, and an unmapped one keeps its own words', () => {
  const card = used.beforeYouBuyUsed({
    url: 'https://www.ebay.co.uk/itm/1',
    name: 'Kettle',
    risks: [
      risk('Hinge cracks at the mount', 'high'),
      risk('Battery drains while idle', 'medium'),
      risk('The seal perishes', 'low'),
      risk('Colour fades in sunlight', 'low'),
    ],
  })
  assert.equal(card.market.name, 'eBay')
  assert.deepEqual(card.inspect.map((one) => one.from), [
    'Hinge cracks at the mount',
    'Battery drains while idle',
    'The seal perishes',
    'Colour fades in sunlight',
  ])
  assert.match(card.inspect[0].text, /open and close the hinge/i)
  assert.match(card.inspect[1].text, /battery/i)
  assert.match(card.inspect[2].text, /seal/i)
  assert.equal(card.inspect[3].text, 'Colour fades in sunlight', 'an unmapped finding is shown in its own words')
})

test('a repeated cue is said once, and the gravest finding leads', () => {
  const card = used.beforeYouBuyUsed({
    url: 'https://www.ebay.co.uk/itm/1',
    name: 'Laptop',
    risks: [risk('Battery wears', 'low'), risk('Battery swells', 'critical')],
  })
  assert.equal(card.inspect.length, 1)
  assert.equal(card.inspect[0].from, 'Battery swells')
})

test('questions come from the identity fields and the recorded variant', () => {
  const card = used.beforeYouBuyUsed({
    url: 'https://www.sahibinden.com/ilan/1',
    name: 'Kettle',
    risks: [],
    identity: { model: 'K-900', serial_number: 'A123', year: 2021 },
    assumed: 'EU plug',
  })
  const asked = card.ask.map((one) => one.text).join(' ')
  assert.match(asked, /model number/i)
  assert.match(asked, /serial number/i)
  assert.match(asked, /first used/i)
  assert.match(asked, /EU plug/)
  for (const one of card.ask) assert.ok(one.from)
})

test('a plain listing asks for a model and serial rather than inventing one', () => {
  const card = used.beforeYouBuyUsed({ url: 'https://www.ebay.co.uk/itm/1', name: 'Kettle', risks: [risk('Hinge cracks')] })
  assert.match(card.ask.map((one) => one.text).join(' '), /serial or model number/i)
  assert.ok(!card.ask.some((one) => /K-900|AK-47/.test(one.text)))
})

test('leverage is a repair price the finding already quotes, never a made-up number', () => {
  const withPrice = used.beforeYouBuyUsed({
    url: 'https://www.ebay.co.uk/itm/1',
    name: 'Kettle',
    risks: [risk('Hinge cracks', 'high', { sources: [{
      host: 'repair.example', url: 'https://repair.example/x', quote: 'A new hinge assembly costs €80 plus labour.', stance: 'supports',
    }] })],
  })
  assert.deepEqual(withPrice.leverage.map((one) => one.text), ['A new hinge assembly costs €80 plus labour.'])
  assert.match(withPrice.leverage[0].from, /Hinge cracks/)

  const noRepair = used.beforeYouBuyUsed({
    url: 'https://www.ebay.co.uk/itm/1',
    name: 'Kettle',
    risks: [risk('Hinge cracks', 'high', { sources: [{
      host: 'shop.example', url: 'https://shop.example/x', quote: 'The kettle sold for €200 in 2021.', stance: 'supports',
    }] })],
  })
  assert.deepEqual(noRepair.leverage, [], 'a plain price is not a repair cost')
})

test('every item on the card points back at a finding or an identity field', () => {
  const card = used.beforeYouBuyUsed({
    url: 'https://www.ebay.co.uk/itm/1',
    name: 'Kettle',
    risks: [risk('Hinge cracks', 'high', { sources: [{
      host: 'repair.example', url: 'https://repair.example/x', quote: 'A replacement hinge kit is £12.', stance: 'supports',
    }] })],
    identity: { model: 'K-900' },
  })
  for (const one of [...card.inspect, ...card.ask, ...card.leverage]) {
    assert.ok(one.text.trim())
    assert.ok(one.from.trim(), `${one.text} says where it came from`)
  }
})
