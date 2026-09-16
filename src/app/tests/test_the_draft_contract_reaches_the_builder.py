"""An agent's adapter has to survive the trip from the draft to the store.

The defect this pins is the whole shape of "agent ops do something but the
extension cannot match them", and it was two constants disagreeing in silence.
`packdraft.WRITABLE_DIRS` accepted an adapter only as `.yaml`; the builder read
`adapters/*.json` and nothing else. So the one file that teaches the extension
how to read a site was the one file an agent could write, could see written,
and could never ship: no `pack_assets` row, no `/api/adapters` entry, no
content script, and therefore no listing page on earth from which the subject
it had just researched could be found.

Nothing failed. `write_draft_file` returned the path it had written, the build
succeeded, the pack installed, and the knowledge was real -- it simply had no
door. That is why the test below builds and installs rather than comparing the
two constants: a contract and its reader agreeing about a string proves less
than one file making it all the way through.
"""

import json

import pytest

from app import packdraft
from kriko.adapters import load_adapters
from kriko.pack import build as packbuild
from kriko.store import db, packstore

IDENTITY = {"product": ["brand", "series"]}

ADAPTER = {
    "site": "example.invalid",
    "match": ["*example.invalid/*"],
    "fields": {"brand": ".brand", "series": ".series"},
}


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "knowledge.sqlite"
    db.connect(path).close()
    return path


def _drafted(store, text, name="example.json"):
    draft = packdraft.create(
        store, pack_id="demo", name="Demo", identity=IDENTITY, version="0.1.0"
    )
    packdraft.write(store, slug=draft.slug, path=f"adapters/{name}", text=text)
    return draft


def test_an_adapter_an_agent_wrote_is_in_the_pack_it_built(store, tmp_path):
    draft = _drafted(store, json.dumps(ADAPTER))
    artifact = tmp_path / "demo.kpack"
    packbuild.build(draft.root, artifact)

    conn = db.connect(store)
    packstore.install(conn, artifact)
    assert [one["site"] for one in load_adapters(conn)] == ["example.invalid"]


def test_the_suffix_the_draft_accepts_is_the_suffix_the_builder_reads(store):
    """Stated as a property, so the next directory cannot repeat this.

    A suffix the contract permits and the builder ignores is not a smaller
    version of this bug; it is the same bug, and it hides the same way.
    """
    for directory, suffix in packdraft.WRITABLE_DIRS:
        if directory != "adapters":
            continue
        with pytest.raises(packdraft.DraftRefused):
            draft = packdraft.create(
                store,
                pack_id=f"demo-{suffix.strip('.')}",
                name="Demo",
                identity=IDENTITY,
            )
            packdraft.write(
                store,
                slug=draft.slug,
                path="adapters/example.yaml" if suffix == ".json" else "adapters/example.json",
                text="{}",
            )
