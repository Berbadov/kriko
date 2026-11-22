// The questions a reader asks the seller before buying one product.
//
// The builder is pure and is compiled here from the shipped source. What it
// may say is bounded by the data: a serious known problem becomes a question,
// a missing warranty or delivery is asked for rather than guessed, an expired
// or expiring quote asks about validity, and no question carries a number the
// quote or the date did not give.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory
let questions

const MODULES = [
  ['src/engine/sellerQuestions.ts', 'sellerQuestions.mjs'],
  ['src/engine/quotes.ts', 'quotes.mjs'],
  ['src/engine/money.ts', 'money.mjs'],
]

before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-questions-'))
  for (const [source, name] of MODULES) {
    const code = await readFile(new URL(`../${source}`, import.meta.url), 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
      .replace(/from '\.\/([A-Za-z0-9]+)'/g, "from './$1.mjs'")
    await writeFile(join(directory, name), built)
  }
  questions = await import(pathToFileURL(join(directory, 'sellerQuestions.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const TODAY = new Date(2026, 10, 20) // 20 November 2026, local

/** A quote with every term stated; a test blanks the one it is about. */
const quote = (patch = {}) => ({
  quote_id: 'q1',
  vendor: 'Vendor Ltd',
  seller: '',
  url: '',
  unit_price: 100,
  currency: 'TRY',
  vat_rate: 20,
  vat_included: false,
  delivery_days: 14,
  warranty_months: 24,
  quote_date: '2026-11-01',
  valid_until: '2026-12-31',
  note: '',
  selected: true,
  ...patch,
})

const line = (label = 'Office laptop') => ({ label })

const texts = (model) => model.items.map((item) => item.text)

test('a serious claim ranks first, and its question names the claim', () => {
  const model = questions.buildSellerQuestions({
    line: line(),
    quote: quote(),
    claims: [
      { severity: 'low', domain: 'paint', title: 'Paint chips at the edges' },
      { severity: 'critical', domain: 'fuel', title: 'Fuel line can split' },
    ],
    today: TODAY,
  })
  assert.equal(model.items[0].source, 'claim')
  assert.match(model.items[0].text, /Owners report Fuel line can split\./)
  assert.match(model.items[0].text, /batch or firmware changed since\?/)
  assert.match(model.items[0].text, /What does the warranty cover for it\?/)
  assert.equal(model.items.filter((item) => item.source === 'claim').length, 2)
})

test('a claim title that already ends in a stop is not given a second one', () => {
  const model = questions.buildSellerQuestions({
    line: line(),
    quote: quote(),
    claims: [{ severity: 'high', domain: 'x', title: 'Overheats under load.' }],
    today: TODAY,
  })
  assert.match(model.items[0].text, /Owners report Overheats under load\. Has/)
  assert.doesNotMatch(model.items[0].text, /load\.\./)
})

test('no warranty stated asks for the warranty', () => {
  const model = questions.buildSellerQuestions({
    line: line(),
    quote: quote({ warranty_months: null }),
    claims: undefined,
    today: TODAY,
  })
  const asked = model.items.find((item) => /warranty comes with this price/.test(item.text))
  assert.ok(asked, 'the warranty is asked')
  assert.equal(asked.source, 'quote')
})

test('no delivery days asks for the delivery time', () => {
  const model = questions.buildSellerQuestions({ line: line(), quote: quote({ delivery_days: null }), claims: [], today: TODAY })
  assert.ok(texts(model).some((text) => /How many days will delivery take/.test(text)))
})

test('an expired quote asks whether the price is still valid, and until when', () => {
  const model = questions.buildSellerQuestions({
    line: line(),
    quote: quote({ valid_until: '2026-11-01' }),
    claims: [],
    today: TODAY,
  })
  const asked = model.items.find((item) => /expired on 2026-11-01/.test(item.text))
  assert.ok(asked)
  assert.match(asked.text, /Is the price still valid, and until when\?/)
})

test('a quote expiring within the window asks too, with the days the date gives', () => {
  const model = questions.buildSellerQuestions({
    line: line(),
    quote: quote({ valid_until: '2026-11-25' }),
    claims: [],
    today: TODAY,
  })
  assert.ok(texts(model).some((text) => /expires in 5 days\./.test(text)))
})

test('a quote valid well past the window asks nothing about validity', () => {
  const model = questions.buildSellerQuestions({ line: line(), quote: quote({ valid_until: '2027-06-30' }), claims: [], today: TODAY })
  assert.equal(texts(model).some((text) => /valid|expire/i.test(text)), false)
})

test('no validity date at all asks until when the price is valid', () => {
  const model = questions.buildSellerQuestions({ line: line(), quote: quote({ valid_until: '' }), claims: [], today: TODAY })
  assert.ok(texts(model).some((text) => /Until when is this price valid\?/.test(text)))
})

test('a quote with no VAT statement asks whether the price includes VAT', () => {
  const model = questions.buildSellerQuestions({ line: line(), quote: quote({ vat_rate: null }), claims: [], today: TODAY })
  assert.ok(texts(model).some((text) => /Does the price include VAT, and at what rate\?/.test(text)))
  const stated = questions.buildSellerQuestions({ line: line(), quote: quote({ vat_rate: 20 }), claims: [], today: TODAY })
  assert.equal(texts(stated).some((text) => /include VAT/.test(text)), false)
})

test('no claims still yields the quote questions', () => {
  const model = questions.buildSellerQuestions({
    line: line(),
    quote: quote({ warranty_months: null, delivery_days: null }),
    claims: [],
    today: TODAY,
  })
  assert.equal(model.items.length, 2)
  assert.ok(model.items.every((item) => item.source === 'quote'))
})

test('a line with no quote asks for the price and VAT, and still lists its claims', () => {
  const model = questions.buildSellerQuestions({
    line: line(),
    quote: null,
    claims: [{ severity: 'high', domain: 'x', title: 'Battery swells' }],
    today: TODAY,
  })
  assert.equal(model.items[0].source, 'claim')
  assert.ok(model.items.some((item) => item.source === 'quote' && /price for one unit/.test(item.text)))
})

test("the engine's risk reasons become questions, except the ones the quote questions already ask", () => {
  const model = questions.buildSellerQuestions({
    line: line(),
    quote: quote({
      risk: {
        level: 'red',
        reasons: ['no seller named', 'no warranty stated', 'the quote expired on 2026-11-01'],
      },
    }),
    claims: [],
    today: TODAY,
  })
  const risk = model.items.filter((item) => item.source === 'risk')
  assert.equal(risk.length, 1)
  assert.match(risk[0].text, /no seller named/)
  assert.match(risk[0].text, /settle this before we buy\?$/)
})

test('a question never carries a number the quote or the date did not give', () => {
  const model = questions.buildSellerQuestions({
    line: line('Desk'),
    quote: quote({ warranty_months: null, delivery_days: null, valid_until: '' }),
    claims: [{ severity: 'medium', domain: 'x', title: 'Hinge wears' }],
    today: TODAY,
  })
  for (const item of model.items) {
    assert.equal(/\d/.test(item.text), false, `no digit in: ${item.text}`)
  }
})

test('the greeting uses the seller, then the vendor, then nobody', () => {
  const withSeller = questions.buildSellerQuestions({ line: line(), quote: quote({ seller: 'Acme Trading' }), claims: [], today: TODAY })
  assert.match(withSeller.body, /^Hello Acme Trading,/)
  const withVendor = questions.buildSellerQuestions({ line: line(), quote: quote(), claims: [], today: TODAY })
  assert.match(withVendor.body, /^Hello Vendor Ltd,/)
  const nobody = questions.buildSellerQuestions({ line: line(), quote: quote({ vendor: '' }), claims: [], today: TODAY })
  assert.match(nobody.body, /^Hello,/)
})

test('the subject and opening name the line, and the body numbers each question', () => {
  const model = questions.buildSellerQuestions({
    line: line('Lab fridge'),
    quote: quote({ warranty_months: null }),
    claims: [],
    today: TODAY,
  })
  assert.equal(model.subject, 'Questions before buying Lab fridge')
  assert.match(model.body, /We are about to buy Lab fridge\./)
  assert.match(model.body, /\n1\. What warranty/)
  assert.match(model.body, /Thank you\.$/)
})

test('an empty label falls back to a plain phrase, not a blank', () => {
  const model = questions.buildSellerQuestions({ line: line('   '), quote: quote(), claims: [], today: TODAY })
  assert.equal(model.subject, 'Questions before buying this product')
})

test('mailtoHref keeps a short body whole, with no cut note', () => {
  const { href, cut } = questions.mailtoHref('Subject here', 'Hello,\n\n1. A question?')
  assert.equal(cut, false)
  assert.ok(href.startsWith('mailto:?subject=Subject%20here&body='))
  const body = new URL(href).searchParams.get('body')
  assert.equal(body, 'Hello,\n\n1. A question?')
})

test('mailtoHref cuts a long body to 1800 characters at a line break and says so', () => {
  const long = Array.from({ length: 400 }, (_, index) => `${index + 1}. A question about the warranty and the delivery.`).join('\n')
  const { href, cut } = questions.mailtoHref('S', long)
  assert.equal(cut, true)
  const body = new URL(href).searchParams.get('body')
  assert.ok(body.length <= questions.MAILTO_BODY_LIMIT, `body is ${body.length} characters`)
  assert.ok(body.endsWith(questions.CUT_NOTE))
  const kept = body.slice(0, body.length - questions.CUT_NOTE.length)
  assert.equal(kept.split('\n').pop().endsWith('.'), true, 'the cut falls at a whole line')
})
