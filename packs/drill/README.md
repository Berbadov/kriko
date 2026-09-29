# Cordless drills — example pack

**Synthetic evidence — not a knowledge source.** Every quote in `data/claims.yaml` is invented; every URL points at `example.invalid` (reserved, never resolves). Do not install it to learn about drills.

## What it is for

Falsification test for the pack format, built *before* the cars pack: pouring 700 real car claims in first would let a car-shaped format look successful for weeks; a category that breaks car assumptions finds it in an afternoon.

| Old-schema assumption | What this pack does |
|---|---|
| Every subject has engine, fuel, displacement | Motor type, voltage, chuck size — no engine |
| Wear is measured in kilometres | Wear in **charge cycles** and **running hours** |
| A product decomposes into components | `DHP484` has zero `relations` rows — degenerate, not special |
| Claims attach to products | Battery platforms (`LXT`, `PXC`) carry claims via `part_of`, reaching every tool on them — the same traversal as engine code → cars |

```bash
python -m kriko.pack.build packs/drill --out dist/drill.kpack
python -m kriko.cli install dist/drill.kpack
```

Replace with real sources via the normal pipeline once the researcher interface lands (Phase 5). Until then it stays marked: a knowledge engine shipping invented facts silently is worse than one shipping nothing.
