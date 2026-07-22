"""Export: claims as a deterministic view over verdicts.

Writes the existing claims-YAML schema (docs/INTERNALS.md §Data Formats) to a
build directory. The purge_* scripts' invariants live here as per-cluster
checks: a cluster whose verdict copy fails validation is skipped and reported,
never shipped — but it does NOT abort the whole export (backlog B1 blocker 1:
one DTC-titled cluster used to nuke every other valid cluster's export).
Nothing here deletes ledger data — an unexported cluster is retained, just
not servable, and the skip report says exactly which clusters were held back
and why."""

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from knowledge.ledger.verdict import cluster_payload, gate_product_value, input_hash
from knowledge.stoplists import (
    is_likely_non_english, title_has_dtc_code, title_is_verbose,
)

_DOMAINS = {"engine", "transmission", "electrical", "emissions", "fuel system",
            "brakes", "suspension", "cooling", "body", "general", "hvac", "gearbox"}
_SEVERITIES = {"high", "medium", "low"}


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


def _validate(verdict: dict, errors: list[str], cluster_id: int) -> None:
    title = verdict.get("title_en", "")
    if title_has_dtc_code(title):
        errors.append(f"cluster {cluster_id}: DTC code in title {title!r}")
    if title_is_verbose(title):
        errors.append(f"cluster {cluster_id}: title too long")
    if is_likely_non_english(title):
        errors.append(f"cluster {cluster_id}: non-English title {title!r}")
    if verdict.get("severity") not in _SEVERITIES:
        errors.append(f"cluster {cluster_id}: bad severity")
    if not title:
        errors.append(f"cluster {cluster_id}: empty title")


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
        cluster_errors: list[str] = []
        _validate(v, cluster_errors, row["id"])
        if cluster_errors:
            skipped.extend(cluster_errors)
            continue

        sources = [
            {"source_url": s["url"],
             "source_domain": (urlparse(s["url"]).netloc.removeprefix("www.")
                               if s["url"].startswith("http")
                               else (s["site_or_channel"] or "")),
             "site_or_channel": s["site_or_channel"],
             "quote": s["quote"], "independent": True}
            for s in conn.execute(
                "SELECT DISTINCT d.url, d.site_or_channel, e.quote"
                " FROM cluster_members m JOIN evidence e ON e.id=m.evidence_id"
                " JOIN documents d ON d.id=e.doc_id WHERE m.cluster_id=?"
                " ORDER BY d.url", (row["id"],))
        ]
        domain = row["domain"] if row["domain"] in _DOMAINS else "general"
        key = f"{row['component_id']}_{domain}_{slug(v['title_en'])}".replace(" ", "_")
        by_component.setdefault(row["component_id"], []).append({
            "id": f"{key}_v1", "claim_key": key, "version": 1, "is_current": True,
            "title": v["title_en"], "title_tr": v["title_tr"],
            "kind": "known_issue",   # matches the served per-part claim schema
            "domain": domain, "severity": v["severity"],
            "confidence": 0.8 if status == "verified" else 0.6,
            "rationale": v["rationale_en"], "rationale_tr": v["rationale_tr"],
            "inspection_advice": v["inspection_advice_en"],
            "inspection_advice_tr": v["inspection_advice_tr"],
            "status": status, "promoted_by": "ledger",
            "sources": sources,
        })

    if skipped:
        print(f"  export skipped {len(skipped)} invalid cluster(s)"
              " (retained in ledger, not servable):")
        for reason in skipped:
            print(f"    - {reason}")

    paths = []
    for comp, claims in sorted(by_component.items()):
        path = out_dir / f"{comp}.yaml"
        path.write_text(yaml.dump(sorted(claims, key=lambda c: c["claim_key"]),
                                  allow_unicode=True, sort_keys=False))
        paths.append(path)
    return paths
