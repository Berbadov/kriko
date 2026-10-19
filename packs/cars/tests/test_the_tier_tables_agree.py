"""One tier table, in two places, and nothing allowed to drift between them.

`packs/cars/trust/source_tiers.yaml` is what the *builder* reads (`build.py:55`
imports it into the exported pack's `source_tiers` rows). The copy under
`packs/cars/pipeline/catalog/` is what the pipeline's own scoring reads
(`pipeline/sources/tiers.py:19`). They are byte-identical today, and that is the
whole problem: two hand-edited files that say the same thing, with a comment in
`build.py`'s docstring naming the *pipeline* copy as the builder's input, which
is the opposite of what the code does. Editing the documented one changes
pipeline scoring and does not change the pack a reader installs.

Merging them into one file is the real fix and needs the pipeline's loader
changed with it. Until then, this test is the mechanism that stops the two from
disagreeing without anyone noticing — which is cheaper than being right and
being the only person who knows.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TIERS = [
    REPO / "packs" / "cars" / "trust" / "source_tiers.yaml",
    REPO / "packs" / "cars" / "pipeline" / "catalog" / "source_tiers.yaml",
]


@pytest.fixture
def copies():
    return [(path, path.read_bytes()) for path in TIERS]


def test_both_copies_are_there(copies):
    """A test that passes because one file vanished is not a test."""
    for path, blob in copies:
        assert blob, f"{path.relative_to(REPO)} is missing or empty"


def test_the_two_copies_are_byte_identical(copies):
    first_path, first = copies[0]
    for path, blob in copies[1:]:
        assert blob == first, (
            f"{path.relative_to(REPO)} and {first_path.relative_to(REPO)} have "
            "drifted apart. The builder reads one and the pipeline reads the "
            "other, so a change to either alone makes a pack whose exported "
            "tiers disagree with the tiers it was scored on. Edit both, or "
            "merge them."
        )


def test_each_reader_still_opens_the_copy_it_is_meant_to(copies):
    """The files agree; which one each reader opens is the other half of it.

    `build.py` reads `trust/source_tiers.yaml` (its `TRUST / "source_tiers.yaml"`,
    line 988) while its own docstring at line 15 names the *pipeline* copy. The
    pipeline reads `pipeline/catalog/source_tiers.yaml` (`tiers.py:19`). Both
    statements are pinned here, so a future edit that repoints one of them has
    to say so out loud.
    """
    builder = (REPO / "packs" / "cars" / "build.py").read_text(encoding="utf-8")
    pipeline = (REPO / "packs" / "cars" / "pipeline" / "sources" / "tiers.py").read_text(
        encoding="utf-8")
    assert 'TRUST / "source_tiers.yaml"' in builder, (
        "the builder no longer reads packs/cars/trust/source_tiers.yaml"
    )
    assert '"catalog" / "source_tiers.yaml"' in pipeline, (
        "the pipeline no longer reads packs/cars/pipeline/catalog/source_tiers.yaml"
    )
