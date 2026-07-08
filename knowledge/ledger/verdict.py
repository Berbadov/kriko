"""One strong-model verdict per claim-cluster.

Replaces judge.py's five ministral gates and promote.py's bypass/veto stack
(design_flaws.md Flaw 5): a single claude-haiku-4-5 call sees the whole
cluster, the component, its sibling codes, and the product principle, and
answers attribution + support + value + severity + TR/EN copy in one JSON
object. Verdicts are cached by input hash — unchanged evidence never pays
twice. Batches >4 clusters go through the Message Batches API (50% off)."""

import hashlib
import json
import re
import time

from knowledge.ledger.costs import Budget, estimate_cost
from knowledge.stoplists import sibling_codes_for

VERDICT_MODEL = "claude-haiku-4-5"
PROMPT_VERSION = 1
_MAX_TOKENS = 1200
_EST_OUT_TOKENS = 350

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
    from anthropic import Anthropic
    return Anthropic()


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
    return f"""You are auditing a candidate used-car reliability claim for component
"{payload['component_id']}" (domain: {payload['domain']}).

CRITICAL — sibling components that are DIFFERENT physical parts and must NOT be
conflated with {payload['component_id']}: {siblings}. If the evidence describes a
sibling's failure mode, attribute it to the sibling, not to {payload['component_id']}.
The "found-while-researching" field is search context, NOT evidence of attribution.

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


def _est_usd(todo, batch: bool) -> float:
    key = VERDICT_MODEL + ("#batch" if batch else "")
    return sum(estimate_cost(key, len(build_prompt(p)) // 4, _EST_OUT_TOKENS)
               for _, p, _ in todo)


def pending_verdict_estimate(conn) -> tuple[int, float]:
    todo = pending_clusters(conn)
    return len(todo), _est_usd(todo, batch=len(todo) > 4)


def _store(conn, budget, price_key, cid, h, text, tin, tout) -> bool:
    # The API billed these tokens whether or not the JSON parses, so charge
    # first — otherwise an unparseable verdict silently under-reports real
    # spend and could slip a run past --max-usd.
    usd = budget.charge(price_key, tin, tout)
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


def run_verdicts(conn, budget: Budget, use_batch: bool = True) -> int:
    todo = pending_clusters(conn)
    if not todo:
        return 0
    batch_mode = use_batch and len(todo) > 4
    budget.precheck(_est_usd(todo, batch_mode))  # batches can't abort mid-flight
    client = _client()
    saved = 0
    if batch_mode:
        price_key = VERDICT_MODEL + "#batch"
        batch = client.messages.batches.create(requests=[
            {"custom_id": str(cid),
             "params": {"model": VERDICT_MODEL, "max_tokens": _MAX_TOKENS,
                        "messages": [{"role": "user", "content": build_prompt(p)}]}}
            for cid, p, _ in todo
        ])
        while True:
            b = client.messages.batches.retrieve(batch.id)
            if b.processing_status == "ended":
                break
            time.sleep(30)
        by_id = {str(cid): (cid, h) for cid, _, h in todo}
        for r in client.messages.batches.results(batch.id):
            if r.result.type != "succeeded":
                print(f"  cluster {r.custom_id}: batch item {r.result.type}")
                continue
            m = r.result.message
            cid, h = by_id[r.custom_id]
            saved += _store(conn, budget, price_key, cid, h, m.content[0].text,
                            m.usage.input_tokens, m.usage.output_tokens)
    else:
        for cid, payload, h in todo:
            m = client.messages.create(
                model=VERDICT_MODEL, max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": build_prompt(payload)}])
            saved += _store(conn, budget, VERDICT_MODEL, cid, h, m.content[0].text,
                            m.usage.input_tokens, m.usage.output_tokens)
    return saved
