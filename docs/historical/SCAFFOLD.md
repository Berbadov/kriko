> TL;DR (archived 2026-09-25): Scaffold/how-to reference for the legacy model-centric flow:
bootstrap YAMLs via `knowledge.scaffold`, variant/source field tables, single-source addition,
pipeline command reference. Superseded by `knowledge.catalog.discover` + `knowledge.auto`
(`docs/USAGE.md` §4); kept for field reference only.

# Scaffold & source-addition reference

> **HISTORICAL — describes the legacy model-centric scaffold flow.** Onboarding now goes
> through `knowledge.catalog.discover --write-variants/--write-fitment` + `knowledge.auto`
> (see `docs/USAGE.md` §4). Kept for field-reference context only.

## A — Adding a new car model (end-to-end)

```bash
# 1. Bootstrap the two required YAML files
python -m knowledge.scaffold <make> <model> <gen>
# 2. Edit variants file — replace PLACEHOLDER with real rows (§B)
#    backend/data/variants/<make>_<model>_<gen>.yaml
# 3. Run the pipeline (auto-discovers sources + extraction)
python -m knowledge.auto <make> <model> <gen> --max-sources 60
# 4. Sync to DB
docker compose -f deploy/docker-compose.yml restart api
```

(E.g. Toyota Corolla E210: `scaffold toyota corolla e210` → edit → `auto … --max-sources 60` → restart api.)

---

## B — YAML field reference: variants

`backend/data/variants/{make}_{model}_{gen}.yaml`. Required: `id` (`{model}_{engine_code}_{power_hp}[_{tx_suffix}]`, e.g. `megane4_k9k_110`, permanent), `make`, `model`, `generation` (`"IV"`/`"E210"`), `engine_code` (K9K, 2ZR-FE), `fuel` (petrol/diesel/hybrid/electric), `displacement_cc`, `power_min_hp`/`power_max_hp`, `transmission` (manual/automatic), `year_from`, `year_to` (`null` = in production), `market` (`TR`); optional `notes`. **Invariant:** IDs permanent; no two variants in `(make, model, fuel, year)` overlap on displacement + power (CI linter); add rows, never rename/delete live ones.

## C — YAML field reference: curated sources

`knowledge/sources/curated/{make}_{model}_{gen}.yaml`: `type` (page/youtube); `url` (page) / `video_id` (youtube); `site_or_channel`; `notes` (recommended); `status` (`pending` default/processed/skipped); `added_at` (recommended ISO); `processed_at` (auto). Equal weight; **≥2 independent sources** to auto-verify, one lands in `review`.

## D — Manually adding a single source

Append a `pending` entry (page: url/site_or_channel/notes/added_at; youtube: video_id/channel/notes), then:

```bash
python -m knowledge.process <make> <model> <gen>
docker compose -f deploy/docker-compose.yml restart api
```

---

## E — Pipeline commands reference

| Command | When to use |
|---|---|
| `knowledge.scaffold <make> <model> <gen>` | Bootstrap a new model (blank YAMLs) |
| `knowledge.auto <make> <model> <gen> --max-sources 60` | **Primary pipeline** — auto-discover + extract |
| `knowledge.process <make> <model> <gen>` | Manually-added pending sources only |
| `knowledge.process <make> <model> <gen> --skip-extraction` | Re-run gates + scoring on cache (zero LLM calls) |
| `knowledge.process <make> <model> <gen> --dry-run` | Preview without writing |
| `docker compose -f deploy/docker-compose.yml restart api` | Sync claims YAML → PostgreSQL |
