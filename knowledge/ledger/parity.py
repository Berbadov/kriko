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
     verdict rewrote every word of the title;
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


def compare(existing_dirs: list[Path], export_dir: Path) -> str:
    old, new = _load(existing_dirs), _load([export_dir])
    new_flat = _flat(new)
    new_urls = [(stem, c, _source_urls(c)) for stem, c in new_flat]

    matched, moved, only_old = 0, [], []
    matched_new_ids: set[int] = set()

    for stem, oc in _flat(old):
        oc_urls = _source_urls(oc)
        hit = None
        if oc_urls:
            for i, (nstem, nc, nc_urls) in enumerate(new_urls):
                if oc_urls & nc_urls:
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
            only_old.append(f"  [{stem}] {oc['title']}")
        else:
            matched_new_ids.add(hit[0])
            if hit[1] == stem:
                matched += 1
            else:
                moved.append(f"  [{stem} -> {hit[1]}] {oc['title']}")

    only_new = [f"  [{stem}] {nc['title']}"
                for i, (stem, nc, _) in enumerate(new_urls)
                if i not in matched_new_ids]

    return "\n".join([
        f"matched: {matched}",
        f"moved to another part file ({len(moved)})"
        " — expected where sibling rerouting fixed misfiled claims:",
        *moved,
        f"only in existing YAML ({len(only_old)}) — explain each before retiring gates:",
        *only_old,
        f"only in ledger export ({len(only_new)}):",
        *only_new,
    ])


if __name__ == "__main__":
    import sys
    root = Path(__file__).parent.parent.parent
    print(compare(
        [root / "backend" / "data" / "claims", root / "backend" / "data" / "parts"],
        Path(sys.argv[1]) if len(sys.argv) > 1
        else Path(__file__).parent.parent / "ledger_export",
    ))
