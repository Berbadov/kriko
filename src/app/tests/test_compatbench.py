import json

from app.compatbench import core
from app.compatbench import cli


def test_compatibility_fixtures_have_a_grounded_reference_answer():
    result = core.verify()
    assert result["cases"] == 5
    assert result["outcomes"] == {"compatible": 2, "incompatible": 2, "unknown": 1}
    assert all(row["pass"] for row in result["rows"])


def test_same_socket_does_not_override_a_bios_or_ram_mismatch():
    cases = {row["id"]: row for row in core.load()["cases"]}
    bios = cases["pc-same-socket-old-bios"]
    memory = cases["pc-same-family-ddr-variant"]
    assert core.verdict(bios) == "incompatible"
    assert [row["status"] for row in core.constraint_results(bios)] == ["match", "mismatch"]
    assert core.verdict(memory) == "incompatible"
    proposed = json.loads(core.reference_reply(bios))
    proposed["verdict"] = "compatible"
    assert not core.grade(bios, json.dumps(proposed))["pass"]


def test_missing_engine_vin_and_market_data_keeps_vehicle_fitment_unknown():
    case = next(row for row in core.load()["cases"] if row["id"] == "car-missing-engine-vin-market")
    results = {row["id"]: row["status"] for row in core.constraint_results(case)}
    assert results == {"model_year": "match", "engine_code": "unknown",
                       "market": "unknown", "vin_break": "unknown"}
    assert core.verdict(case) == "unknown"


def test_one_unverified_forum_account_cannot_prove_a_counterfeit_or_rate_the_seller():
    case = next(row for row in core.load()["cases"] if row["id"] == "car-fitment-oem-forum-uncertain")
    assert core.verdict(case) == "compatible"
    assert core.authenticity(case) == "unknown"
    assert core.seller_assessment(case) == "unverified"
    reply = json.loads(core.reference_reply(case))
    reply["authenticity"] = "counterfeit"
    scored = core.grade(case, json.dumps(reply))
    assert not scored["pass"]
    assert any("authenticity" in error for error in scored["errors"])
    reported = json.loads(core.reference_reply(case))
    reported["seller_evidence"][0]["specificity"] = "exact_item"
    scored = core.grade(case, json.dumps(reported))
    assert not scored["pass"]
    assert any("seller evidence" in error for error in scored["errors"])


def test_wrong_or_ungrounded_constraint_evidence_fails():
    case = core.load()["cases"][0]
    reply = json.loads(core.reference_reply(case))
    reply["checks"][0]["evidence"][0]["quote"] = "the socket is compatible"
    scored = core.grade(case, json.dumps(reply))
    assert not scored["pass"]
    assert any("grounded quote" in error for error in scored["errors"])


def test_prompt_contains_sources_but_not_computed_verdict_or_comparisons():
    case = core.load()["cases"][1]
    rendered = core.prompt(case)
    assert "Installed BIOS version: 1.4." in rendered
    assert "no hardcoded" not in rendered.lower()
    assert '"verdict":"compatible|incompatible|unknown"' in rendered
    assert '"expected_verdict"' not in rendered


def test_local_runner_requires_explicit_opt_in_before_opening_a_socket(tmp_path, capsys):
    called = []
    class UnexpectedSocket:
        def __init__(self, *args, **kwargs):
            called.append((args, kwargs))
            raise AssertionError("dry run must not create a model socket")

    from app.providers import local_inference

    original = local_inference.OpenAICompatSocket
    local_inference.OpenAICompatSocket = UnexpectedSocket
    try:
        status = cli.main([
            "run", "--model", "fixture-local",
            "--local-url", "http://127.0.0.1:11434/v1",
            "--out", str(tmp_path / "result.json"),
        ])
    finally:
        local_inference.OpenAICompatSocket = original
    assert status == 2
    assert called == []
    assert not (tmp_path / "result.json").exists()
    assert "No model was called" in capsys.readouterr().err


def test_grader_rejects_extra_fake_citations_duplicate_checks_and_malformed_verdicts():
    case = core.load()["cases"][0]
    baseline = json.loads(core.reference_reply(case))

    fabricated = json.loads(json.dumps(baseline))
    fabricated["checks"][0]["evidence"].append(
        {"url": "https://attacker.example/page", "quote": "socket is compatible"})
    assert not core.grade(case, json.dumps(fabricated))["pass"]

    duplicate = json.loads(json.dumps(baseline))
    duplicate["checks"].append(duplicate["checks"][0])
    assert not core.grade(case, json.dumps(duplicate))["pass"]

    for bad_verdict in ([], {}):
        malformed = json.loads(json.dumps(baseline))
        malformed["verdict"] = bad_verdict
        assert not core.grade(case, json.dumps(malformed))["pass"]
    malformed = json.loads(json.dumps(baseline))
    malformed["checks"][0]["status"] = []
    assert not core.grade(case, json.dumps(malformed))["pass"]


def test_cli_rejects_empty_case_selection_and_nonfinite_budget_before_provider_setup(capsys):
    import pytest

    with pytest.raises(ValueError, match="select at least one case"):
        cli._cases(" , ")
    status = cli.main(["run", "--model", "fixture", "--budget-usd", "nan", "--yes"])
    assert status == 2
    assert "budget must be finite" in capsys.readouterr().err
