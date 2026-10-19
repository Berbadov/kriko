"""Shared, validated context and evidence rules for research prompts."""

import re

from app import prefs


_RESPONSE_LENGTH = (
    "Choose length to match complexity, stakes, and evidence. A clear low-stakes "
    "fact may take one sentence; a consequential choice needs room for constraints, "
    "uncertainty, and evidence. Honor explicit requests for brevity or detail. There "
    "is no fixed word target: cover decision-critical points without padding."
)
_DETAIL_REQUEST = re.compile(r"\b(?:detail|details|detailed|explain|in depth|everything)\b", re.I)
_BRIEF_REQUEST = re.compile(r"\b(?:brief|briefly|short|concise|just the answer|one sentence)\b", re.I)


def response_length_guidance(question: str = "", *, detailed: bool = False) -> str:
    """Tell the model to scale its reply to this question and the reader's request."""
    question = str(question or "")
    if detailed or _DETAIL_REQUEST.search(question):
        return _RESPONSE_LENGTH + " The reader asked for detail; explain the relevant distinctions."
    if _BRIEF_REQUEST.search(question):
        return _RESPONSE_LENGTH + " The reader asked for brevity; lead with the answer."
    return _RESPONSE_LENGTH

COMPATIBILITY_GUIDANCE = (
    "Compatibility is separate from whether a product has a fault. For fitment "
    "or compatibility claims, give a positive fit answer "
    "only when the source matches the exact item and every relevant constraint. "
    "For PC parts, check socket, chipset and BIOS support, memory generation, "
    "form factor, power connectors, dimensions and clearance as relevant. For a "
    "vehicle part, check model year, generation, market, engine code, transmission "
    "or body and exact OE or replacement part number as relevant. A shared model "
    "name or broad fitment list is not enough. Separate physical fit from "
    "electrical, firmware and functional support. If a decisive detail is missing, "
    "say compatibility is unconfirmed and name the detail to check. Do not carry "
    "fitment over from a nearby revision or year."
)

SELLER_GUIDANCE = (
    "When assessing seller credibility, identify the seller by "
    "its own trading name and platform, and keep the platform apart from the "
    "individual seller. Use independent reviews, consumer or owner forums, "
    "complaints, and company or regulatory records. Prefer dated first-hand "
    "reports; distinguish an allegation from a verified finding, and note when "
    "evidence is one person's account or may refer to a different business with "
    "the same name. Do not treat the marketplace's reputation as the seller's. "
    "Report only what a page states; if no page supports an answer, say the seller "
    "could not be verified. Never infer fraud, safety or dishonesty from silence, "
    "a missing review, or a low review count."
)

_COMPATIBILITY = re.compile(
    r"\b(?:compatible|compatibility|fitment|fit|fits|fitting|will it work|"
    r"work with|supported|socket|motherboard|cpu|processor|ram|memory module|"
    r"transmission|engine code|part number|oem|oe number|vin|uyumlu|uyumluluk|"
    r"sığar|sagar|uyar mı|parça numarası|motor kodu)\b", re.I)
_SELLER = re.compile(
    r"\b(?:seller|vendor|shop|store|dealer|company|business|merchant|"
    r"satıcı|satici|mağaza|magaza|firma|esnaf|trustworthy|legit|scam|fraud)\b", re.I)
_FITMENT_INTENT = re.compile(
    r"\b(?:compatible|compatibility|fitment|fits?|fitting|will it work|"
    r"work with|supported|uyumlu|uyumluluk|uyar mı|sığar|sagar)\b", re.I)
_SELLER_INTENT = re.compile(
    r"\b(?:seller|vendor|shop|store|dealer|merchant|satıcı|satici|mağaza|"
    r"magaza|trustworthy|legit|scam|fraud)\b", re.I)


def question_guidance(question: str) -> str:
    """Return only the specialized evidence rule relevant to this question."""
    rules = []
    if _COMPATIBILITY.search(str(question or "")):
        rules.append(COMPATIBILITY_GUIDANCE)
    if _SELLER.search(str(question or "")):
        rules.append(SELLER_GUIDANCE)
    return "\n".join(rules)


def requires_grounded_web(question: str) -> bool:
    """Whether compatibility or seller claims need current source-backed research."""
    question = str(question or "")
    return bool(_FITMENT_INTENT.search(question) or _SELLER_INTENT.search(question))


def market_guidance(region: str = "auto") -> str:
    """A concise market rule for prompts, or empty when the reader chose auto.

    Region is a closed preference value, never arbitrary prompt text. The rule
    steers research toward the reader's market while requiring the source to
    establish market applicability for claims about fitment, standards, recalls
    and availability.
    """
    code = str(region or "auto").strip().upper()
    if code.lower() == "auto":
        return ""
    label = prefs.REGIONS.get(code)
    if not label:
        return ""
    return (
        f"The reader's preferred market is {label} ({code}). Prefer evidence "
        "and search results that apply to this market. For fitment, safety or "
        "regulatory requirements, recalls, prices, stock and availability, use "
        "a source that identifies the relevant market; do not transfer a claim "
        "from another market or assume the product variant is identical. If a "
        "source does not establish market applicability, say it is unconfirmed."
    )
