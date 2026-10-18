"""Finding a model on Hugging Face, with filters, for the Local panel.

Hugging Face is a public list of model repositories. Only the GGUF ones can go
to Ollama, which pulls them by the name `hf.co/<owner>/<repo>:<quant>`, so the
search asks for those and nothing else. This module reads the list and the file
sizes of one repository, and does nothing more: a download is the same
`model_pull` job as any other, started by the reader's button, and nothing here
runs on its own.

What comes back from the site is text anyone can publish. Only the few fields
the panel shows are kept, each cut to a known shape, and none of it ever
enters a prompt.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from app.localplane import MIN_PARAMETERS_B

_API = "https://huggingface.co/api/models"
TIMEOUT = 10.0
#: A search is read from the web, so the same one inside this many seconds is kept.
CACHE_SECONDS = 600
MAX_LIMIT = 40
#: A reply is cut here so a bad answer cannot fill memory.
MAX_BYTES = 8_000_000

SORTS = {"downloads": "downloads", "likes": "likes", "new": "lastModified"}

#: `owner/repo`, the shape the site allows.
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.\-]{0,95}$")
#: The quantisation in a file name: `Q4_K_M`, `IQ3_XS`, `Q8_0`, `F16`, `BF16`.
_QUANT = re.compile(r"(?<![A-Za-z0-9])((?:IQ|Q)\d(?:_[A-Z0-9]+)*|BF16|F16|F32)(?![A-Za-z0-9])", re.I)
_PART = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)
_LICENSE = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,40}$")

_cache: dict[str, tuple[float, object]] = {}


def valid_repo(repo: str) -> bool:
    return bool(_REPO.match(repo or ""))


def pull_name(repo: str, quant: str) -> str:
    """The name Ollama takes for one quantisation of one repository."""
    return f"hf.co/{repo}:{quant}"


def _read(url: str, opener) -> object:
    now = time.monotonic()
    kept = _cache.get(url)
    if kept and now - kept[0] < CACHE_SECONDS:
        return kept[1]
    request = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "kriko"})
    try:
        with opener(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read(MAX_BYTES).decode("utf-8", "replace"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Could not read Hugging Face: {error}") from error
    if len(_cache) > 64:
        _cache.clear()
    _cache[url] = (now, body)
    return body


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _license_of(tags: list) -> str | None:
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("license:"):
            name = tag[8:]
            return name if _LICENSE.match(name) else None
    return None


def search(
    query: str = "",
    *,
    sort: str = "downloads",
    min_b: float | None = None,
    max_b: float | None = None,
    licence: str = "",
    limit: int = 24,
    opener=urllib.request.urlopen,
) -> list[dict]:
    """GGUF repositories that match, with the filters applied.

    Gated and private repositories are left out, since a download needs a token
    Kriko does not hold. A repository under `MIN_PARAMETERS_B` is left out for
    the reason the Ollama list leaves it out. One whose size the site does not
    report is kept, with `params_b` empty, unless a size filter is set.
    """
    params: list[tuple[str, str]] = [
        ("filter", "gguf"),
        ("pipeline_tag", "text-generation"),
        ("sort", SORTS.get(sort, "downloads")),
        ("direction", "-1"),
        ("limit", str(max(1, min(limit, MAX_LIMIT)) * 2)),
    ]
    if query.strip():
        params.append(("search", query.strip()[:80]))
    if licence and _LICENSE.match(licence):
        params.append(("filter", f"license:{licence}"))
    for field in ("gguf", "downloads", "likes", "tags", "lastModified", "gated", "private"):
        params.append(("expand[]", field))
    body = _read(_API + "?" + urllib.parse.urlencode(params), opener)
    if not isinstance(body, list):
        raise RuntimeError("Hugging Face answered with something Kriko does not read.")

    out: list[dict] = []
    for row in body:
        if not isinstance(row, dict) or not valid_repo(str(row.get("id") or "")):
            continue
        if row.get("gated") or row.get("private"):
            continue
        found_gguf = row.get("gguf")
        gguf: dict = found_gguf if isinstance(found_gguf, dict) else {}
        total = _int(gguf.get("total"))
        params_b = round(total / 1e9, 1) if total else None
        if params_b is not None and params_b < MIN_PARAMETERS_B:
            continue
        if (min_b is not None or max_b is not None) and params_b is None:
            continue
        if min_b is not None and params_b is not None and params_b < min_b:
            continue
        if max_b is not None and params_b is not None and params_b > max_b:
            continue
        found_tags = row.get("tags")
        tags: list = found_tags if isinstance(found_tags, list) else []
        out.append({
            "repo": row["id"],
            "downloads": _int(row.get("downloads")) or 0,
            "likes": _int(row.get("likes")) or 0,
            "params_b": params_b,
            "license": _license_of(tags),
            "updated": str(row.get("lastModified") or "")[:10] or None,
            "context": _int(gguf.get("context_length")),
        })
        if len(out) >= limit:
            break
    return out


def files(repo: str, *, opener=urllib.request.urlopen) -> list[dict]:
    """The quantisations in one repository, with the bytes each one takes.

    A model split into parts is one choice with the parts added up. Files that
    are not weights (vision projectors, imatrix files) are not choices.
    """
    if not valid_repo(repo):
        raise RuntimeError("That is not a Hugging Face repository name.")
    body = _read(f"{_API}/{repo}/tree/main", opener)
    if not isinstance(body, list):
        raise RuntimeError("Hugging Face answered with something Kriko does not read.")
    sizes: dict[str, int] = {}
    for item in body:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        path = str(item.get("path") or "")
        lowered = path.lower()
        if not lowered.endswith(".gguf") or "mmproj" in lowered or "imatrix" in lowered:
            continue
        found = _QUANT.search(_PART.sub(".gguf", path))
        size = _int(item.get("size"))
        if not found or size is None:
            continue
        quant = found.group(1).upper()
        sizes[quant] = sizes.get(quant, 0) + size
    return [{"quant": quant, "bytes": size, "pull": pull_name(repo, quant)} for quant, size in sorted(sizes.items(), key=lambda kv: kv[1])]
