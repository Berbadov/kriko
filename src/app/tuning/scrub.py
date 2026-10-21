"""No secret in a trace: what a tuning run writes down is scrubbed first.

A tuning ledger keeps questions, answers, fetched page excerpts and the log of
the run that produced them, and the reader may share the folder. Two things
could carry a credential into it: a question the reader typed (a saved chat
that pasted a key) and a log line or URL that echoed one (`?api_key=...`). So
every string that is written passes through here, and the exact value of any
key in the environment is removed wherever it appears.

The patterns are about the *shape* of a credential, never about a provider.
"""

import os
import re

_PATTERNS = (
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"), "[key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[key]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[key]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[key]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]{12,}=*"), "Bearer [token]"),
    (re.compile(r"(?i)([?&](?:key|api_key|apikey|token|access_token|auth|signature|sig)=)[^&\s\"')]+"),
     r"\1[redacted]"),
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|secret|password|passwd|token)"
                r"(\s*[:=]\s*|\"\s*:\s*\")([^\s\"',;&]{6,})"), r"\1\2[redacted]"),
    (re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+"), "[email]"),
)

_NAME = re.compile(r"(?i)(key|token|secret|password|passwd)")
#: Shorter than this is not worth replacing by value: it would mangle prose.
_MIN_SECRET = 8


def _secrets(environ: dict | None = None) -> list[str]:
    source = os.environ if environ is None else environ
    values = {value for name, value in source.items()
              if _NAME.search(name) and isinstance(value, str) and len(value.strip()) >= _MIN_SECRET}
    return sorted(values, key=len, reverse=True)


def scrub(text: str, environ: dict | None = None) -> str:
    """`text` with credentials, e-mail addresses and the environment's own key
    values removed."""
    out = str(text)
    for value in _secrets(environ):
        out = out.replace(value, "[redacted]")
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def scrub_obj(value, environ: dict | None = None):
    """The same, through any JSON-shaped value; keys and non-strings are kept."""
    if isinstance(value, str):
        return scrub(value, environ)
    if isinstance(value, list):
        return [scrub_obj(one, environ) for one in value]
    if isinstance(value, dict):
        return {key: scrub_obj(one, environ) for key, one in value.items()}
    return value
