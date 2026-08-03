"""Golden-export regression: diff existing claim YAMLs against the ledger
export. Every difference must be an explainable improvement (e.g. DQ200
claims leaving dq381.yaml) — reviewed by a human once, then the export
becomes the new golden set.

Matching is by STABLE IDENTITY, not title text (backlog B1 blocker 2: the
verdict stage rewrites titles, so title-Jaccard reported `matched: 0` and the
diff was unreviewable):
  1. a shared source URL between the legacy claim and the exported claim —
     legacy `source_url` values flow into the ledger as documents and back out
     into the export's `sources`, so corroborated claims match even when the
     verdict rewrote every word of the title. The URL match must ALSO agree on
     domain: one source page ("Golf 7 common problems") seeds several distinct
     failure claims, so a bare URL match false-paired e.g. a legacy EA888
     timing-chain claim with a DQ200 transmission claim extracted from the
     same page. Sibling reroutes keep the claim's domain (only the part FILE
     changes), so the domain check costs no legitimate moves.
  2. fallback: same file stem + same domain + title Jaccard >= 0.4, for
     claims that carry no source URLs.

A claim matched in a DIFFERENT file is reported as `moved` (the sibling
reroute working as designed — an explainable improvement), not as lost."""

from pathlib import Path

import yaml

from knowledge.ledger.cluster import jaccard


def _load(dirs: list[Path]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in dirs:
        for p in sorted(d.glob("**/*.yaml")):
            data = yaml.safe_load(p.read_text()) or []
            claims = data if isinstance(data, list) else data.get("claims") or []
            out.setdefault(p.stem, []).extend(
                c for c in claims if isinstance(c, dict) and c.get("title"))
    return out


def _norm_url(url: str) -> str:
    u = (url or "").strip().lower()
    for prefix in ("https://", "http://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
    if u.startswith("www."):
        u = u[4:]
    return u.rstrip("/")


def _source_urls(claim: dict) -> set[str]:
    return {_norm_url(s.get("source_url", ""))
            for s in claim.get("sources") or []
            if isinstance(s, dict) and s.get("source_url")}


def _flat(claims_by_stem: dict[str, list[dict]]) -> list[tuple[str, dict]]:
    return [(stem, c) for stem, claims in claims_by_stem.items() for c in claims]


def _match(existing_dirs: list[Path], export_dir: Path):
    """Match legacy claims against an export dir.

    Returns (matched, moved, only_old, only_new):
      matched  — count of legacy claims found in the same part file
      moved    — list of (old_stem, new_stem, old_claim)
      only_old — list of (stem, old_claim) with no export counterpart
      only_new — list of (stem, new_claim) with no legacy counterpart
    """
    old, new = _load(existing_dirs), _load([export_dir])
    new_urls = [(stem, c, _source_urls(c)) for stem, c in _flat(new)]

    matched, moved, only_old = 0, [], []
    matched_new_ids: set[int] = set()

    for stem, oc in _flat(old):
        oc_urls = _source_urls(oc)
        hit = None
        if oc_urls:
            for i, (nstem, nc, nc_urls) in enumerate(new_urls):
                if (oc_urls & nc_urls) and nc.get("domain") == oc.get("domain"):
                    hit = (i, nstem)
                    break
        if hit is None:
            # fallback: same-stem title similarity (covers URL-less claims)
            for i, (nstem, nc, _) in enumerate(new_urls):
                if (nstem == stem and nc.get("domain") == oc.get("domain")
                        and jaccard(nc["title"], oc["title"]) >= 0.4):
                    hit = (i, nstem)
                    break
        if hit is None:
            only_old.append((stem, oc))
        else:
            matched_new_ids.add(hit[0])
            if hit[1] == stem:
                matched += 1
            else:
                moved.append((stem, hit[1], oc))

    only_new = [(stem, nc) for i, (stem, nc, _) in enumerate(new_urls)
                if i not in matched_new_ids]
    return matched, moved, only_old, only_new


def compare(existing_dirs: list[Path], export_dir: Path) -> str:
    matched, moved, only_old, only_new = _match(existing_dirs, export_dir)
    return "\n".join([
        f"matched: {matched}",
        f"moved to another part file ({len(moved)})"
        " — expected where sibling rerouting fixed misfiled claims:",
        *(f"  [{o} -> {n}] {c['title']}" for o, n, c in moved),
        f"only in existing YAML ({len(only_old)}) — explain each before retiring gates:",
        *(f"  [{stem}] {c['title']}" for stem, c in only_old),
        f"only in ledger export ({len(only_new)}):",
        *(f"  [{stem}] {c['title']}" for stem, c in only_new),
    ])


def explain_only_old(conn, existing_dirs: list[Path], export_dir: Path) -> str:
    """Categorize WHY each only-in-existing claim has no export counterpart.

    Turns the acceptance review from 'explain 474 titles by hand' into a
    sign-off over a handful of categories (product-value gate did its job,
    unsupported, blocked source, never verdicted, …). Reads the ledger only;
    changes nothing."""
    import json
    from collections import Counter, defaultdict

    _, _, only_old, _ = _match(existing_dirs, export_dir)
    # Exported titles per component, to recognize claims that DID ship under a
    # verdict-rewritten title (a fuzzy evidence match must not report those as
    # export bugs when the claim is right there in the export).
    exported_titles = {stem: [c["title"] for c in claims]
                       for stem, claims in _load([export_dir]).items()}

    def _verdict_path_reason(ev_rows) -> str:
        """Shared tail: given candidate evidence rows, find a cluster+verdict
        and translate the drop into a reviewable reason."""
        last_reason = "evidence never clustered (likely flagged low-value pre-cluster)"
        for ev in ev_rows:
            cm = conn.execute(
                "SELECT cluster_id FROM cluster_members WHERE evidence_id=?",
                (ev["id"],)).fetchone()
            if not cm:
                continue
            from knowledge.ledger.verdict import cluster_payload, input_hash
            payload = cluster_payload(conn, cm["cluster_id"])
            vr = conn.execute(
                "SELECT verdict_json FROM verdicts WHERE input_hash=?",
                (input_hash(payload),)).fetchone()
            if vr is None:
                last_reason = "cluster has no verdict yet (pending)"
                continue
            v = json.loads(vr["verdict_json"])
            if not v.get("supported"):
                last_reason = "dropped: verdict says unsupported"
                continue
            pv = v.get("product_value")
            if pv != "high":
                last_reason = f"dropped: product-value gate ({pv})"
                continue
            comp = (v.get("attribution") or {}).get("component_id") or ""
            if comp in ("", "foreign", "none"):
                last_reason = f"dropped: unattributable ({comp or 'no component'})"
                continue
            # verdict is OK — did the claim actually ship under a rewritten title?
            for t in exported_titles.get(comp.lower(), []):
                if jaccard(t, v.get("title_en", "")) >= 0.3:
                    return f"exported under rewritten title [{comp}]"
            last_reason = "verdict OK but not exported (contamination catch or validation)"
        return last_reason

    def _reason(stem: str, claim: dict) -> str:
        urls = sorted(_source_urls(claim))
        if not urls:
            # ~2/3 of legacy claims carry no sources (mostly body/elec files).
            # Fall back to a title search over ALL evidence — the extractor's
            # titles are close to the legacy ones even when verdicts rewrote
            # the exported claim. Only when NOTHING similar exists is the
            # claim unverifiable: no URL, no evidence anywhere — the ledger
            # bar (>=1 grounded source) would never serve it, so this is an
            # attributable legacy-quality drop, not a reproducible loss.
            all_ev = conn.execute("SELECT id, title FROM evidence").fetchall()
            similar = [e for e in all_ev
                       if jaccard(e["title"] or "", claim["title"]) >= 0.3]
            if not similar:
                return "no source URLs in legacy claim (unverifiable provenance)"
            return _verdict_path_reason(similar)
        docs = []
        for u in urls:
            docs.extend(conn.execute(
                "SELECT id, url FROM documents WHERE lower(url) LIKE ?",
                (f"%{u}%",)).fetchall())
        if not docs:
            return "source never ingested into ledger"
        # evidence from those docs whose title resembles the legacy claim
        ev_rows = []
        for d in docs:
            ev_rows.extend(conn.execute(
                "SELECT id, title FROM evidence WHERE doc_id=?", (d["id"],)).fetchall())
        similar = [e for e in ev_rows
                   if jaccard(e["title"] or "", claim["title"]) >= 0.3]
        if not similar:
            return "no matching evidence extracted from source"
        return _verdict_path_reason(similar)

    counts: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for stem, claim in only_old:
        r = _reason(stem, claim)
        counts[r] += 1
        if len(examples[r]) < 3:
            examples[r].append(f"    [{stem}] {claim['title']}")

    lines = [f"only-in-existing breakdown ({sum(counts.values())} claims):"]
    for reason, n in counts.most_common():
        lines.append(f"  {n:4d}  {reason}")
        lines.extend(examples[reason])
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    root = Path(__file__).parent.parent.parent
    existing = [root / "backend" / "data" / "claims", root / "backend" / "data" / "parts"]
    export_dir = (Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
                  else Path(__file__).parent.parent / "ledger_export")
    print(compare(existing, export_dir))
    if "--explain" in sys.argv:
        from knowledge.ledger import db
        conn = db.connect()
        print("\n" + explain_only_old(conn, existing, export_dir))
        conn.close()
