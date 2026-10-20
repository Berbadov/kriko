"""One redactor for every record that keeps what was said to or by a model.

The benchmark traces redacted by *value*: every provider key the process holds
is replaced wherever it appears, whatever field it landed in, because a key is
echoed in places nobody predicted (an error body, a URL, a prompt that quoted
its own headers). `agentledger.redact` redacts by *shape* (`Bearer ...`,
`api_key=...`, `sk-...`). Neither is enough alone, and the trace helper lived
inside `app.searchbench`, which the serving path must not import — so a second
copy would have been the next place a rule drifted.

This module is that helper, moved down: `searchbench` now calls it with its
own named keys, the job log's per-call records call it with whatever the
process holds. Three kinds of thing are taken out of a kept text:

* the *value* of any environment variable that looks like a credential;
* anything shaped like a credential (`agentledger.redact`);
* **the reader's own saved words** (`private`): the profile an agent is handed
  about how they buy and use things is the reader's, and a log that repeats it
  in plain text hands it to anyone who is later sent that log.

No category knowledge, no network, and nothing here raises.
"""

import json
import os
import re
from collections.abc import Iterable, Mapping

from app.agentledger import redact as redact_shapes

#: Environment names that hold a credential. The same test `livesearch.scrub`
#: has always used, kept in one place now.
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|AUTH", re.IGNORECASE)

#: A shorter value is more likely to be a word than a key, and replacing every
#: `yes` in a log because some variable is called `AUTH_MODE=yes` would make the
#: log unreadable.
MIN_SECRET_CHARS = 8

MASK = "[REDACTED]"
PRIVATE_MASK = "[saved profile]"


def secret_values(names: Iterable[str] | None = None,
                  env: Mapping[str, str] | None = None) -> list[str]:
    """The credential values this process holds, longest first.

    `names` pins the variables to read (the benchmark names its provider keys);
    without it every variable whose *name* looks like a credential is read.
    """
    source = os.environ if env is None else env
    chosen = (source.keys() if names is None
              else [name for name in names if name in source])
    found = {str(source[name]) for name in chosen
             if (names is not None or SECRET_NAME.search(name))
             and len(str(source[name])) >= (1 if names is not None else MIN_SECRET_CHARS)}
    return sorted(found, key=len, reverse=True)


def _replace(text: str, values: Iterable[str], mask: str) -> str:
    for value in values:
        if not value:
            continue
        text = text.replace(value, mask)
        # The same value as it sits inside a JSON string (quotes, backslashes,
        # non-ASCII escaped), because kept requests are often JSON.
        escaped = json.dumps(value, ensure_ascii=False)[1:-1]
        if escaped != value:
            text = text.replace(escaped, mask)
    return text


def redact_json(value, names: Iterable[str] | None = None,
                env: Mapping[str, str] | None = None) -> str:
    """`value` as JSON with every named secret's value taken out.

    What the benchmark trace has always done; `app.searchbench` calls this.
    """
    return _replace(json.dumps(value, ensure_ascii=False),
                    secret_values(names, env), MASK)


def redact_text(text, *, limit: int | None = None, private: Iterable[str] = (),
                env: Mapping[str, str] | None = None) -> str:
    """A text safe to keep: credentials by value and by shape, the reader's words masked.

    `private` is the reader's saved free text, longest first so a phrase inside
    a longer one does not leave the rest of the longer one behind. Values under
    four characters are ignored (a one-letter preference would mask the page).
    """
    clean = str(text or "")
    clean = _replace(clean, secret_values(None, env), MASK)
    clean = _replace(clean, sorted({str(one).strip() for one in private
                                    if len(str(one).strip()) >= 4},
                                   key=len, reverse=True), PRIVATE_MASK)
    clean = redact_shapes(clean, limit=len(clean) + 1)
    if limit is not None and len(clean) > limit:
        clean = clean[:limit] + f"… (+{len(clean) - limit} chars not kept)"
    return clean
