"""Keep configuration identifiers intact without a category dictionary.

Identifiers come from the product line, never the instructions or sample
reply. Matching is by token: AX-10 does not match AX-100 or AX-10B.
"""

import re


GUIDANCE = (
    "\n\n## Configuration boundaries\n"
    "Treat every part code, revision, year range and market as a separate "
    "configuration. A nearby code or a shared product name does not prove "
    "compatibility or a shared fault. Preserve identifiers exactly. Use a "
    "source only when it supports the requested configuration; an explicit "
    "exclusion overrides a general family statement. When an identifier is "
    "missing or conflicting, say so in assumed and omit claims that depend "
    "on it. Do not infer a missing part from a year alone. Empty lists are "
    "a valid answer when evidence is insufficient.\n"
    "A specification difference is not a failure or a risk. Describe only "
    "a documented fault applicable to the requested configuration.\n"
    "The requested item can be a replacement part, accessory or consumable. "
    "Products it fits or connects to are context, not the research subject. "
    "Do not turn a host product's faults into faults of the item sold.\n"
)


def product_line(task: str) -> str:
    for line in task.splitlines():
        text = line.strip()
        if text and not text.startswith(("#", "```")):
            return text.lstrip("*-> ").strip("`").strip()
    return ""


def codes(task: str) -> set[str]:
    """Mixed letter/number tokens, including hyphenated SKU suffixes."""
    return {word.casefold() for word in re.findall(
        r"[\w]+(?:[-./][\w]+)*", product_line(task))
        if any(c.isalpha() for c in word) and any(c.isdigit() for c in word)}


def contains(text: str, code: str) -> bool:
    return bool(re.search(r"(?<![\w./-])" + re.escape(code) + r"(?![\w./-])",
                          text, re.IGNORECASE))


def anchor_queries(task: str, queries: list[str]) -> list[str]:
    anchors = sorted(codes(task))
    return [query + " " + " ".join(f'"{code}"' for code in anchors
                                    if not contains(query, code))
            if any(not contains(query, code) for code in anchors) else query
            for query in queries]
