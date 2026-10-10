"""A reproducible configuration suite, independent of real product lore.

These are explicitly fictional products. Documents are the entire world of
each case; answer keys stay out of prompts. Regenerate with
``python -m app.precisioncases`` after changing the suite and version.
"""

import json
from pathlib import Path

SET_ID = "kriko-configuration"
SET_VERSION = "2026.10.3"


def generate() -> dict:
    cases = []

    def add(key, product, text, facts, specs=(), *, dimension, absent=False):
        url = f"https://fixtures.example/{key}"
        cases.append({
            "id": key, "product": product,
            "queries": [f"{product} documented failures"],
            "mode": "controlled", "dimension": dimension,
            "documents": [{"url": url, "text": text}],
            "supported": [{"id": fact_id, "url": url, "quote": quote,
                           "terms": terms} for fact_id, quote, terms in facts],
            "expected_specs": [{"name": name, "value": value, "url": url}
                               for name, value in specs],
            "requested_specs": [name for name, _ in specs],
            "must_find": [{"claim": fact_id} for fact_id, _, _ in facts],
            "must_not_find": [], "known_absent": [],
            "expect_abstention": absent,
        })

    quote = "AX-1040R2 units can develop a fractured charging connector."
    add("pc-revision", "Fictional Northstar notebook AX-1040R2 (2021 EU)",
        "Synthetic service bulletin, not a real product. AX-1040R1 (2020) has "
        "cooling fan seizure. That report excludes AX-1040R2. " + quote +
        " AX-1040R2 memory capacity is 16 GB; AX-1040R1 is 8 GB.",
        [("connector-fracture", quote, [["connector"], ["fractur", "crack", "break"]])],
        [("memory capacity", "16 GB")], dimension="revision")

    quote = "GX-07A built from 2018 through 2020 can develop cooler seal leakage."
    add("car-code-suffix", "Fictional Meridian car 2019 EU gearbox GX-07A",
        "Synthetic fitment sheet. GX-07 (2014-2017) uses a dry clutch and has "
        "clutch shudder. GX-07A (2018-2020) uses a wet clutch; the dry-clutch "
        "shudder bulletin excludes GX-07A. " + quote,
        [("cooler-leak", quote, [["cooler"], ["leak", "seep"]])],
        [("clutch type", "wet")], dimension="code-suffix")
    cases[-1]["expected_specs"][0]["aliases"] = ["wet clutch"]

    quote = "PX-6800XT-B has reported memory solder fractures under thermal cycling."
    add("pc-long-sku", "Fictional Northstar graphics board PX-6800XT-B 12GB rev 2",
        "Synthetic technical sheet. PX-6800XT has 8 GB. PX-6800XT-B revision 2 "
        "has 12 GB. The power socket melting notice is only for PX-6800XT-C "
        "revision 1 and explicitly excludes PX-6800XT-B. " + quote,
        [("memory-solder", quote, [["memory", "solder"], ["fractur", "crack"]])],
        [("memory capacity", "12 GB")], dimension="long-sku")

    quote = "HZ-220 EU units built in 2020 can develop coolant pump leakage."
    add("car-market", "Fictional Meridian HZ-220 2020 EU engine EN-20B",
        "Synthetic market bulletin. HZ-220 NA uses EN-20A and has timing chain "
        "stretch. EU units use EN-20B with a timing belt, so that chain notice "
        "does not apply to EU. " + quote,
        [("pump-leak", quote, [["pump"], ["leak", "seep"]])],
        [("timing drive", "belt")], dimension="market")

    add("car-year-outside", "Fictional Meridian car 2021 gearbox GX-07A",
        "Synthetic service notice. GX-07A cooler seal leakage affects build "
        "years 2018 through 2020 inclusive. Units built from 2021 onward "
        "use the corrected seal and are excluded from that notice. No other "
        "fault is documented here.", [], dimension="year-exclusion", absent=True)

    add("missing-fitment", "Fictional Meridian car 2019, gearbox code unknown",
        "Synthetic fitment table. The 2019 car can have either GX-07A or "
        "GX-08B; the year does not distinguish them. GX-07A has cooler leakage. "
        "GX-08B has bearing noise. No plate, VIN, or gearbox identifier is "
        "available for the requested car. Do not assume either gearbox.",
        [], dimension="missing-identity", absent=True)

    quote = "AX-1040R2 has a charging connector fracture notice."
    add("corrected-bulletin", "Fictional Northstar notebook AX-1040R2 2021",
        "Synthetic correction dated 2021-06-02, supersedes the 2021-05-01 "
        "bulletin. The earlier bulletin incorrectly listed AX-1040R2 for "
        "fan seizure. The correction says fan seizure applies only to "
        "AX-1040R1 and withdraws the AX-1040R2 fan claim. " + quote,
        [("connector-fracture", quote, [["connector"], ["fractur", "crack", "break"]])],
        dimension="superseded-source")

    quote = "AX-1040R2 units can develop a fractured charging connector."
    distractors = "\n".join(
        f"Table row {i}: AX-{2000 + i} revision 1 has a fan seizure notice; "
        "this is a different SKU and does not apply to AX-1040R2."
        for i in range(32))
    add("long-table", "Fictional Northstar notebook AX-1040R2 2021",
        "Synthetic multi-SKU service table.\n" + distractors + "\n" + quote,
        [("connector-fracture", quote, [["connector"], ["fractur", "crack", "break"]])],
        dimension="distractor-load")

    add("no-evidence", "Fictional Northstar AX-9099Z 2026",
        "Synthetic catalogue stub. AX-9099Z has no service reports, technical "
        "specifications, part mappings, or fitment records in this corpus. "
        "No conclusion about reliability follows from that absence.", [],
        dimension="no-evidence", absent=True)
    return {"id": SET_ID, "version": SET_VERSION,
            "about": "Controlled fictional configuration cases. Documents are "
                     "authoritative only within this synthetic experiment. "
                     "This is not a benchmark of real product knowledge.",
            "cases": cases}


if __name__ == "__main__":
    Path(__file__).with_name("benchprecision.json").write_text(
        json.dumps(generate(), indent=2) + "\n", encoding="utf-8")
