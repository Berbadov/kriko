"""Does the claim say what its own source says? — the NLI evidence gate.

The acceptance path already proves that a claim's *quote* is on its *page*
(`app.categorypack.ground`, `app.findings.accept_findings`). It proves nothing
about whether the quote supports the claim. So a report can be perfectly
sourced and still be wrong in the one way that matters: it reads a page that
says "the chain is available", and files "the chain is unobtainable", with the
real sentence quoted under it. The quote check passes, because the quote is
real. Nothing else was asking.

This module asks it, with a small cross-encoder trained for natural language
inference (premise = the source span, hypothesis = the claim). It decides
nothing about a category, and it never decides anything on its own —
`NliGate.check` returns a verdict and a decision, and the caller acts on the
decision exactly as it acts on a failed quote.

**Why it lives in `app/` and not `app/pipeline/`.** The gate sits on the
acceptance path (`app/categorypack.py`, `app/findings.py`), which both doors
share; `app/pipeline/` is the driver layer, and `test_repo_invariants.py`'s
`test_app_never_imports_the_pipeline_layer` forbids an interface from reaching
into it. So this is a driver that belongs beside the path it guards, and it
imports nothing upward.

**Policy, and why it is not a review step.** `CLAUDE.md`'s "Automation — no
human in the data path" holds here as everywhere:

* entailment at or above `accept_threshold` — **accept**;
* contradiction — **drop**, and say so, the way a quote that is not on its page
  is dropped;
* neutral, or an entailment under the threshold — **flag**: held out of the
  catalog and named in the run's log, the submit verdict and the coverage
  report, so an automated retry or the agent can re-source it. A held claim is
  not a claim waiting for a person; it is a gap with a reason.

**Fail open.** No model configured, no `transformers`/`torch` installed, a
model that will not load, a verifier that raises: the gate is off, every claim
passes through unchanged, and the result says `nli: unchecked`. Extraction must
never stall on a check that is an improvement rather than a condition.

**The desktop installer carries no model.** `transformers` and `torch` are the
optional `nli` extra (`pyproject.toml`), imported inside
`TransformersNliVerifier.__init__` and nowhere else, and excluded from the
frozen sidecar (`packaging/freeze_imports.py`). A reader's install has no
verifier, so its gate is off by construction.
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "Verdict", "GateResult", "Verifier", "NliGate", "TransformersNliVerifier",
    "gate_from_env", "DEFAULT_MODEL", "ENV_MODEL", "ENV_ACCEPT",
]

Verdict = Literal["entailment", "neutral", "contradiction"]

#: The three labels a cross-encoder NLI head is trained on. A model's own
#: `id2label` is read and mapped onto these, never assumed: the order differs
#: between checkpoints and a reversed one turns every contradiction into an
#: acceptance, silently.
LABELS: tuple[Verdict, ...] = ("entailment", "neutral", "contradiction")

#: A DeBERTa-v3-small cross-encoder trained on MNLI/SNLI/FEVER/ANLI — about
#: 180 MB, and a second or two per claim on a CPU. Big enough to read a
#: sentence pair, small enough to self-host on the reader's machine.
DEFAULT_MODEL = "cross-encoder/nli-deberta-v3-small"

#: `KRIKO_NLI_MODEL` names the checkpoint, or is empty for the default. Set to
#: `off` to turn the gate off on a machine that has the extra installed.
ENV_MODEL = "KRIKO_NLI_MODEL"
#: `KRIKO_NLI_ACCEPT` is the entailment probability a claim needs to enter.
ENV_ACCEPT = "KRIKO_NLI_ACCEPT"

#: The floor of an entailment that enters the catalog. Deliberately not 0.5:
#: a three-way softmax gives a claim unrelated to its quote a third of the
#: mass, and the cost of being wrong here is a claim in a shared catalog.
DEFAULT_ACCEPT = 0.70

#: How far the premise is widened around the quote, in characters, before it
#: is cut to the model's own maximum length. Enough for the sentence the quote
#: sits in plus its neighbours, which is what a pronoun in the claim points at.
WIDEN = 320


@dataclass(frozen=True)
class GateResult:
    """What the gate decided about one claim, and why.

    `decision` is what the caller acts on. `verdict` and `score` are what it
    was decided from, kept so the claim's provenance can say "entailment 0.94"
    rather than "accepted". `verifier` names the model that answered, or "" when
    none did — a stored verdict outlives the model that produced it.
    """

    decision: Literal["accept", "flag", "drop"]
    verdict: Verdict | None
    score: float
    verifier: str = ""
    reason: str = ""

    def provenance(self) -> dict:
        """The free-form record a claim keeps beside its evidence."""
        return {"verdict": self.verdict or "unchecked", "score": round(self.score, 4),
                "decision": self.decision, "verifier": self.verifier}


@runtime_checkable
class Verifier(Protocol):
    """One sentence pair in, one verdict and a score out.

    `verify` answers for one pair and `verify_many` for a batch; a verifier only
    has to implement the first, and the gate batches through the second when it
    is there.
    """

    def verify(self, premise: str, hypothesis: str) -> tuple[Verdict, float]: ...


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKC", str(text or ""))
    return " ".join(plain.split())


@dataclass
class NliGate:
    """The decision rule. A verifier answers; this decides what the answer means.

    `claim` is a mapping with a `title` and either a `quote` (the source span,
    already proved to be on the page) or a `premise` (the page text, from which
    the quote is widened). `check` is the one call the acceptance paths make.
    """

    verifier: Verifier
    accept_threshold: float = DEFAULT_ACCEPT
    name: str = ""
    _batch: Callable[[Sequence[tuple[str, str]]], list[tuple[Verdict, float]]] | None = field(
        default=None, repr=False)

    def __post_init__(self) -> None:
        many = getattr(self.verifier, "verify_many", None)
        self._batch = many if callable(many) else None
        if not self.name:
            self.name = str(getattr(self.verifier, "name", "") or type(self.verifier).__name__)

    def __call__(self, claim: dict) -> GateResult:
        return self.check(claim)

    # ── what the model is shown ──────────────────────────────────────────

    @staticmethod
    def premise_of(claim: dict) -> str:
        """The source span: the quote, widened to its passage in the page text.

        The quote alone is often a clause — "unobtainable in some markets" —
        and a claim that restates the sentence around it would be judged
        against half of what it says. Widening is only possible when the page
        text is in hand, which `ground` and `accept_findings` both have.
        """
        quote = _norm(claim.get("quote", ""))
        page = str(claim.get("premise") or "")
        if not page:
            return quote
        at = page.find(quote) if quote else -1
        if at < 0:
            return quote or _norm(page[: 2 * WIDEN])
        return _norm(page[max(0, at - WIDEN): at + len(quote) + WIDEN])

    @staticmethod
    def hypothesis_of(claim: dict) -> str:
        """The claim itself: its title, and its body when it has one."""
        title = _norm(claim.get("title", ""))
        body = _norm(claim.get("body", ""))
        if not body or body == title:
            return title
        return f"{title}. {body}"

    # ── the decision ─────────────────────────────────────────────────────

    def decide(self, verdict: Verdict, score: float) -> GateResult:
        if verdict == "contradiction":
            return GateResult("drop", verdict, score, self.name,
                              "the source says the opposite of the claim")
        if verdict == "entailment" and score >= self.accept_threshold:
            return GateResult("accept", verdict, score, self.name)
        return GateResult(
            "flag", verdict, score, self.name,
            f"the source does not clearly support the claim ({verdict} {score:.2f}, "
            f"needs entailment {self.accept_threshold:.2f})")

    def check(self, claim: dict) -> GateResult:
        """One claim. A verifier that fails is a gate that is off, not a crash."""
        premise, hypothesis = self.premise_of(claim), self.hypothesis_of(claim)
        if not premise or not hypothesis:
            return GateResult("flag", None, 0.0, self.name,
                              "no source span or no claim text to compare")
        try:
            verdict, score = self.verifier.verify(premise, hypothesis)
        except Exception as error:  # noqa: BLE001 — fail open, see the module
            return GateResult("accept", None, 0.0, self.name,
                              f"the verifier failed, so the claim passed unchecked: {error}")
        return self.decide(verdict, score)

    def check_many(self, claims: Sequence[dict]) -> list[GateResult]:
        """The same decision, batched where the verifier can batch.

        A batch verifier that raises is retried one claim at a time, so one bad
        pair cannot take its neighbours' verdicts down with it.
        """
        if self._batch is None or len(claims) < 2:
            return [self.check(one) for one in claims]
        pairs = [(self.premise_of(one), self.hypothesis_of(one)) for one in claims]
        if any(not premise or not hypothesis for premise, hypothesis in pairs):
            return [self.check(one) for one in claims]
        try:
            answers = self._batch(pairs)
        except Exception:  # noqa: BLE001 — see `check`
            return [self.check(one) for one in claims]
        if len(answers) != len(claims):
            return [self.check(one) for one in claims]
        return [self.decide(verdict, score) for verdict, score in answers]


class TransformersNliVerifier:
    """A small NLI cross-encoder on the CPU, loaded on first use.

    `transformers` and `torch` are imported here and nowhere else in the
    package, so a machine without the `nli` extra can import this module,
    construct nothing, and run with the gate off. The label order comes from
    the checkpoint's own `id2label`; a checkpoint whose head is not three-way
    NLI is refused rather than guessed at.
    """

    def __init__(self, model: str = DEFAULT_MODEL, *, max_length: int | None = None) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.name = model
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model)
        self._model = AutoModelForSequenceClassification.from_pretrained(model)
        self._model.eval()
        config = self._model.config
        self._order = _label_order(dict(getattr(config, "id2label", {}) or {}))
        self.max_length = int(max_length or int(getattr(self._tokenizer, "model_max_length", 512)))
        if self.max_length > 4096 or self.max_length <= 0:  # the sentinel a tokenizer uses for "unset"
            self.max_length = 512

    def verify(self, premise: str, hypothesis: str) -> tuple[Verdict, float]:
        return self.verify_many([(premise, hypothesis)])[0]

    def verify_many(self, pairs: Sequence[tuple[str, str]]) -> list[tuple[Verdict, float]]:
        torch = self._torch
        batch = self._tokenizer(
            [premise for premise, _ in pairs], [hypothesis for _, hypothesis in pairs],
            truncation=True, max_length=self.max_length, padding=True, return_tensors="pt")
        with torch.no_grad():
            logits = self._model(**batch).logits
        probabilities = torch.softmax(logits, dim=-1).tolist()
        out: list[tuple[Verdict, float]] = []
        for row in probabilities:
            best = max(range(len(self._order)), key=lambda at: row[at])
            out.append((self._order[best], float(row[best])))
        return out


def _label_order(id2label: dict) -> tuple[Verdict, ...]:
    """Map a checkpoint's own label ids onto the three verdicts, or refuse.

    `cross-encoder/nli-deberta-v3-small` names its head
    `contradiction/entailment/neutral`, in that order; another checkpoint names
    the same three in another order. Reading the config is the difference
    between a gate and a coin.
    """
    order: list[Verdict | None] = []
    for index in range(len(id2label)):
        label = str(id2label.get(index, id2label.get(str(index), ""))).casefold()
        order.append(next((one for one in LABELS if one in label), None))
    if sorted(one or "" for one in order) != sorted(LABELS):
        raise ValueError(
            "the NLI checkpoint's id2label is not entailment/neutral/contradiction: "
            f"{id2label!r}")
    return tuple(one for one in order if one is not None)


def gate_from_env(environ=None) -> NliGate | None:
    """The gate this machine is configured for, or None for "off".

    None when `KRIKO_NLI_MODEL` is `off`, when the `nli` extra is not installed,
    or when the checkpoint will not load — each of which leaves every claim
    passing through unchanged and marked unchecked. A checkpoint whose label
    order cannot be read is also off, because the alternative is a gate that
    silently inverts every verdict; the reason is on the gate's own name so a
    caller that logs it says why.
    """
    env = os.environ if environ is None else environ
    wanted = str(env.get(ENV_MODEL, "")).strip()
    if wanted.casefold() == "off":
        return None
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return None
    try:
        threshold = float(env.get(ENV_ACCEPT, DEFAULT_ACCEPT))
    except ValueError:
        threshold = DEFAULT_ACCEPT
    try:
        verifier = TransformersNliVerifier(wanted or DEFAULT_MODEL)
    except Exception as error:  # noqa: BLE001 — a model that will not load is a gate that is off
        return NliGate(_Unavailable(f"{wanted or DEFAULT_MODEL}: {error}"),
                       accept_threshold=threshold, name="unavailable")
    return NliGate(verifier, accept_threshold=threshold)


class _Unavailable:
    """A verifier that is never asked: the gate it belongs to is off.

    It exists so a caller that logs "the gate is off" can say why — a
    checkpoint that would not load — instead of the same silence as a machine
    that never configured one.
    """

    def __init__(self, reason: str) -> None:
        self.name = f"unavailable ({reason})"

    def verify(self, premise: str, hypothesis: str) -> tuple[Verdict, float]:
        raise RuntimeError(self.name)

