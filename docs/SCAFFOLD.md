# Scaffold & source-addition reference

## A — Adding a new car model (end-to-end)

```bash
# 1. Bootstrap the two required YAML files
python -m knowledge.scaffold <make> <model> <gen>

# 2. Edit the variants file — replace the PLACEHOLDER row with real variant rows
#    File: backend/data/variants/<make>_<model>_<gen>.yaml
#    See Section B for field reference.

# 3. Run the pipeline (auto-discovers sources + runs extraction)
python -m knowledge.auto <make> <model> <gen> --max-sources 60

# 4. Sync to DB
docker compose -f deploy/docker-compose.yml restart api
```

Example for Toyota Corolla E210:
```bash
python -m knowledge.scaffold toyota corolla e210
# edit backend/data/variants/toyota_corolla_e210.yaml
python -m knowledge.auto toyota corolla e210 --max-sources 60
docker compose -f deploy/docker-compose.yml restart api
```

---

## B — YAML field reference: variants

File: `backend/data/variants/{make}_{model}_{gen}.yaml`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Stable forever. Format: `{model}_{engine_code}_{power_hp}[_{tx_suffix}]` e.g. `megane4_k9k_110` |
| `make` | string | yes | Lowercase, e.g. `renault` |
| `model` | string | yes | Lowercase, e.g. `megane` |
| `generation` | string | yes | Human label, e.g. `"IV"` or `"E210"` |
| `engine_code` | string | yes | Manufacturer code, e.g. `K9K`, `H5F`, `2ZR-FE` |
| `fuel` | string | yes | `petrol` \| `diesel` \| `hybrid` \| `electric` |
| `displacement_cc` | int | yes | Engine displacement in cc, e.g. `1461` |
| `power_min_hp` | int | yes | Lower bound of the HP range for this trim level |
| `power_max_hp` | int | yes | Upper bound (same as min if single power level) |
| `transmission` | string | yes | `manual` \| `automatic` |
| `year_from` | int | yes | First model year, e.g. `2016` |
| `year_to` | int/null | yes | Last model year; `null` = still in production |
| `market` | string | yes | `TR` for Turkish market |
| `notes` | string | no | Human-readable description of this variant |

**Invariant:** Variant IDs are permanent. Within `(make, model, fuel, year)` no two variants may overlap on both displacement and power range — the CI linter enforces this. Add new rows; never rename or delete live ones.

---

## C — YAML field reference: curated sources

File: `knowledge/sources/curated/{make}_{model}_{gen}.yaml`

| Field | Type | Required | Notes |
|---|---|---|---|
| `type` | string | yes | `page` or `youtube` |
| `url` | string | if page | Full URL for `type: page` |
| `video_id` | string | if youtube | YouTube video ID for `type: youtube` |
| `site_or_channel` | string | yes | Domain (page) or channel name (YouTube) |
| `tier` | string | yes | `A`, `B`, or `C` — see tier rules below |
| `notes` | string | recommended | Article title or short description |
| `status` | string | no | `pending` (default), `processed`, or `skipped` |
| `added_at` | date | recommended | ISO date when added, e.g. `'2026-06-29'` |
| `processed_at` | date/null | auto | Set automatically on pipeline run |

**Tier assignment rules:**

| Tier | Weight | Rule |
|---|---|---|
| A | 1.0 | Specialist repair shops, technical databases. One Tier A source alone auto-verifies a claim. |
| B | 0.5 | Owner clubs, established reliability media, high-signal forums. Two Tier B sources auto-verify. |
| C | 0.34 | YouTube, general blogs, unknown domains. Three Tier C sources auto-verify; two go to held. |

Known Tier A domains: `asrgearboxrepairs.co.uk`, `eco-torque.co.uk`, `enginecode.uk`, `gaga.ba`, `fiches-auto.fr`

Known Tier B domains: `meganeownersclub.co.uk`, `honestjohn.co.uk`, `pistonheads.com`, `donanimhaber.com`, `whatcar.com`, `sikayetvar.com`

Reddit and any domain containing `forum`, `forums`, `community`, `club`, `owners` → Tier B. Everything else → Tier C.

---

## D — Manually adding a single source

Add the entry to the curated YAML with `status: pending`, then run `process.py`:

```yaml
# For a web page:
- type: page
  url: https://example.com/megane-4-problems
  site_or_channel: example.com
  tier: B
  notes: "Forum thread on common Megane 4 issues"
  status: pending
  added_at: '2026-06-29'
  processed_at: null

# For a YouTube video:
- type: youtube
  video_id: dQw4w9WgXcQ
  site_or_channel: SomeChannel
  tier: C
  notes: "Megane 4 K9K injector review"
  status: pending
  added_at: '2026-06-29'
  processed_at: null
```

```bash
python -m knowledge.process renault megane 4
docker compose -f deploy/docker-compose.yml restart api
```

---

## E — Pipeline commands reference

| Command | When to use |
|---|---|
| `python -m knowledge.scaffold <make> <model> <gen>` | Bootstrap a new car model (creates blank YAML files) |
| `python -m knowledge.auto <make> <model> <gen> --max-sources 60` | **Primary pipeline** — auto-discovers sources + runs extraction |
| `python -m knowledge.process <make> <model> <gen>` | Process manually-added pending sources only |
| `python -m knowledge.process <make> <model> <gen> --skip-extraction` | Re-run gates + scoring on cached candidates (zero LLM calls) |
| `python -m knowledge.process <make> <model> <gen> --dry-run` | Preview extraction without writing anything |
| `docker compose -f deploy/docker-compose.yml restart api` | Sync claims YAML → PostgreSQL DB |
