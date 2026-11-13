"""The NLI evidence gate: a claim must be supported by the page it quotes.

The quote check proves a sentence is on a page. This proves the claim is what
the sentence says. The case it exists for is a report that sounds sourced and
fails against its own source: the page says the part is available, the claim
says it is not, and the real sentence is quoted under it — so every check that
came before this one passes.

No model is downloaded here. A fake verifier answers by rule, and the one test
that needs the real checkpoint is skipped unless the `nli` extra is installed.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from app.nli_gate import (
    DEFAULT_ACCEPT,
    GateResult,
    NliGate,
    TransformersNliVerifier,
    Verifier,
    _label_order,
    gate_from_env,
)

REPO = Path(__file__).resolve().parents[3]

AVAILABLE = "the timing chain kit is available in every market"
UNAVAILABLE = "the timing chain kit is unobtainable in some markets"


class RuleVerifier:
    """A stand-in for a cross-encoder: the verdict is decided by the words.

    One rule per verdict, so a test says which verdict it is exercising by
    writing the claim, and nothing about the gate's own logic is re-implemented
    in the fake.
    """

    name = "rule"

    def __init__(self, score: float = 0.95) -> None:
        self.score = score
        self.seen: list[tuple[str, str]] = []

    def verify(self, premise: str, hypothesis: str) -> tuple[str, float]:
        self.seen.append((premise, hypothesis))
        premise, hypothesis = premise.casefold(), hypothesis.casefold()
        if "unobtainable" in hypothesis and "available" in premise and "unobtainable" not in premise:
            return "contradiction", self.score
        if "timing chain kit" in hypothesis and "timing chain kit" in premise:
            return "entailment", self.score
        return "neutral", self.score


def _claim(**over) -> dict:
    base = {"title": "Timing chain kit unobtainable",
            "quote": "the timing chain kit is unobtainable in some markets",
            "premise": f"Owners report that {UNAVAILABLE}. Several waited months."}
    return {**base, **over}


# ── the policy ───────────────────────────────────────────────────────────

def test_a_claim_its_source_restates_is_accepted():
    gate = NliGate(RuleVerifier())
    out = gate.check(_claim())
    assert out.decision == "accept"
    assert out.verdict == "entailment"
    assert out.score == pytest.approx(0.95)


def test_a_claim_its_source_refutes_is_dropped():
    """The case this whole module exists for: sounds sourced, fails its source."""
    gate = NliGate(RuleVerifier())
    out = gate.check(_claim(title="Timing chain kit unobtainable",
                            quote="the timing chain kit is available in every market",
                            premise=f"Dealers say {AVAILABLE}."))
    assert out.decision == "drop"
    assert out.verdict == "contradiction"


def test_a_claim_its_source_never_mentions_is_held_not_entered():
    gate = NliGate(RuleVerifier())
    out = gate.check(_claim(title="Paint peels after two winters",
                            quote="the timing chain kit is unobtainable in some markets"))
    assert out.decision == "flag"
    assert out.verdict == "neutral"
    assert "does not clearly support" in out.reason


def test_a_weak_entailment_is_held_like_a_neutral():
    """A three-way softmax gives an unrelated pair a third of the mass. The
    threshold is the difference between a gate and a coin."""
    gate = NliGate(RuleVerifier(score=0.51))
    out = gate.check(_claim())
    assert out.verdict == "entailment"
    assert out.decision == "flag"
    assert DEFAULT_ACCEPT > 0.51


def test_the_threshold_is_the_callers():
    gate = NliGate(RuleVerifier(score=0.51), accept_threshold=0.5)
    assert gate.check(_claim()).decision == "accept"


def test_a_verifier_that_raises_leaves_the_claim_unchecked():
    """Fail open: a broken check is not a reason to lose a sourced claim."""
    class Broken:
        name = "broken"

        def verify(self, premise, hypothesis):
            raise RuntimeError("CUDA is not available")

    out = NliGate(Broken()).check(_claim())
    assert out.decision == "accept"
    assert out.verdict is None
    assert out.provenance()["verdict"] == "unchecked"
    assert "CUDA" in out.reason


def test_a_claim_with_nothing_to_compare_is_held_not_accepted():
    out = NliGate(RuleVerifier()).check({"title": "", "quote": "x", "premise": "x"})
    assert out.decision == "flag"


# ── what the model is shown ──────────────────────────────────────────────

def test_the_premise_is_the_quote_widened_to_its_passage():
    """A quote is often a clause; the sentence around it is what the claim
    restates, and it is only available when the page text is in hand."""
    page = ("Preface paragraph with no bearing on the claim. " * 40
            + f"Owners report that {UNAVAILABLE}. Several have waited months. "
            + "Closing paragraph with no bearing on the claim. " * 40)
    claim = _claim(premise=page)
    premise = NliGate.premise_of(claim)
    assert UNAVAILABLE in premise
    assert len(premise) < len(page)
    assert not premise.startswith("Preface")


def test_without_the_page_the_premise_is_the_quote():
    claim = _claim()
    claim.pop("premise")
    assert NliGate.premise_of(claim) == claim["quote"]


def test_the_hypothesis_is_the_title_and_the_body():
    assert NliGate.hypothesis_of({"title": "A", "body": "B"}) == "A. B"
    assert NliGate.hypothesis_of({"title": "A", "body": "A"}) == "A"


def test_a_batch_verifier_is_used_and_a_failing_batch_falls_back():
    class Batched(RuleVerifier):
        fail = False

        def verify_many(self, pairs):
            if self.fail:
                raise RuntimeError("out of memory")
            return [self.verify(*pair) for pair in pairs]

    verifier = Batched()
    gate = NliGate(verifier)
    out = gate.check_many([_claim(), _claim(title="Paint peels")])
    assert [one.decision for one in out] == ["accept", "flag"]
    verifier.fail = True
    out = gate.check_many([_claim(), _claim(title="Paint peels")])
    assert [one.decision for one in out] == ["accept", "flag"]


# ── the label order, which a wrong guess would invert silently ───────────

def test_the_label_order_is_read_from_the_checkpoint():
    order = _label_order({0: "contradiction", 1: "entailment", 2: "neutral"})
    assert order == ("contradiction", "entailment", "neutral")
    order = _label_order({0: "ENTAILMENT", 1: "NEUTRAL", 2: "CONTRADICTION"})
    assert order == ("entailment", "neutral", "contradiction")


def test_a_checkpoint_that_is_not_three_way_nli_is_refused():
    with pytest.raises(ValueError):
        _label_order({0: "negative", 1: "positive"})


# ── off, and how it gets there ───────────────────────────────────────────

def test_with_no_model_configured_the_gate_is_off():
    assert gate_from_env({}) is None


def test_off_is_a_switch_even_with_the_extra_installed():
    assert gate_from_env({"KRIKO_NLI_MODEL": "off"}) is None


def test_importing_the_module_does_not_import_torch_or_transformers():
    """The desktop installer carries neither, and must not start to.

    Checked in a fresh interpreter: this one may already have them imported by
    another test, and a check that reads `sys.modules` here would pass on a
    machine where the import had merely been done somewhere else.
    """
    done = subprocess.run(
        [sys.executable, "-c",
         "import sys, app.nli_gate\n"
         "print(','.join(m for m in ('torch', 'transformers') if m in sys.modules))\n"],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "", f"imported eagerly: {done.stdout.strip()}"


def test_the_verifier_protocol_is_what_a_fake_satisfies():
    assert isinstance(RuleVerifier(), Verifier)


def test_a_gate_result_records_its_provenance():
    out = GateResult("accept", "entailment", 0.9412, "cross-encoder/x")
    assert out.provenance() == {"verdict": "entailment", "score": 0.9412,
                                "decision": "accept", "verifier": "cross-encoder/x"}


@pytest.mark.skipif(
    subprocess.run([sys.executable, "-c", "import transformers, torch"],
                   capture_output=True).returncode != 0,
    reason="the optional `nli` extra is not installed")
def test_the_real_checkpoint_reads_its_own_label_order():
    """Skipped without the extra; downloads the small checkpoint when present."""
    verifier = TransformersNliVerifier()
    verdict, score = verifier.verify(f"Dealers say {AVAILABLE}.",
                                     "Timing chain kit available everywhere")
    assert verdict == "entailment"
    assert score > 0.5
