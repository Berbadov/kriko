"""Export: claims as a deterministic view over verdicts.

Writes the part-dict YAML schema sync.py expects (part_id / part_type /
display_name / manufacturer / claims — the shape of any file under
packs/cars/data/parts/**) to a build directory. Part headers are derived from
the served catalog itself (component_part_meta), never hand-enumerated
(no-hardcoded-car-data rule); a component with no catalog identity is
skip-and-reported, exactly like an invalid cluster.

Each exported claim carries the serving-gate fields main's resolver consumes,
grounded at export time by the EXISTING deterministic grounders (zero LLM):

  * applies_when.min_mileage_km — ground_mileage_threshold() over the claim's
    own text + cited quotes (emits only on an onset-cued km figure, biased
    low = fail-open-safe);
  * applies_when.applies_year_from/to — every plausible year token in the
    cited quotes is PROPOSED as a bound and vetted by ground_year_window()
    (exact token + direction cue in proximity guards against a false window).
    Widest grounded window wins; contradictory windows (from > to) drop both
    bounds;
  * kind/maintenance — maintenance.to_maintenance(), the same
    closed interval vocabulary the legacy catalog used (schema v2:
    interval_km / interval_years / evidence_keywords);
  * requires_equipment is deliberately NOT emitted: verdicts carry no
    equipment signal, and sync.py already derives it deterministically from
    title+rationale at sync time (the retired backend/core/equipment.py).

The purge_* scripts' invariants live here as per-cluster checks: a cluster
whose verdict copy fails validation is skipped and reported, never shipped —
but it does NOT abort the whole export (backlog B1 blocker 1: one DTC-titled
cluster used to nuke every other valid cluster's export). A second hard gate
runs the exact validator sync.py runs (validate_part) on every written file;
a file that fails is unlinked and reported, so a shape/contamination failure
surfaces at export time, not at sync. Nothing here deletes ledger data — an
unexported cluster is retained, just not servable, and the skip report says
exactly which clusters were held back and why."""

import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import yaml
from packs.cars.pipeline.paths import REPO_ROOT

from packs.cars.pipeline.claims.maintenance import to_maintenance
from packs.cars.pipeline.util.domains import normalize_domain
from packs.cars.pipeline.claims.ground_mileage_threshold import ground_mileage_threshold
from packs.cars.pipeline.claims.ground_year_window import ground_year_window
from packs.cars.pipeline.ledger.verdict import cluster_payload, gate_product_value, input_hash
from packs.cars.pipeline.parts.validate_part_yaml import validate_part
from packs.cars.pipeline.stoplists import (
    is_likely_non_english, title_has_dtc_code, title_is_verbose,
)

_SEVERITIES = {"high", "medium", "low"}
_KINDS = {"known_issue", "maintenance", "recall"}

_CATALOG_PARTS_DIR = REPO_ROOT / "packs" / "cars" / "data" / "parts"
# Part ids follow the power-split convention (k9k_110, ea888_220) — the
# trailing "_<hp>" is bookkeeping, not part of the engineering identity the
# ledger clusters by (same reading as ledger/resolve.py's component_registry).
_POWER_SUFFIX_RE = re.compile(r"_\d+$")
_HP_DISPLAY_RE = re.compile(r"\s*\d+\s*hp$", re.IGNORECASE)
# Plausible model-year window for a candidate window bound — same engineering-
# constant role as MIN_KM/MAX_KM in ground_mileage_threshold.
_MIN_MODEL_YEAR, _MAX_MODEL_YEAR = 1990, 2030
_YEAR_TOKEN_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def merged_part_id(part_id: str) -> str:
    """Power-collapsed identity: k9k_110 -> k9k.

    The trailing "_<hp>" is bookkeeping, not engineering identity (same reading
    as component_part_meta and ledger/resolve.py). Public so a fitment remap
    can derive the legacy -> merged mapping without a hand-enumerated list —
    the scalability rule.
    """
    return _POWER_SUFFIX_RE.sub("", part_id)


class ExportError(RuntimeError):
    """Reserved for catastrophic export failure (e.g. unwritable output dir).

    Per-cluster validation problems are NOT this — they skip the offending
    cluster and appear in the skip report (see export_all)."""


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
    return s[:24]


def independent_source_count(conn, cluster_id: int) -> int:
    rows = conn.execute(
        "SELECT DISTINCT d.url, d.site_or_channel FROM cluster_members m"
        " JOIN evidence e ON e.id = m.evidence_id"
        " JOIN documents d ON d.id = e.doc_id WHERE m.cluster_id=?",
        (cluster_id,)).fetchall()
    origins = set()
    for url, chan in rows:
        origin = urlparse(url).netloc if url.startswith("http") else (chan or url)
        origins.add(origin.lower())
    return len(origins)


def _has_structured(conn, cluster_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM cluster_members m JOIN evidence e ON e.id=m.evidence_id"
        " JOIN documents d ON d.id=e.doc_id"
        " WHERE m.cluster_id=? AND d.source_type='structured'",
        (cluster_id,)).fetchone() is not None


def disposition(verdict: dict, n_independent: int, has_structured: bool) -> str | None:
    if not verdict.get("supported") or verdict.get("product_value") != "high":
        return None
    comp = (verdict.get("attribution") or {}).get("component_id") or ""
    if comp in ("", "foreign", "none"):
        return None
    if verdict.get("severity") == "high":
        return "review"   # invariant: high severity always needs a human
    if n_independent >= 2 or has_structured:
        return "verified"
    return "review"


# ── Part-dict headers, derived from the served catalog ──────────────────────


@lru_cache(maxsize=1)
def _catalog_part_headers() -> dict[str, dict]:
    """part_id -> part-dict header fields (everything but claims), read off
    the served catalog. Same derive-from-catalog pattern as
    stoplists.catalog_code_manufacturers(): a new part is covered the moment
    its stub exists, with no separate registration step to forget."""
    headers: dict[str, dict] = {}
    for path in _CATALOG_PARTS_DIR.glob("**/*.yaml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        part_id = data.get("part_id")
        if not part_id:
            continue
        headers[str(part_id)] = {
            k: data[k]
            for k in ("part_type", "display_name", "manufacturer", "code_family",
                      "code_family_extra", "known_also_as", "production_years")
            if data.get(k) is not None
        }
    return headers


def component_part_meta(component_id: str) -> dict | None:
    """Part-dict header for an exported component id, derived from the catalog.

    1. exact part_id match (dc4, golf7_body): copy the catalog header verbatim.
    2. power-collapsed match (k9k <- k9k_110/k9k_100/...): manufacturer,
       code_family and production_years are kept only where every matched
       variant agrees; display_name = shortest (least tune-specific) with any
       trailing power figure stripped; code_family_extra and known_also_as are
       unioned instead — a sibling alias or code family that only one variant
       declares still needs to be visible, not silently dropped because
       another variant's stub omits it.
    None when the component has no catalog identity at all, or an ambiguous
    part_type — the caller skip-and-reports, since a part-dict without a real
    header would only fail sync's validation gate later.
    """
    headers = _catalog_part_headers()
    exact = headers.get(component_id)
    if exact is not None:
        return {"part_id": component_id, **exact}
    matches = [h for pid, h in sorted(headers.items())
               if _POWER_SUFFIX_RE.sub("", pid) == component_id]
    if not matches:
        return None
    part_types = {m.get("part_type") for m in matches}
    if len(part_types) != 1 or not next(iter(part_types)):
        return None  # ambiguous identity — never guess
    meta: dict = {"part_id": component_id, "part_type": next(iter(part_types))}
    names = [m["display_name"] for m in matches if m.get("display_name")]
    if names:
        # "Renault H5F (1.2 TCe) 130hp" reads wrong on a tune-merged file.
        meta["display_name"] = _HP_DISPLAY_RE.sub(
            "", min(names, key=lambda s: (len(s), s))).strip()
    for field in ("manufacturer", "code_family"):
        vals = {m[field] for m in matches if m.get(field) is not None}
        if len(vals) == 1:
            meta[field] = next(iter(vals))
    # code_family_extra carries sibling aliases (e.g. R9M's M9R) the sibling
    # guard reads off the catalog — the power merge must preserve the union,
    # or the guard silently loses a sibling family (regression the swap caught
    # live on r9m/M9R).
    extra = sorted({x for m in matches for x in (m.get("code_family_extra") or [])})
    if extra:
        meta["code_family_extra"] = extra
    aliases = sorted({a for m in matches for a in (m.get("known_also_as") or [])})
    if aliases:
        meta["known_also_as"] = aliases
    vals = {m["production_years"] for m in matches if m.get("production_years")}
    if len(vals) == 1:
        meta["production_years"] = next(iter(vals))
    return meta


# ── Serving-gate grounding (deterministic, zero LLM) ────────────────────────


def _ground_applies_when(claim_text: str, source_text: str) -> dict:
    """applies_when gate fields for one exported claim.

    min_mileage_km: ground_mileage_threshold() over claim text + cited quotes
    — emitted only when a km figure sits near an onset cue; the grounder
    biases low, and a lower gate hides the claim from FEWER cars
    (fail-open-safe).

    applies_year_from/to: every plausible year token in the cited quotes is
    proposed as a bound and vetted by ground_year_window() (exact token +
    direction-appropriate cue in proximity guards against a false window).
    Widest grounded window wins (min from / max to — narrowing only ever
    hides cars, so wide is the safe direction); contradictory windows
    (from > to) drop both bounds.
    """
    aw: dict = {}
    km = ground_mileage_threshold(f"{claim_text} {source_text}".strip())
    if km is not None:
        aw["min_mileage_km"] = km

    years = {int(y) for y in _YEAR_TOKEN_RE.findall(source_text or "")
             if _MIN_MODEL_YEAR <= int(y) <= _MAX_MODEL_YEAR}
    froms, tos = set(), set()
    for year in years:
        g = ground_year_window(year, year, source_text)
        if g.year_from is not None:
            froms.add(year)
        if g.year_to is not None:
            tos.add(year)
    year_from = min(froms) if froms else None
    year_to = max(tos) if tos else None
    if year_from is not None and year_to is not None and year_from > year_to:
        year_from = year_to = None  # contradictory evidence — fail open
    if year_from is not None:
        aw["applies_year_from"] = year_from
    if year_to is not None:
        aw["applies_year_to"] = year_to
    return aw


def _validate(claim: dict, errors: list[str], cluster_id: int) -> None:
    title = claim.get("title", "")
    if title_has_dtc_code(title):
        errors.append(f"cluster {cluster_id}: DTC code in title {title!r}")
    if title_is_verbose(title):
        errors.append(f"cluster {cluster_id}: title too long")
    if is_likely_non_english(title):
        errors.append(f"cluster {cluster_id}: non-English title {title!r}")
    if claim.get("severity") not in _SEVERITIES:
        errors.append(f"cluster {cluster_id}: bad severity")
    if not title:
        errors.append(f"cluster {cluster_id}: empty title")

    # Serving-gate invariants, hard-checked at export time — mirrors what
    # validate_part_yaml enforces at the sync gate, so a malformed gate is
    # held back HERE instead of failing the whole catalog sync later.
    if claim.get("kind") not in _KINDS:
        errors.append(f"cluster {cluster_id}: bad kind {claim.get('kind')!r}")
    aw = claim.get("applies_when")
    if aw is not None:
        if not isinstance(aw, dict):
            errors.append(f"cluster {cluster_id}: applies_when is not a mapping")
        else:
            for name, val in aw.items():
                if isinstance(val, bool) or not isinstance(val, int):
                    errors.append(
                        f"cluster {cluster_id}: applies_when.{name} must be an"
                        f" integer, got {val!r}")
            yf, yt = aw.get("applies_year_from"), aw.get("applies_year_to")
            if (isinstance(yf, int) and not isinstance(yf, bool)
                    and isinstance(yt, int) and not isinstance(yt, bool)
                    and yf > yt):
                errors.append(
                    f"cluster {cluster_id}: applies_year_from ({yf}) >"
                    f" applies_year_to ({yt})")
    if claim.get("kind") == "maintenance":
        m = claim.get("maintenance")
        if (not isinstance(m, dict)
                or not (m.get("interval_km") or m.get("interval_years"))
                or not m.get("evidence_keywords")):
            errors.append(
                f"cluster {cluster_id}: maintenance claim without a grounded"
                " interval block")


def _dedup_claim_keys(claims: list[dict], skipped: list[str]) -> list[dict]:
    """One claim per claim_key within a component file.

    slug() truncates titles to 24 chars, so genuinely distinct clusters can
    collide on claim_key ("Excessive Oil Consumption …1.8 TSI" vs "…2.0 TSI")
    — invisible in the old bare-list export, fatal at sync's validator. Keep
    one deterministic survivor (content-keyed: cluster ids are reassigned on
    every rebuild, so they must not decide identity), hold back the rest as a
    clustering-quality signal — near-identical clusters cluster.py didn't
    merge. Holding back ALL collidees would silently drop servable coverage.
    """
    ordered = sorted(
        claims,
        key=lambda c: (c["claim_key"], c["title"],
                       (c["sources"][0]["source_url"] if c["sources"] else ""),
                       c["cluster_id"]),
    )
    kept: list[dict] = []
    for c in ordered:
        if kept and kept[-1]["claim_key"] == c["claim_key"]:
            skipped.append(
                f"cluster {c['cluster_id']}: duplicate claim_key"
                f" {c['claim_key']!r} — held back (near-identical clusters"
                " clustering didn't merge)")
            continue
        kept.append(c)
    return kept


def export_all(conn, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_component: dict[str, list[dict]] = {}
    skipped: list[str] = []

    # Verdicts are content-addressed by input_hash (not cluster_id), so recover
    # each cluster's verdict by recomputing its hash — the same value run_verdicts
    # cached it under. Clusters with no verdict yet are simply skipped.
    rows = conn.execute(
        "SELECT id, component_id, domain FROM clusters ORDER BY id").fetchall()
    import json as _json
    for row in rows:
        payload = cluster_payload(conn, row["id"])
        vr = conn.execute(
            "SELECT verdict_json FROM verdicts WHERE input_hash=?",
            (input_hash(payload),)).fetchone()
        if vr is None:
            continue
        v = _json.loads(vr["verdict_json"])
        # Deterministic product-value gate: the model over-rates DTC-litany
        # evidence as high value (see gold eval). Downgrade before disposition.
        v["product_value"] = gate_product_value(
            [e["title"] for e in payload["evidence"]], v)
        att_comp = (v.get("attribution") or {}).get("component_id") or ""
        # Compare case-insensitively: the model routinely echoes engine codes
        # upper-cased ("K9K") while catalog component_ids are lower-case ("k9k").
        # Genuine cross-code contamination (dq200 vs dq381) still differs after
        # folding case — only same-code case mismatches stop being false drops.
        if (att_comp not in ("", "foreign", "none")
                and att_comp.lower() != row["component_id"].lower()):
            print(f"  contamination catch: cluster {row['id']} filed under"
                  f" {row['component_id']} but verdict says {att_comp} — not exported")
            continue
        n_ind = independent_source_count(conn, row["id"])
        status = disposition(v, n_ind, _has_structured(conn, row["id"]))
        if status is None:
            continue

        sources = [
            {"source_url": s["url"],
             "source_domain": (urlparse(s["url"]).netloc.removeprefix("www.")
                               if s["url"].startswith("http")
                               else (s["site_or_channel"] or "")),
             "site_or_channel": s["site_or_channel"],
             # When we last actually saw the page. Feeds sources.retrieved_at
             # and, through it, the staleness signal in kriko.lookup.tree.
             "retrieved_at": s["fetched_at"] or "",
             "quote": s["quote"], "independent": True}
            for s in conn.execute(
                "SELECT DISTINCT d.url, d.site_or_channel, d.fetched_at, e.quote"
                " FROM cluster_members m JOIN evidence e ON e.id=m.evidence_id"
                " JOIN documents d ON d.id=e.doc_id WHERE m.cluster_id=?"
                " ORDER BY d.url", (row["id"],))
        ]
        domain = normalize_domain(row["domain"])
        key = f"{row['component_id']}_{domain}_{slug(v['title_en'])}".replace(" ", "_")
        claim = {
            "id": f"{key}_v1", "claim_key": key, "version": 1, "is_current": True,
            "title": v["title_en"], "title_tr": v["title_tr"],
            "kind": "known_issue",   # may become "maintenance" below
            "domain": domain, "severity": v["severity"],
            "confidence": 0.8 if status == "verified" else 0.6,
            "rationale": v["rationale_en"], "rationale_tr": v["rationale_tr"],
            "inspection_advice": v["inspection_advice_en"],
            "inspection_advice_tr": v["inspection_advice_tr"],
            "status": status, "promoted_by": "ledger",
            "sources": sources,
        }

        # Serving gates, grounded deterministically from the claim's own text
        # and the cluster's cited quotes (see module docstring) — zero LLM.
        quotes = " ".join(e.get("quote") or "" for e in payload["evidence"])
        aw = _ground_applies_when(
            f"{claim['title']} {claim['rationale']} {claim['inspection_advice']}",
            quotes)
        if aw:
            claim["applies_when"] = aw
        # Interval-shaped claims (timing belt, DSG fluid, clutch, ...) become
        # kind=maintenance with a schema-v2 maintenance block — the same
        # deterministic reclassify the legacy catalog used.
        to_maintenance(claim)

        cluster_errors: list[str] = []
        _validate(claim, cluster_errors, row["id"])
        if cluster_errors:
            skipped.extend(cluster_errors)
            continue
        claim["cluster_id"] = row["id"]  # export-internal, stripped before write
        by_component.setdefault(row["component_id"], []).append(claim)

    paths = []
    for comp, claims in sorted(by_component.items()):
        meta = component_part_meta(comp)
        if meta is None:
            skipped.append(
                f"component {comp}: no catalog part identity — {len(claims)}"
                " claim(s) held back (needs a real part stub + fitment remap)")
            continue
        claims = _dedup_claim_keys(claims, skipped)
        for c in claims:
            del c["cluster_id"]
        # B16: which legacy part files does this merged part supersede? Derived
        # from the legacy catalog by the power-collapse rule (k9k_110 ->
        # k9k) — no hand list — so the swap mechanism can remap fitment
        # mechanically. Only when non-empty; post-swap re-exports simply lack
        # the field.
        legacy_ids = sorted(
            pid for pid in _catalog_part_headers()
            if merged_part_id(pid) == comp and pid != comp)
        file_data = {**meta, "claims": sorted(claims, key=lambda c: c["claim_key"])}
        if legacy_ids:
            file_data["legacy_part_ids"] = legacy_ids
        # Per-claim hard gate: run the exact validator sync.py runs, hold back
        # only the claims it rejects (its per-claim checks are independent —
        # contamination, malformed gates), rewrite, re-check. A root-level or
        # persistent failure holds back the whole file.
        kept = sorted(claims, key=lambda c: c["claim_key"])
        for _attempt in range(2):
            path = out_dir / f"{comp}.yaml"
            path.write_text(yaml.dump(
                {**file_data, "claims": kept}, allow_unicode=True, sort_keys=False))
            errors = validate_part(path)
            if not errors:
                break
            idxs = {int(m.group(1)) for e in errors
                    if (m := re.search(r"\[(\d+)\]:", e))}
            if not idxs or _attempt == 1:
                break  # root-level failure or persistent errors — hold back file
            for i in sorted(idxs):
                skipped.append(
                    f"{comp}.yaml[{i}] {kept[i].get('claim_key')}: held back by"
                    " part-YAML validation at export")
            kept = [c for i, c in enumerate(kept) if i not in idxs]
        if errors or not kept:
            path.unlink(missing_ok=True)
            if errors:
                skipped.extend(f"{comp}.yaml held back: {e}" for e in errors)
            continue
        paths.append(path)

    if skipped:
        print(f"  export skipped {len(skipped)} invalid item(s)"
              " (retained in ledger, not servable):")
        for reason in skipped:
            print(f"    - {reason}")
    return paths
