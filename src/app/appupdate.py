"""Is there a newer app, and how does it get here?

The knowledge updates on its own clock (`app/packsource.py`); this is the
other one, the app itself. It asks the releases page for the latest release,
compares it with the running version, and, only when the reader asks,
downloads that release's installer into a temporary folder and checks it
against the `SHA256SUMS.txt` published beside it. Installing is the desktop
shell's job (it closes the app, the installer replaces it): this module never
runs an installer.

Three rules, the same as the pack download:

**Verify before offering.** A truncated installer is not a smaller update, it
is a broken install. A file whose digest is missing or wrong is discarded.

**Only https, only what the release named.** The release is remote data.

**Fail quiet.** A reader offline, behind a proxy, or looking at a repository
with no public release gets "could not check" and a working app.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

API_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 600
#: An installer is tens of MB; the cap keeps a wrong URL from filling the disk.
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
USER_AGENT = "kriko-app-updater"

_INSTALLER = re.compile(r"^kriko-(?P<version>[0-9][0-9A-Za-z.\-]*)-x86_64\.msi$")


def _open(url: str, timeout: int):
    if urlparse(url).scheme != "https":
        raise ValueError(f"refusing a non-https update URL: {url!r}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — scheme checked


def version_key(text: str) -> tuple[int, ...]:
    """`1.1.10` sorts after `1.1.9`; anything after a `-` (a pre-release tag) is ignored."""
    core = text.strip().lstrip("vV").split("-", 1)[0]
    parts = []
    for piece in core.split("."):
        digits = re.match(r"\d+", piece)
        parts.append(int(digits.group()) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    if not current or current == "unknown":
        return False
    return version_key(candidate) > version_key(current)


def parse_release(payload: dict) -> dict:
    """The installer and checksum assets of one release, or `{}` if it has no Windows installer."""
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in payload.get("assets", [])}
    for name, url in assets.items():
        match = _INSTALLER.match(name)
        if match and url:
            return {
                "version": match.group("version"),
                "tag": payload.get("tag_name", ""),
                "name": name,
                "url": url,
                "sums_url": assets.get("SHA256SUMS.txt", ""),
                "page": payload.get("html_url", ""),
                "notes": (payload.get("body") or "")[:4000],
            }
    return {}


def latest(api_url: str) -> dict:
    with _open(api_url, API_TIMEOUT) as response:
        payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
    return parse_release(payload)


def check(api_url: str, current: str) -> dict:
    """What the settings screen shows: the running version, the newest, and whether to offer it."""
    try:
        found = latest(api_url)
    except Exception as cause:  # noqa: BLE001 — every failure is the same answer to the reader
        return {"current": current, "newer": False, "error": _plain(cause)}
    if not found:
        return {"current": current, "newer": False, "error": "the latest release has no Windows installer"}
    return {"current": current, "newer": is_newer(found["version"], current), "error": "", **found}


def _plain(cause: Exception) -> str:
    text = str(cause)
    if "404" in text:
        return "no published release found"
    return f"could not check for updates ({text or type(cause).__name__})"


def parse_sums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def download(info: dict, into: Path | None = None) -> Path:
    """Fetch the installer named by `check`, verified against the release checksums."""
    if not info.get("url") or not info.get("sums_url"):
        raise ValueError("this release publishes no checksums, so it is not offered as an update")
    with _open(info["sums_url"], API_TIMEOUT) as response:
        wanted = parse_sums(response.read(1 << 20).decode("utf-8")).get(info["name"], "")
    if not wanted:
        raise ValueError(f"{info['name']} is not in the release's SHA256SUMS.txt")
    folder = into or Path(tempfile.mkdtemp(prefix="kriko-update-"))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / info["name"]
    part = folder / (info["name"] + ".part")
    digest = hashlib.sha256()
    read = 0
    try:
        with _open(info["url"], DOWNLOAD_TIMEOUT) as response, open(part, "wb") as out:
            while chunk := response.read(1 << 16):
                read += len(chunk)
                if read > MAX_INSTALLER_BYTES:
                    raise ValueError("the installer is larger than any Kriko release")
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != wanted:
            raise ValueError("the download does not match the release checksum; discarded")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
    return target
