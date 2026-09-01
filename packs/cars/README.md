# Cars (TR market) — pack #1

The car catalog Kriko began as, exported into the pack format. 26 variants
across VW Golf 7/8, Renault Clio 5 and Mégane 4; 21 parts; 699 claims with
725 pieces of evidence.

```bash
python -m packs.cars.build --out dist/cars.kpack
```

## What this pack is for

It is the migration's proof, in two directions at once. It has to show the pack
format can hold everything the old car-specific schema held — and the drill
pack, built first and deliberately, has to show the format is not merely a
rename of that schema.

`tests/test_pack_parity.py` replays 98 real listings through both engines and
compares. It runs only while `backend/` still exists.

## Where the old columns went

| Old | New |
|---|---|
| `variants.make/model/engine_code/fuel/...` | `attributes` rows, `is_identity=1` on the seven identity keys |
| `variants.year_from` / `year_to` | one `build_year` row with `valid_from`/`valid_to` bounds |
| `claims.title_tr` / `rationale_tr` / `inspection_advice_tr` | `claim_text` rows with `lang='tr'` |
| `claims.min_mileage_km`, `applies_year_*`, `requires_equipment`, `maintenance` | `claim_conditions` rows |
| `sync.py`'s five compatibility gates | `claim_conditions` rows, computed once at export |
| `claim_variants` | `relations` rows (`part_of`), note string preserved verbatim |
| `claim_sources` | `sources` + `evidence` |
| `claims.status` | `author_confidence` — see below |
| `claims.source_tier` / `source_trust` | derived at read time from the evidence |

## Three deliberate divergences

**Status became rank.** The old resolver refused to serve any high-severity
claim that was not `verified`, and 696 of 699 claims sit at `review`. With no
authority there is nobody to promote a claim, so review state became a rank
multiplier (`verified` 1.0, `review`/`held` 0.6, `draft`/`rejected` not
exported). The new engine serves strictly more, ranked lower. Closes B26.

**Year windows became soft.** A listing whose year falls outside the catalogued
production window now matches and carries an `out_of_range` flag. A year one off
is far more often a gap in our catalog than a different car. This is B9, and a
parity test asserts it still happens — if it ever returns zero, the window has
quietly gone hard again.

**Part attribution got stricter.** The old sync served DC4 gearbox faults to a
diesel Mégane out of the **h5f petrol engine's** part file — a car not fitted
with that engine at all. Claims now reach a car through fitment only, so the
same faults arrive from the DC4 part where they belong. Five titles are listed
in `KNOWN_ATTRIBUTION_FIXES`; that list should shrink to nothing when the
catalog is refiled, and it is enumerated rather than generalised so that it
cannot quietly grow.

## Compatibility gates, and when they are suppressed

The five text-signal gates from `sync.py` run once at export and become
condition rows, so a judgement that used to be frozen into an ETL link is now
data a reader can inspect.

They are suppressed for any attribute the part is fitted *across*. A gearbox
shared between petrol and diesel cars spans both fuels, so a claim about it that
names a petrol engine code is telling you which car the source discussed, not
which cars have the gearbox. The span comes from fitment, never a hand-written
exception list, so a new shared part is covered the moment its fitment rows
exist.

## Known coverage gap

Golf 8's `ea211_evo2` engine has no part file, so the one live Golf 8 variant
reaches no engine claims. Its `7_speed_dsg` gearbox has none either (backlog
B27). The exporter counts both rather than failing — a missing stub is a
coverage finding for the remediation loop, not a build error.
