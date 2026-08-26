# Cordless drills — example pack

**This pack carries synthetic evidence and is not a knowledge source.** Every
quote in `data/claims.yaml` is invented, and every URL points at `example.invalid`,
a reserved domain that can never resolve. Do not install it expecting to learn
anything true about a drill.

## What it is for

It is the falsification test for the pack format, and it is deliberately built
*before* the cars pack. Pouring 700 real car claims into the format first would
let a car-shaped format look successful for weeks; a category that breaks the
car assumptions finds the problem in an afternoon.

Three things here break assumptions the old `variants` table hard-coded:

| Assumption in the old schema | What this pack does |
|---|---|
| Every subject has an engine, a fuel and a displacement | A drill has a motor type, a voltage and a chuck size, and no engine at all |
| Wear is measured in kilometres | Wear is measured in **charge cycles** and **running hours** |
| A product decomposes into components | `DHP484` has zero `relations` rows — the degenerate case, not a special case |

It also exercises the opposite shape: battery platforms (`LXT`, `PXC`) are
subjects that several products point at with `part_of`, so a claim about a
battery platform reaches every tool on it — the same traversal that lets a claim
about an engine code reach every car fitted with it.

## Building

```bash
python -m kriko.pack.build packs/drill --out dist/drill.kpack
python -m kriko.cli install dist/drill.kpack
```

## When this pack should be replaced

Once the researcher interface lands (Phase 5), this pack should be rebuilt from
real sources through the normal pipeline, at which point the synthetic evidence
goes away and the `example.invalid` URLs with it. Until then it stays clearly
marked, because a knowledge engine that ships invented facts without saying so is
worse than one that ships nothing.
