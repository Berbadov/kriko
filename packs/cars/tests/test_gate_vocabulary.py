"""The cars gate vocabulary is pack data, not engine code."""

from pathlib import Path

import yaml

from kriko.gates import gate_reason, load_gates
from kriko.store import packstore
from kriko.store.db import connect


def _installed(tmp_path):
    from packs.cars import build

    out, _ = build.build(tmp_path / "cars.kpack")
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, out)
    return conn


def test_cars_pack_emits_and_installs_gate_rows(tmp_path):
    conn = _installed(tmp_path)
    vocab = load_gates(conn, "org.kriko.cars")
    # No mileage number here on purpose: kriko.gates.gate_reason now
    # exempts a "covered" hit whose subject carries a specificity anchor
    # (a mileage or an engine/gearbox code) — a mileage figure alone
    # doesn't make routine pad wear config-specific, but this fixture
    # must not accidentally trip that escape while testing the plain
    # "covered" path.
    assert gate_reason("Brake pad wear", vocab) == "covered"
    assert gate_reason("Injector bench test recommended", vocab) == "covered"
    assert gate_reason("ABS warning light", vocab) == "noise"
    conn.close()


def test_config_specific_ambiguous_claim_survives(tmp_path):
    conn = _installed(tmp_path)
    vocab = load_gates(conn, "org.kriko.cars")
    assert (
        gate_reason("Oil consumption in the EA211 1.4 TSI above 100,000 km", vocab)
        is None
    )
    conn.close()


def test_cars_yaml_retains_every_stoplist_group(tmp_path):
    spec = yaml.safe_load(
        Path("packs/cars/vocabulary/gates.yaml").read_text(encoding="utf-8")
    )
    assert len(spec["covered"]) == 44
    assert len(spec["generic"]) == 11
    assert len(spec["ambiguous"]) == 3
    assert len(spec["exempt"]) == 1
    assert len(spec["noise"]) == 4
    assert len(spec["specificity"]) == 3
