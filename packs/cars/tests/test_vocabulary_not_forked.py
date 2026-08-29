"""The cars pack has one authoritative component registry."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PACK_COPY = REPO / "packs" / "cars" / "vocabulary" / "components.yaml"


def test_pipeline_uses_the_pack_component_registry():
    assert PACK_COPY.exists()
    assert not (REPO / "knowledge" / "catalog" / "components.yaml").exists()
