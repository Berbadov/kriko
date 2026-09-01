"""Fetching packs from wherever they are published.

The engine decides *whether* to update (`kriko.pack.updates`); this decides
*how to get the bytes*, and it lives in `app/` because the engine owns no
network. That split is not ceremony — it is what lets the whole update
decision be tested with dictionaries and no socket.

Three rules the download obeys:

**Verify before installing.** A `.kpack` is a SQLite file that
`packstore.install` ATTACHes. A truncated download is a corrupt database, and
the honest place to notice is before it touches the store — so a candidate that
declares a `sha256` must match it, byte for byte, or the file is discarded.

**Download to a temp file, never over the destination.** The store keeps no
copy of the pack file, but a half-written file in the packs directory looks
exactly like a real one to the next reader.

**Only http(s), and only what the index named.** The index is remote data; a
`file://` URL in it would read the host's disk on the index author's say-so.
"""

import hashlib
import shutil
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from kriko.pack import updates

#: Enough for an index, and small enough that a wrong URL fails fast.
INDEX_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 300
#: A pack is a SQLite file; a few hundred MB would be extraordinary. The cap
#: exists so a wrong URL cannot fill the user's disk before anyone notices.
MAX_PACK_BYTES = 512 * 1024 * 1024

USER_AGENT = "kriko-pack-updater"


def _require_http(url: str) -> None:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"refusing a non-http(s) pack URL: {url!r}")


def _open(url: str, timeout: int):
    _require_http(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — scheme checked


def fetch_index(url: str) -> list[updates.Candidate]:
    with _open(url, INDEX_TIMEOUT) as response:
        text = response.read(4 * 1024 * 1024).decode("utf-8")
    return updates.parse_index(text)


def download(candidate: updates.Candidate, into: Path, on_progress=None) -> Path:
    """Fetch one pack file into `into`, verified. Returns the written path."""
    into.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    read = 0
    handle = tempfile.NamedTemporaryFile(
        dir=into, prefix=f".{candidate.pack_id}-", suffix=".part", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle, _open(candidate.url, DOWNLOAD_TIMEOUT) as response:
            while chunk := response.read(1 << 16):
                read += len(chunk)
                if read > MAX_PACK_BYTES:
                    raise ValueError(
                        f"{candidate.pack_id} exceeded {MAX_PACK_BYTES} bytes; "
                        "refusing to keep downloading"
                    )
                digest.update(chunk)
                handle.write(chunk)
                if on_progress:
                    on_progress(read, candidate.size)
        if candidate.sha256 and digest.hexdigest() != candidate.sha256:
            raise ValueError(
                f"{candidate.pack_id} downloaded with sha256 "
                f"{digest.hexdigest()}, but the index promised {candidate.sha256}"
            )
        destination = into / f"{candidate.pack_id}-{candidate.version}.kpack"
        shutil.move(str(temporary), destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
