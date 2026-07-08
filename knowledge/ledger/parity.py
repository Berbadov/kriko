"""Golden-export regression: diff existing claim YAMLs against the ledger
export. Every difference must be an explainable improvement (e.g. DQ200
claims leaving dq381.yaml) — reviewed by a human once, then the export
becomes the new golden set."""

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


def compare(existing_dirs: list[Path], export_dir: Path) -> str:
    old, new = _load(existing_dirs), _load([export_dir])
    matched, only_old, only_new = 0, [], []
    for stem, olds in sorted(old.items()):
        news = new.get(stem, [])
        for oc in olds:
            hit = any(nc.get("domain") == oc.get("domain")
                      and jaccard(nc["title"], oc["title"]) >= 0.4 for nc in news)
            if hit:
                matched += 1
            else:
                only_old.append(f"  [{stem}] {oc['title']}")
    for stem, news in sorted(new.items()):
        olds = old.get(stem, [])
        for nc in news:
            if not any(oc.get("domain") == nc.get("domain")
                       and jaccard(oc["title"], nc["title"]) >= 0.4 for oc in olds):
                only_new.append(f"  [{stem}] {nc['title']}")
    return "\n".join([
        f"matched: {matched}",
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
