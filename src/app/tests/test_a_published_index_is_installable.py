"""A release's pack index must be one a reader can install from.

The website's second step is Find release catalogs. For two releases it ended in
"nothing published yet", because a hand-built release carried no `packs.json`,
and once in an index whose catalogs were never attached. `verify_pack_index.py`
is the check a release runs against the address every installed app asks; these
tests run it against a real local server, so the failures are the ones a reader
met.
"""

import importlib.util
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.tests.test_pack_updates_api import write_pack
from kriko.pack import build

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "verify_pack_index.py"
PUBLISH = Path(__file__).resolve().parents[3] / "packaging" / "publish_index.py"


@pytest.fixture
def served(tmp_path):
    """A directory served over real HTTP, so urllib does its actual job."""
    published = tmp_path / "published"
    published.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(published))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield published, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _publish(tmp_path, published, base, *, attach: bool):
    artifact = build.build(write_pack(tmp_path / "src"), tmp_path / "tools.kpack")
    index = {"packs": [_load(PUBLISH).describe(artifact, base)]}
    (published / "packs.json").write_text(json.dumps(index), encoding="utf-8")
    if attach:
        (published / artifact.name).write_bytes(artifact.read_bytes())
    return f"{base}/packs.json"


def test_an_index_whose_catalogs_are_attached_has_nothing_wrong(served, tmp_path):
    published, base = served
    url = _publish(tmp_path, published, base, attach=True)
    assert _load(SCRIPT).problems(url, allow_private=True) == []


def test_an_index_naming_a_catalog_that_was_never_attached_says_which(served, tmp_path):
    # v0.3.5: packs.json was published, cars.kpack and drill.kpack were not.
    published, base = served
    url = _publish(tmp_path, published, base, attach=False)
    found = _load(SCRIPT).problems(url, allow_private=True)
    assert len(found) == 1
    assert "tools.kpack" in found[0] and "did not download" in found[0], found


def test_a_release_with_no_index_at_all_fails(served):
    # v0.3.6 and v0.3.7: the address every installed app asks answered 404.
    _, base = served
    found = _load(SCRIPT).problems(f"{base}/packs.json", allow_private=True)
    assert len(found) == 1 and "could not be read" in found[0], found
