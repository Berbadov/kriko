"""Fill a throwaway engine's app state with the invented e-bikes of the site.

    python site/tools/seed_app_examples.py <app.sqlite>

`capture-app.mjs` runs this first, against an empty folder of its own, so the
desktop pictures show the app reading three saved checks, a queue and a
comparison the way it reads a reader's: through the engine's own tables, not a
page that pretends. The first e-bike comes from `examples.json` (the one the
extension panel pictures follow); the other two come from `app_examples.json`.
Every product and every finding is invented.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from app.web import state  # noqa: E402

#: The kind of site each invented source is, as a catalog's tiers would say it.
#: A real lookup carries `tier` on every source, and the engine grades trust from
#: it (`app/evidence.py`); a bare example address would be graded as an unknown
#: blog. The grade each finding then gets (solid, partial, thin) is the engine's.
TIER_BY_TITLE = {
    "Service manual": "manufacturer",
    "Safety notice": "manufacturer",
    "Owner forum thread": "forum_ugc",
    "Forum thread": "forum_ugc",
    "Repair thread": "forum_ugc",
    "Bike magazine long-term test": "editorial",
    "Review": "editorial",
    "Dealer notice": "specialist",
    "Used-bike buying guide": "specialist",
}


def payload(key: str, product: dict, pack: str) -> dict:
    """What the engine answers a lookup with, for one invented product."""
    return {
        "coverage": "RISKS_FOUND",
        "identity": {"model": product["title"]},
        "context": {},
        "packs": [{"pack_id": pack, "version": "1.0.0"}],
        "app_route": f"result/{key}",
        "app_routes": {"result": f"result/{key}", "compare": "compare"},
        "subjects": [{"kind": "product", "subject_id": key, "label": product["title"]}],
        "claims": [
            {"claim_id": f"{key}-{n}", "pack_id": pack, "subject_id": key, **claim,
             "sources": [{"tier": TIER_BY_TITLE.get(s["title"], "unknown"), **s}
                         for s in claim["sources"]]}
            for n, claim in enumerate(product["claims"])
        ],
    }


def main(path: str) -> None:
    examples = json.loads((HERE / "examples.json").read_text(encoding="utf-8"))
    more = json.loads((HERE / "app_examples.json").read_text(encoding="utf-8"))
    first = json.loads(json.dumps(examples["products"]["ebike"]))
    for claim, extra in zip(first["claims"], more["first_extra_sources"]):
        claim["sources"] = claim["sources"] + extra
    products = [("m", first["title"], "https://shop.example/e-bike-m-2022", first, first["pack"])]
    products += [(o["key"], o["title"], o["url"], o, o["pack"]) for o in more["others"]]

    conn = state.connect(Path(path))
    ids = []
    for key, title, url, product, pack in products:
        body = payload(key, product, pack)
        lookup_id = state.record_lookup(
            conn, source="extension", label=title,
            request={"url": url, "title": title}, response=body)
        ids.append((lookup_id, title, url))
    # All three researched: Compare draws a column for a product still waiting,
    # and a picture of a comparison is better without a half-drawn one.
    for lookup_id, title, url in ids:
        row, _, _ = state.queue_product(conn, url, title, lookup_id)
        state.update_queued(conn, row["queue_id"], state="researching")
        state.update_queued(conn, row["queue_id"], state="done")
    # The reader's own agent is the one the app ships.
    state.put_settings(conn, {"preferred_harness": "kriko-agent"})
    state.save_compare_draft(conn, more["draft"], [lookup_id for lookup_id, _, _ in ids])
    conn.close()
    print(json.dumps({"lookups": [lookup_id for lookup_id, _, _ in ids]}))


if __name__ == "__main__":
    main(sys.argv[1])
