"""Working out how to read a site with a model, from the browser's own snapshot.

The reader's sentence: *"Site recognition needs an AI to figure out the reading
structure via web extension's data."* Until this existed, whether Kriko could
read a page was decided by glob-matching its URL against hand-written adapters,
then by whatever schema.org product data the page happened to publish. Nothing
inferred a page's structure, and the only way to teach this installation a new
site was for the reader to press a button that spends a coding-agent run.

Three things make an *automatic* inference safe to run at all, and they are the
whole of this module's design:

* **The caller already has the page.** The extension scrapes the labels a page
  prints beside its values and the structured data it publishes for search
  engines, and sends both with every analysis. Nothing is fetched here and
  nothing could be: the page is already rendered and already past whatever bot
  check the site runs. What the model sees is that snapshot, capped.
* **The answer is data, checked like any other adapter.** A reply is parsed,
  then put through `sites.check` and `sites.reading` — the same two gates a
  pack's or an agent's adapter passes, including the refusal of an adapter that
  can only ever read nothing. Nothing is executed on either side of the wire:
  an inferred adapter is label rules and parse hints, never a selector and never
  code, which is the boundary `kriko/adapters.py` opens with.
* **Everything here fails open.** No local model, a model that answers late,
  answers prose, or answers an adapter that reads nothing: the page is simply
  not inferred and the answer the reader gets is the one they would have got
  before this module existed.

**Which plane, and why only one.** Inference is this machine's own model — the
one the reader configured in Settings → Local machine — and nothing else, ever.
The rule it follows is written down in `app/providers/__init__.py::resolve_agent`
and in `app/web/tasks.py::default_backend`: the paid plane runs only when the
reader picked it, never as a fallback, because a per-token bill that arrives
because a key happened to be saved is a charge nobody chose. A page load is the
purest case of that — the reader asked to have a listing read, not to buy a
model call — so this path never reaches for a key, and never for the coding-agent
CLI either: a CLI takes minutes and spends the reader's subscription, and the
one place it belongs is unchanged (`site_register`, on the reader's own press).
A reader who picked another agent keeps that pick; nothing is inferred for them,
and the press answers exactly as it did before.
"""

import hashlib
import logging
import threading
from datetime import UTC, datetime

from app import pagefacts, sites
from app.web import state
from kriko.adapters import _key, identity_vocabulary

log = logging.getLogger(__name__)

#: How long one inference call may take, in seconds.
#:
#: Not a preference. `extension/background.js` holds every request to the app on
#: a 30-second clock (`APP_TIMEOUT_MS`) and says "Kriko is open but did not
#: answer" when it expires — so an inference that outlives the request does not
#: fail open, it *replaces* the reader's answer with a red banner. This budget
#: leaves the scrape, the response and the transport room inside that 30, and is
#: short enough that a reader standing on a new site waits once rather than
#: once per page.
CALL_TIMEOUT = 12.0

#: How long a *failed* inference keeps a page shape out of the model's queue.
#:
#: A failure is not a judgement about the page — the model was still loading,
#: the server was busy, the reply was cut off — so it must not be permanent, or
#: one unlucky first page would leave a whole shop uninferable with nothing on
#: any screen to say why. It must not be free either: the next 12-second
#: timeout on every listing of that shop is a worse experience than a site that
#: is simply not inferred for ten minutes. A refusal is different and has no
#: window: the model *answered*, and its answer read none of the page's labels.
FAILED_BRAKE_SECONDS = 600

#: The reply budget in tokens. An adapter is one small JSON object; a model that
#: runs past this is composing prose about the page, which this path cannot use.
MAX_REPLY_TOKENS = 900

#: How many of a page's labels the shape digest is built from. The same number
#: the prompt's snapshot is capped at (`app/pagefacts.MAX_FACTS`), so the digest
#: and the prompt are bounded by one decision rather than by two: a page with
#: hundreds of rows is not made a different shape by rows nobody will read.
SHAPE_LABELS = pagefacts.MAX_FACTS

#: The shape a constrained local server is asked to hold the reply to. Loose on
#: purpose — `context` keys are the model's to name and a rule's own keys are
#: the engine's — but it insists on the one key without which nothing here can
#: work, and it keeps a small model from answering with a paragraph the fence
#: reader would then have to fish a JSON object out of.
ADAPTER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "site": {"type": "string"},
        "subject_kind": {"type": "string"},
        "match": {"type": "array", "items": {"type": "string"}},
        "identity": {"type": "object"},
        "context": {"type": "object"},
    },
    "required": ["identity"],
}


def shape_of(fields: dict) -> str:
    """A digest of a page's shape: its labels and its structured-data types.

    Keyed on the shape rather than on the URL because one site's listings are
    the same page with different values: inferring once per product page would
    be a model call per product page. Labels are folded exactly the way the
    engine folds them (`kriko.adapters._key`), so a site that prints "Yıl" on
    one page and "yıl" on the next is one shape rather than two — and the sort
    comes before the cap, so the same page cannot be two shapes because its
    fields arrived in a different order.
    """
    labels = sorted(
        {_key(label) for label in (fields or {}) if str(label).strip()}
    )[:SHAPE_LABELS]
    # The schema.org types the page publishes, which is the other half of "what
    # kind of page is this": a shop's `Product` and a vehicle site's `Car` are
    # different reading structures even when their label sets overlap.
    kind = str((fields or {}).get("ld:@type") or "").strip().casefold()
    return hashlib.sha256("\n".join([kind, *labels]).encode("utf-8")).hexdigest()[:32]


def plane(app_state_path, *, timeout: float = CALL_TIMEOUT) -> dict:
    """The one plane an inference call may use, and why not when there is none.

    Returns `{"ready", "complete", "model", "reason"}`. `complete` is a
    callable taking the prompt, and it is the local server's own socket: the
    address, the model name, the timeout and the loader options all come from
    what the reader set on the Local machine screen (`app.localplane.resolve`),
    so a model they chose stays chosen here too.

    Not ready is the ordinary answer and never an error. A reader who picked a
    coding or API agent in Settings made a choice, and `default_plane` keeps it;
    this path does not go behind it to the local model, and it must never
    substitute the paid plane — see the module docstring for the rule and where
    it is written down.
    """
    from app import localplane

    if not app_state_path:
        return _no_plane("this installation has no app state to read a model "
                         "choice from")
    try:
        found = localplane.resolve(app_state_path, with_search=False)
    except Exception:  # noqa: BLE001 — a probe that raises is a plane that is not ready
        return _no_plane("the local model could not be checked")
    if localplane.reader_chose_an_agent(app_state_path):
        return _no_plane("the reader picked another agent, so nothing is inferred")
    if not found.get("ready"):
        return _no_plane(str(found.get("reason") or "no local model is ready"))
    from app.providers.local_inference import OpenAICompatSocket

    # A floor as well as a ceiling: a reader who set a five-minute timeout for
    # a CPU model is right about their research runs and wrong about this path,
    # which a browser is waiting on.
    seconds = max(1.0, min(float(found.get("timeout") or timeout), timeout))
    return {
        "ready": True,
        "reason": "",
        "model": str(found.get("model") or ""),
        "complete": OpenAICompatSocket(
            found["url"], found["model"], timeout=seconds,
            max_tokens=MAX_REPLY_TOKENS, response_json_schema=ADAPTER_SCHEMA,
            runtime_options=found.get("runtime_options"),
            context_tokens=found.get("context_tokens"), temperature=0.0,
        ),
    }


def _no_plane(reason: str) -> dict:
    return {"ready": False, "complete": None, "model": "", "reason": reason}


def _bounded(complete, prompt: str, seconds: float) -> tuple[str, str]:
    """`(reply, why not)` from one call that cannot outlive `seconds`.

    The wait is bounded here rather than left to the socket because the socket
    also waits for a host permit (`app/providers/network.py`): with the reader's
    own research run holding the one local-inference slot, a call that never
    gets it would hold this page's request open until the extension gave up on
    Kriko altogether. Abandoning the worker is safe — a daemon thread's socket
    times out on its own and its permit is released by the response proxy — and
    nothing follows it: this path makes one call per page shape, ever, plus the
    one retry the local socket itself makes for a transient server error — the
    same policy every other local call gets.
    """
    out: dict = {}

    def run() -> None:
        try:
            out["reply"] = complete(prompt)
        except Exception as error:  # noqa: BLE001 — reported as a reason below
            out["error"] = error

    worker = threading.Thread(target=run, name="kriko-site-inference", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        return "", f"the model did not answer within {seconds:g} s"
    if "error" in out:
        return "", f"the model could not answer: {out['error']}"
    return str(out.get("reply") or ""), ""


#: What a single-turn model is told before the brief an agent gets. The brief
#: teaches the adapter contract and is the one place that does; this only says
#: what is different about answering once, with no tools and no second try.
PREFACE = """You are working out how to read a web page from what the browser
already found on it, and answering once. You cannot fetch anything, browse, or
ask a question: the snapshot below is the whole page, and your answer is the
last thing you write.

A rule may contain only these keys: {keys}. Anything else is ignored silently,
so an adapter full of invented keys looks exactly like one that works.

"""


def prompt_for(host: str, url: str, keys: str, sample: dict) -> str:
    """The brief, plus what a single-turn model has to be told.

    Deliberately the same `sites.BRIEF` an agent is handed: the vocabulary it
    teaches is the vocabulary `kriko/adapters.py` interprets, and a second
    prompt written for this door would be the second place for that to drift.
    The allowed rule keys are read off `sites.RULE_KEYS` for the same reason.
    """
    allowed = ", ".join(f"`{key}`" for key in sites.RULE_KEYS)
    return PREFACE.format(keys=allowed) + sites.brief(host, url, keys, sample)


def infer(store, app_conn, *, app_state_path=None, url: str, fields: dict,
          title: str = "", description: str = "", product_name: str = "",
          timeout: float = CALL_TIMEOUT) -> dict | None:
    """The adapter an inference produced for this page, or `None`. Never raises.

    The caller is answering a page nothing installed can read, so this is
    always the *last* thing tried: a pack's adapter, a pack's any-site adapter
    and the product's own name have all already declined.

    Exactly one call is made per page shape per host, and the outcome of that
    call — including "the model answered nothing usable" — is what the next
    page of the same shape is answered from. A cache of failures is the whole
    reason a reader browsing a shop Kriko cannot read does not pay for the same
    model call on every listing.
    """
    if app_conn is None or not store:
        return None
    host = sites.host_of(url)
    if not host:
        return None
    digest = shape_of(fields)
    for row in state.local_adapters(app_conn, enabled_only=False):
        if row["host"] == host and not row.get("enabled", 1):
            # The reader turned this site off (`POST /api/sites/{host}/inferred`).
            # Every page here asks the same consent question, and a switch a
            # later page shape could quietly flip back by inferring a new
            # adapter is not a switch. Not recorded: the shape cache is about
            # what a model was asked, and nothing was.
            return None
    if any(_brake(row) for row in
           state.site_inferences(app_conn, host=host, shape=digest)):
        # This exact page shape has been to a model already, and the record of
        # what came of it still stands. An `ok` row means the adapter is in
        # `local_adapters` and the reader has since turned it off, or the page
        # changed under it; a `refused` row is a judgement about this shape.
        # `_brake` is the one that expires, and why is there.
        return None

    sample = sites.sample(url=url, title=title, fields=fields,
                          description=description, product={"name": product_name})
    if not sample["facts"]:
        # Nothing labelled on the page to infer from: a call here would be one
        # per page and could not answer. Not recorded, so the first page that
        # does carry labels is inferred the moment it arrives.
        return None

    keys = _keys_brief(store)
    if not keys:
        # No enabled pack declares an identity key, so every adapter a model
        # could write would be refused by `check` for mapping into nothing.
        return None

    chosen = plane(app_state_path, timeout=timeout)
    if not chosen.get("ready"):
        # Nothing recorded: a reader who starts their model server later must
        # have their pages inferred, not be told these shapes were tried.
        log.info("nothing was inferred on %s: %s", host, chosen.get("reason", ""))
        return None

    def gave_up(outcome: str, detail: str) -> None:
        """Record why, and answer "nothing was inferred"."""
        log.info("nothing was inferred on %s: %s", host, detail)
        state.save_site_inference(
            app_conn, host=host, shape=digest, state=outcome,
            detail=detail[:400], model=chosen["model"])
        return None

    reply, why = _bounded(chosen["complete"],
                          prompt_for(host, url, keys, sample), timeout)
    if why:
        return gave_up("failed", why)

    from app.packauthor import _payload  # the same fence reader every door uses

    spec = _payload(reply)
    if not spec:
        return gave_up("refused", "the model printed no adapter")
    # The host is a fact from the reader's browser, never the model's to choose.
    # `check` validates `match` against `site`, so a model that wrote another
    # site's pattern here is refused rather than handed a permission on a host
    # the reader never opened — the boundary `sites.check` exists for, kept.
    offered = {**spec, "site": host}
    try:
        checked = sites.check(offered, host=host)
    except sites.SiteRefused as exc:
        return gave_up("refused", f"the adapter was refused: {exc}")

    vocabulary = identity_vocabulary(store)
    if not set(checked.get("identity") or {}) & set(vocabulary):
        # The keys an identity may be mapped into are the packs', not the
        # model's (`app/sites.py::BRIEF` says so, and an invented one resolves
        # every page to nothing). A hand-written adapter is allowed to be
        # wrong about this and show it; an automatic one is not, because
        # nobody is watching the page it mis-reads.
        return gave_up("refused", "the adapter's identity keys are not any "
                                  "installed pack's")
    read = sites.reading(
        checked, sample["facts"], url=str(sample.get("url") or url),
        title=str(sample.get("title") or ""),
        description=str(sample.get("description") or ""), vocabulary=vocabulary)
    if not read["identity"]:
        return gave_up(
            "refused",
            f"the adapter reads none of the {len(sample['facts'])} labelled "
            f"fact(s) the browser saw on {host}, so no identity key resolves")

    state.save_local_adapter(app_conn, host=host, spec=checked,
                             source="inference", pack_id="")
    state.save_site_inference(
        app_conn, host=host, shape=digest, state="ok",
        detail=f"{len(read['identity'])} identity key(s), "
               f"{len(read['context'])} context",
        model=chosen["model"])
    log.info("%s can be read now: an inferred adapter from %s", host, chosen["model"])
    # `learned_by` rides the spec so the caller can say *how* the page was read
    # without a second lookup of the row it was just written from.
    return {**checked, "learned_by": "inference"}


def _brake(row: dict) -> bool:
    """Whether a recorded attempt still stops this page shape being asked again.

    A refusal and a stored adapter never stop being true. A failure does: a
    model that was loading when the reader opened the first listing is not a
    model that cannot read the site, and a row that outlived its own cause
    would be a site this installation can never learn again. An unreadable or
    naive timestamp is treated as expired — the safe direction is a second
    call, never a permanent silence.
    """
    if str(row.get("state") or "") != "failed":
        return True
    try:
        when = datetime.fromisoformat(str(row.get("at") or ""))
        age = (datetime.now(UTC) - when).total_seconds()
    except (TypeError, ValueError):
        return False
    return age < FAILED_BRAKE_SECONDS


def _keys_brief(store) -> str:
    """The identity keys the installed packs declare, or `""` when there are none.

    `app/web/tasks.py::identity_keys_text` is the one renderer of that list, for
    the agent brief and for this prompt both — imported rather than rewritten,
    because two lists of the keys a lookup will accept is two lists to drift.
    """
    from app.web.tasks import NO_IDENTITY_KEYS, identity_keys_text

    text = identity_keys_text(store)
    return "" if text == NO_IDENTITY_KEYS else text
