# Kriko — working notes for Claude

Kriko is a Chrome extension + FastAPI backend that surfaces reliability risks for used cars
on Sahibinden. See `docs/USAGE.md` (operation), `docs/INTERNALS.md` (architecture),
`docs/pipeline_postmortem.md` (knowledge-pipeline history).

## Product principle — what Kriko surfaces (READ THIS BEFORE TOUCHING CLAIM SELECTION)

Kriko's value is **the config- and mileage-specific known risks a buyer cannot cheaply get
from the standard pre-purchase inspection** — what to worry about for *this* specific car,
*before* they even book the expert. Everything we show should clear that bar.

**Surface a claim when it is:**
- **Specific to this variant/config** — engine code, gearbox type (e.g. dual-clutch/automated
  manual vs torque-converter), fuel, market. Not advice that applies to any car.
- **Predictable from the listing data** (mileage, year, transmission, fuel) *without*
  inspecting the car — a known weak point or failure pattern the odometer/age implies.
- **Maintenance-interval / "unless recently done"** — items due by a km or time interval (cam
  belt, major service, clutch/wear parts on high mileage). If the listing gives no evidence the
  work was done, **the omission itself is the signal** — flag it as "due unless the ad/seller
  proves otherwise".
- **High-consequence or expensive** — structural/known-weak-point failures and costly systems
  (emissions hardware, dual-clutch/mechatronics, turbo, timing components), not cosmetic or
  trivial.

**Do NOT surface (low value — drop or heavily downrank):**
- Generic dashboard-warning-light items ("ABS light", "ESP fault") or anything true of all cars.
- Anything the standard pre-purchase mechanic inspection already catches as routine — fluid
  levels/leaks, brake-pad wear, injector bench tests, compression. Buyers already pay an expert
  for these; repeating them is noise, not signal.

The test for any candidate claim: *"Would a buyer learn this from a normal pre-purchase
inspection anyway?"* If yes, it's low value. *"Is it specific to this car's
engine/gearbox/mileage and predictable from the ad?"* If yes, it's what we exist to show.

> Status: the extraction/gating pipeline currently keeps whatever sources mention (including
> generic warning-light items), so live output does **not** yet fully reflect this principle.
> Aligning it — mileage-gated claims, explicit maintenance-interval/"not mentioned in ad"
> claims, and an "inspection already covers this" filter — is open work. Honour this principle
> in any claim-selection change.
