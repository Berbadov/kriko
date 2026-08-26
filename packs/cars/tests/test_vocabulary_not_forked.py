"""The component registry exists twice right now. This makes drift fail loudly.

Phase 6 of the pivot moved the cars catalog into the pack, and the builder now
reads `packs/cars/vocabulary/components.yaml`. But `knowledge/catalog/` — the
authoring tools that *write* that catalog (discover, write_variants, doctor,
validate_part_yaml) — still reads its own copy at
`knowledge/catalog/components.yaml`, because those modules have not moved into
the pack yet.

Two identical files that two different tools each treat as authoritative is the
oldest data bug there is: someone adds a component to one, the other keeps
validating against the old list, and a claim silently loses its subsystem and
detection level on the way into the pack.

The real fix is to finish the move (knowledge/catalog + parts + fitment ->
packs/cars/), at which point the pack's copy is the only one and this test
deletes itself. Until then the mechanism is this assertion: edit one copy
without the other and CI stops you, rather than a buyer seeing an unranked card
three weeks later.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PACK_COPY = REPO / "packs" / "cars" / "vocabulary" / "components.yaml"
KNOWLEDGE_COPY = REPO / "knowledge" / "catalog" / "components.yaml"


def test_the_two_component_registries_have_not_drifted():
    if not KNOWLEDGE_COPY.exists():
        return  # the move finished; there is only one copy left. Delete this file.

    pack = PACK_COPY.read_text(encoding="utf-8")
    knowledge = KNOWLEDGE_COPY.read_text(encoding="utf-8")
    assert pack == knowledge, (
        "packs/cars/vocabulary/components.yaml and "
        "knowledge/catalog/components.yaml have diverged.\n\n"
        "The pack builder reads the first; the catalog authoring tools and "
        "validate_part_yaml read the second. A component that exists in only "
        "one of them either fails validation or ships without a subsystem and "
        "detection level.\n\n"
        "Copy the edit across, or — better — finish the Phase 6 move of "
        "knowledge/catalog into packs/cars and delete the second copy."
    )
