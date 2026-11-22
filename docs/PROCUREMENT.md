# Procurement in the Procurement screen

The Procurement screen holds equipment lines, each with the vendor quotes gathered
for it. This note records the decisions that are not visible in the code, so a
reader can argue with them.

## Money

- **A quote owns its currency and VAT.** `currency` is TRY, EUR or USD (the
  screen offers those three; the API accepts any code it has a rate for).
  `vat_rate` is a percentage, 0–100, and `vat_included` says whether the number
  typed is the price with VAT or without it.
- **Net and gross are both shown.** A net quote is read as `gross = net ×
  (1 + rate)`; a gross quote as `net = gross ÷ (1 + rate)`. The totals row
  shows net, VAT and gross for the whole estimate. `capital` in the forecast is
  the gross amount actually paid.
- **A new quote's default VAT rate is 20%**, Turkey's standard rate, and every
  line can change it. It is a starting value, not a claim about the purchase.
  A price saved before quotes existed is read at 0%, because that row never
  said whether it was net or gross; its exported total does not grow a tax
  nobody typed.
- **Rates are TRY per one unit**, the direction the Central Bank publishes, so
  one table serves every currency pair: `A → B` is `amount × rate[A] ÷
  rate[B]`. A currency with no rate is shown as uncomparable and is not
  converted at 1.
- **Fetching is a press.** "Fetch today's rates" reads
  `https://www.tcmb.gov.tr/kurlar/today.xml` once, uses `ForexSelling`, and
  shows the bulletin date. The extension and the engine never poll it. Manual
  rates and a fetched table are the same shape; `source` says which.

## Depreciation

Each line carries a method, a useful life, a salvage value and, for the VUK
method, a rate.

| Method | Charge | Stops at |
| --- | --- | --- |
| `straight_line` | `(cost − salvage) ÷ life` each year | the end of the life |
| `declining_balance` | twice the straight-line rate on the falling book value | salvage |
| `vuk` | the reader's `vuk_rate` on the falling book value | salvage |

The VUK option exists because Turkish tax practice has an official amortisman
list. Kriko does **not** ship that table: the list at
<https://www.gib.gov.tr/mevzuat/amortisman-oranlari> is published through a
client-rendered page, and this repository has no way to verify a rate against
the official text automatically. The method therefore takes the rate the reader
read off the list. When a verifiable, versioned source exists, the table becomes
a data change (a file with its source and effective date), not a code change.

No failure rate is inferred from a claim's severity, and no repair cost is
invented. Repair prices appear only where a source quotes one.

## Quotes, risk and landed cost

- A line holds up to 20 quotes. Exactly one is selected; the first one is
  selected when none is, and only the selected quote drives the line total and
  the forecast.
- A price saved before quotes existed becomes one quote labelled "Migrated
  price", selected, in the estimate's currency and at its default VAT. The
  legacy `unit_price` column stays readable.
- **Risk** (`src/app/quoterisk.py`) is a pure function of the quote: the site
  tier from `sellers.json`, whether the seller is named, delivery days, warranty
  months and validity. A level always comes with its reasons. An unrecognised
  site is `unknown`, never green; a classified ad is red; a marketplace is
  amber until its named seller can be checked.
- **Landed cost** compares the gross unit price converted to the estimate's
  currency. Delivery *days* and warranty *months* are terms, not money, so no
  delivery charge is invented; ties break on the shorter delivery. A quote
  without a rate is listed as unranked, with that reason.
- Price history per quote is **not wired into the Procurement screen yet**. The
  existing `pricewatch` store already keeps per-URL points and would answer
  "lowest / usual / high / thin" plus "not enough history yet"; the screen does
  not offer a watch from a quote row, so no history exists for most quotes.
  Landed-cost ranking above is what ships now.

## Export

The workbook keeps its four original sheets and adds **Accounting**. CSV writes
the Estimate sheet. The accounting columns are fixed and in this order:

`Item, Catalog, Asset category, Acquisition year, Useful life (years),
Depreciation method, Cost (net), VAT, Cost (gross), Salvage, Currency, Vendor,
Seller, Quote date, Document`

New columns go at the end. There is no vendor-specific import format: one needs
a real sample file from the bookkeeper it is for, and inventing a template would
be a guess dressed as compatibility. "Asset category" and "Acquisition year" are
blank because the app does not know them; they are for the reader to fill.

## Where procurement shows

The Procurement screen is the desk, and the same figures reach the
other screens through `src/engine/procurement.ts`, so no screen computes its own.

- **Procurement** opens on figures from every estimate: gross committed per
  currency (never summed across currencies), quotes expiring within 14 days,
  lines at risk, lines without a price and lines quoted in a currency with no
  rate, then a Needs attention list.
- **Ask** shows a strip of the same counts when any is non-zero.
- **Product** shows the best landed cost, the saving against the next quote, the
  quote risk, delivery, warranty and validity for each estimate line holding the
  product, or "Not in an estimate yet" with Add to estimate.
- **Compare** adds the same rows per product and a one-sentence read that says
  so when the products are quoted in different currencies instead of converting.
- A quote in the estimate's own currency needs no rate: it converts at 1 by
  definition. Another currency with no rate stays uncomparable.
- The accounting sheet converts net, VAT and gross to the estimate currency and
  leaves a cell blank where there is no rate, rather than writing a quote's
  amount under the estimate's currency.
- A watched price has no link to a catalog product in the API, so Prices does not
  offer "Add as a quote" yet.
