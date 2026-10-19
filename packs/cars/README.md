# Cars (TR market) — pack #1

The car catalog Kriko began as, exported into pack format. 26 variants (Golf 7/8, Clio 5, Mégane 4); 21 parts; 699 claims, 725 evidence.

```bash
python -m packs.cars.build --out dist/cars.kpack
```

## What this pack is for

Proof the pack format holds everything the old car schema held — and the drill pack (built first, deliberately) proves it is not just that schema renamed. `tests/test_pack_parity.py` replays 98 listings through both engines; it runs only while `backend/` still exists.

## Where the old columns went

| Old | New |
|---|---|
| `variants.make/model/engine_code/fuel/...` | `attributes` rows (`is_identity=1` on the seven identity keys) |
| `variants.year_from`/`year_to` | one `build_year` row with `valid_from`/`valid_to` |
| `claims.title_tr`/`rationale_tr`/`inspection_advice_tr` | `claim_text` rows, `lang='tr'` |
| `claims.min_mileage_km`, `applies_year_*`, `requires_equipment`, `maintenance` | `claim_conditions` rows |
| `sync.py`'s five compatibility gates | `claim_conditions` rows, computed once at export |
| `claim_variants` | `relations` rows (`part_of`), note preserved verbatim |
| `claim_sources` | `sources` + `evidence` |
| `claims.status` | `author_confidence` (status → rank, below) |
| `claims.source_tier`/`source_trust` | derived at read time from evidence |

## Three deliberate divergences

| Change | Why |
|---|---|
| **Status → rank.** 696/699 claims sit at `review`, which the old resolver refused to serve at high severity. Export maps `verified` 1.0, `review`/`held` 0.6, `draft`/`rejected` dropped — strictly more served, ranked lower. Closes B26. | No authority exists to promote claims. |
| **Year windows soft.** Out-of-window years match with an `out_of_range` flag — one year off is usually a catalog gap, not a different car (B9; parity test asserts non-zero). | Hard windows silently dropped real cars. |
| **Stricter part attribution.** Claims reach cars through fitment only — the old sync served DC4 gearbox faults to a diesel Mégane from the h5f petrol part. Five titles in `KNOWN_ATTRIBUTION_FIXES`, enumerated so the list can only shrink. | Fitment, not prose, decides. |

## Gates and gaps

The five `sync.py` text-signal gates run once at export into condition rows. Suppressed for any attribute the part is fitted *across* (gearbox shared petrol/diesel: an engine code in the source names the discussed car, not the fitment) — span comes from fitment rows, never a hand-written list.

**Gap:** Golf 8's `ea211_evo2` engine and `7_speed_dsg` gearbox have no part files, so the live Golf 8 variant reaches no engine claims (B27). The exporter counts these as coverage findings, not build errors.
