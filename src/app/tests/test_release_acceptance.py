"""Release observations cannot be replaced by a passing compilation result."""

import importlib.util
from pathlib import Path


def _gate():
    path = Path(__file__).resolve().parents[3] / "tools" / "release_readiness.py"
    spec = importlib.util.spec_from_file_location("release_readiness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_skipped_journey_and_stale_source_identity_prevent_release():
    gate = _gate()
    evidence = {"version": "0.2.5", "source_fingerprint": "old", "platform": "windows-x86_64",
                "journeys": {name: {"status": "passed", "observed_at": "2026-10-19", "evidence": "Observed on the packaged Windows app."} for name in gate.JOURNEYS},
                "providers": {"test-agent": {"status": "passed", "model": "observed-model", "version": "observed-version", "report": "provider-report.json"}}}
    evidence["journeys"]["stop"]["status"] = "skipped"
    errors = gate.problems(evidence, "0.2.5", "current")
    assert any("fingerprint" in error for error in errors)
    assert any("stop" in error for error in errors)
    evidence["source_fingerprint"] = "current"
    evidence["journeys"]["stop"]["status"] = "passed"
    assert gate.problems(evidence, "0.2.5", "current") == []


def test_missing_provider_observations_and_malformed_reports_do_not_pass():
    gate = _gate()
    assert gate.problems({}, "0.2.5", "current")
    assert gate.problems([], "0.2.5", "current")
