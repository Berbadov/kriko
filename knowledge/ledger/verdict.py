"""One strong-model verdict per claim-cluster.

Replaces judge.py's five ministral gates and promote.py's bypass/veto stack
(design_flaws.md Flaw 5): a single deepseek-v4-flash call sees the whole
cluster, the component, its sibling codes, and the product principle, and
answers attribution + support + value + severity + TR/EN copy in one JSON
object. Verdicts are cached by input hash — unchanged evidence never pays
twice. DeepSeek has no batch/async job API (unlike Anthropic/Mistral/OpenAI,
per api-docs.deepseek.com) — every call is synchronous."""

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from knowledge.ledger.costs import Budget, estimate_cost
from knowledge.stoplists import sibling_codes_for, title_has_dtc_code

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
VERDICT_MODEL = "deepseek-v4-flash"
PROMPT_VERSION = 1
# A complete verdict is 12 keys with bilingual (EN+TR) title/rationale/advice;
# real completions run ~1000-2200 output tokens, so a 1200 cap truncated ~1/4 of
# them mid-string into unparseable JSON. Size the cap and the cost estimate to
# the observed distribution with headroom.
_MAX_TOKENS = 3000
_EST_OUT_TOKENS = 1100
# DeepSeek has no batch API, but each verdict call is I/O-bound (a synchronous
# HTTP round-trip). Fanning the calls across a thread pool turns a ~9h serial
# run over ~1k clusters into minutes; the OpenAI SDK retries 429s with backoff,
# so moderate concurrency self-heals against rate limits.
_MAX_WORKERS = 16

REQUIRED_KEYS = frozenset({
    "attribution", "supported", "refuted_by", "product_value", "severity",
    "title_en", "title_tr", "rationale_en", "rationale_tr",
    "inspection_advice_en", "inspection_advice_tr",
})

_PRODUCT_PRINCIPLE = """Kriko surfaces used-car risks a buyer CANNOT get from a standard
pre-purchase inspection (ekspertiz): config-specific (this engine/gearbox code),
predictable from mileage/age/fuel/transmission alone, maintenance-interval items
("due unless the ad proves otherwise"), high-consequence/expensive systems.
LOW value: generic warning lights, anything true of all cars, anything a routine
inspection catches (fluids, brake wear, compression, injector bench tests)."""


def _client():
    from openai import OpenAI
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=_DEEPSEEK_BASE_URL)


def cluster_payload(conn, cluster_id: int) -> dict:
    cl = conn.execute("SELECT * FROM clusters WHERE id=?", (cluster_id,)).fetchone()
    rows = conn.execute(
        "SELECT e.title, e.rationale, e.inspection_advice, e.severity, e.quote,"
        " e.component_hint, d.url, d.site_or_channel, d.source_type, d.target_hint"
        " FROM cluster_members m JOIN evidence e ON e.id = m.evidence_id"
        " JOIN documents d ON d.id = e.doc_id WHERE m.cluster_id=? ORDER BY e.id",
        (cluster_id,),
    ).fetchall()
    return {
        "component_id": cl["component_id"],
        "domain": cl["domain"],
        "sibling_codes": sorted(sibling_codes_for(cl["component_id"])),
        "evidence": [dict(r) for r in rows],
    }


def input_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"v{PROMPT_VERSION}:{canonical}".encode()).hexdigest()


_STRUCTURED_GUIDANCE = """\
RECALL RECORDS — at least one evidence item here has source_type "structured":
it is an OFFICIAL safety recall record (e.g. NHTSA), not owner testimony.
- The record itself IS the claim: supported=true unless another item refutes it.
- An official safety recall affecting this model is exactly the config-specific,
  high-consequence signal Kriko exists to surface — product_value "high" unless
  the recall is pure paperwork trivia (VIN label misprints, compliance docs).
- Attribution: a recall covers the whole vehicle, so attribute it to the part
  the failed system belongs to — airbags/seatbelts/structure/locks/suspension
  to the model's body part, ignition/infotainment/wiring to its electrical part.
  'foreign' is ONLY for recalls of vehicles outside this catalog."""


def build_prompt(payload: dict) -> str:
    ev_lines = []
    for i, e in enumerate(payload["evidence"], 1):
        ev_lines.append(
            f"[{i}] source={e['url']} ({e['site_or_channel']}, {e['source_type']})\n"
            f"    title: {e['title']}\n    rationale: {e['rationale']}\n"
            f"    quote: {e['quote']}\n    component_hint: {e['component_hint']}\n"
            f"    found-while-researching: {e['target_hint']}"
        )
    siblings = ", ".join(payload["sibling_codes"]) or "none registered"
    # Structured-only guidance: including this only when recall records are
    # present keeps every testimony-only prompt byte-identical (verdict cache
    # stays valid — input_hash covers the payload, and unchanged payloads
    # never re-spend).
    structured_block = (
        "\n" + _STRUCTURED_GUIDANCE + "\n"
        if any(e.get("source_type") == "structured" for e in payload["evidence"])
        else ""
    )
    return f"""You are auditing a candidate used-car reliability claim for component
"{payload['component_id']}" (domain: {payload['domain']}).

CRITICAL — sibling components that are DIFFERENT physical parts and must NOT be
conflated with {payload['component_id']}: {siblings}. If the evidence describes a
sibling's failure mode, attribute it to the sibling, not to {payload['component_id']}.
The "found-while-researching" field is search context, NOT evidence of attribution.
{structured_block}
Product principle:
{_PRODUCT_PRINCIPLE}

Evidence ({len(payload['evidence'])} item(s)):
{chr(10).join(ev_lines)}

Return ONLY a JSON object with exactly these keys:
{{"attribution": {{"component_id": "<the component this evidence is actually about,
or 'foreign' if it is about a car/part outside this catalog entry, or 'none' if
undeterminable>", "confidence": "high|medium|low", "reason": "<one sentence>"}},
"supported": <true if the evidence concretely supports a real chronic issue>,
"refuted_by": [<evidence numbers that contradict the claim, usually empty>],
"product_value": "high|low|inspection_covered|generic",
"severity": "high|medium|low",
"title_en": "<brief phrase, <12 words, names failure + component code, no DTC codes>",
"title_tr": "<same in Turkish>",
"rationale_en": "<2-3 plain sentences for a non-mechanic buyer>",
"rationale_tr": "<same in Turkish>",
"inspection_advice_en": "<what to check at viewing; DTC codes allowed here>",
"inspection_advice_tr": "<same in Turkish>"}}"""


def parse_verdict(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"verdict is not valid JSON: {exc}") from exc
    missing = REQUIRED_KEYS - set(data)
    if missing:
        raise ValueError(f"verdict missing keys: {sorted(missing)}")
    return data


def gate_product_value(evidence_titles, v: dict) -> str | None:
    """Deterministic downgrade of the model's self-reported product_value.

    The verdict model is unreliable on product value (the gold eval catches it):
    handed a raw fault-code litany it launders the codes out of its rewritten
    title_en and still returns product_value="high". A claim whose EVIDENCE leads
    with DTC codes is the low-value "DTC litany" form CLAUDE.md drops — force it
    off "high" regardless of what the model said. Same shape as promote.py's
    deterministic pre-checks: downgrade-only, never raises the model's judgment.
    """
    pv = v.get("product_value")
    if pv == "high" and any(title_has_dtc_code(t or "") for t in evidence_titles):
        return "low"
    return pv


def pending_clusters(conn) -> list[tuple[int, dict, str]]:
    out = []
    for row in conn.execute("SELECT id FROM clusters ORDER BY id"):
        payload = cluster_payload(conn, row["id"])
        h = input_hash(payload)
        hit = conn.execute(
            "SELECT 1 FROM verdicts WHERE input_hash=?", (h,)).fetchone()
        if not hit:
            out.append((row["id"], payload, h))
    return out


def _est_usd(todo) -> float:
    return sum(estimate_cost(VERDICT_MODEL, len(build_prompt(p)) // 4, _EST_OUT_TOKENS)
               for _, p, _ in todo)


def pending_verdict_estimate(conn) -> tuple[int, float]:
    todo = pending_clusters(conn)
    return len(todo), _est_usd(todo)


def _store(conn, budget, cid, h, text, tin, tout) -> bool:
    # The API billed these tokens whether or not the JSON parses, so charge
    # first — otherwise an unparseable verdict silently under-reports real
    # spend and could slip a run past --max-usd.
    usd = budget.charge(VERDICT_MODEL, tin, tout)
    try:
        v = parse_verdict(text)
    except ValueError as exc:
        print(f"  cluster {cid}: unparseable verdict skipped ({exc})")
        return False
    conn.execute(
        "INSERT OR REPLACE INTO verdicts (input_hash, model,"
        " verdict_json, tokens_in, tokens_out, usd, created_at)"
        " VALUES (?,?,?,?,?,?, datetime('now'))",
        (h, VERDICT_MODEL, json.dumps(v, ensure_ascii=False), tin, tout, usd),
    )
    conn.commit()
    return True


def _call(client, payload: dict) -> tuple[str, int, int]:
    m = client.chat.completions.create(
        model=VERDICT_MODEL, max_tokens=_MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": build_prompt(payload)}])
    return (m.choices[0].message.content,
            m.usage.prompt_tokens, m.usage.completion_tokens)


def run_verdicts(conn, budget: Budget, max_workers: int = _MAX_WORKERS) -> int:
    todo = pending_clusters(conn)
    if not todo:
        return 0
    budget.precheck(_est_usd(todo))
    client = _client()
    saved = 0
    # Only the LLM round-trips run concurrently; every DB write and budget
    # charge is marshalled back to this thread via _store (sqlite3 connections
    # and Budget are single-threaded). A failed call leaves its cluster pending
    # for the next resume — verdicts are content-hash cached and committed
    # per-row, so nothing is lost.
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_call, client, payload): (cid, h)
                   for cid, payload, h in todo}
        for fut in as_completed(futures):
            cid, h = futures[fut]
            try:
                text, tin, tout = fut.result()
            except Exception as exc:  # noqa: BLE001 — one bad call must not sink the batch
                print(f"  cluster {cid}: verdict call failed, resume will retry ({exc})")
                continue
            saved += _store(conn, budget, cid, h, text, tin, tout)
    return saved
