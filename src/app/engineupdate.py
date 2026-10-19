"""Updating the engine without the installer.

An installer lays new files over old ones, and over a running program. That
is what made an update need an uninstall: a stale `kriko-0.2.3.dist-info`
beside the new engine, a mapped executable the copy could not replace, a
version record that said the wrong thing. Each was fixed once, and the next
one is the same kind of bug, because the method is the problem.

The engine is the part that changes most (the chat, the prompts, the research,
the extension it hands out), so it gets its own way in. A release publishes the
engine folder as `kriko-engine-<version>-win64.zip` beside `engine.json`, the
installer and the checksums. Updating:

1. downloads it and checks it against `SHA256SUMS.txt`;
2. unpacks it into a folder of its own, `<engines>/<version>/`, which nothing
   else ever writes to, so nothing is laid over anything;
3. writes `ready` in it, last. A folder without `ready` is half a download.

The desktop shell does the rest (`kriko-ui/src-tauri/src/versions.rs`): at its
next engine start it prefers the newest ready engine that is newer than the one
it carries, and when that engine cannot start it marks it `bad` and starts the
one beside it instead. The window stays open, the installer never runs, and a
broken engine costs a restart, not a reinstall.

The shell and this file agree on the layout, and nothing else.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from app import appupdate

MANIFEST = "engine.json"
READY = "ready"
BAD = "bad"

#: What a release names the engine folder, and the small file that describes it.
_ZIP = re.compile(r"^kriko-engine-(?P<version>[0-9][0-9A-Za-z.\-]*)-win64\.zip$")
MANIFEST_ASSET = "engine.json"

#: An engine folder is a few hundred files and some hundreds of MB. These keep
#: a wrong URL, or a zip that lies about its size, from filling a disk.
MAX_ZIP_BYTES = 1024 * 1024 * 1024
MAX_UNPACKED_BYTES = 3 * 1024 * 1024 * 1024
MAX_FILES = 20000

#: How long an unfinished folder is left alone, in case its update is still running.
_UNFINISHED_GRACE_S = 3600


def sidecar_name() -> str:
    return "kriko-sidecar.exe" if os.name == "nt" else "kriko-sidecar"


def engines_root() -> Path:
    """Where engine folders live. Must equal `versions::engines_root` in the shell."""
    forced = os.environ.get("KRIKO_ENGINES_DIR")
    if forced:
        return Path(forced)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Kriko" / "engines"
    return Path.home() / ".kriko" / "engines"


def shell_version() -> str:
    """The desktop app's own version, told to the engine when it is started. "" without one."""
    return os.environ.get("KRIKO_SHELL_VERSION", "").strip()


def parse_engine(payload: dict) -> dict:
    """The engine asset of one release, or `{}` when it publishes none."""
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in payload.get("assets", [])}
    for name, url in assets.items():
        match = _ZIP.match(name)
        if match and url:
            return {
                "version": match.group("version"),
                "name": name,
                "url": url,
                "manifest_url": assets.get(MANIFEST_ASSET, ""),
                "sums_url": assets.get("SHA256SUMS.txt", ""),
            }
    return {}


def _json(url: str) -> dict:
    with appupdate._open(url, appupdate.API_TIMEOUT) as response:
        loaded = json.loads(response.read(1 << 20).decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def offer(release: dict, current: str, shell: str) -> dict:
    """The engine update to show for a release, or `{}` when only the installer will do.

    It is offered when the release carries an engine that is newer than the one
    running, and the desktop app it would run under is new enough for it. A
    reader with no desktop app (no `shell`) has no way to restart into a staged
    engine, so is offered nothing.
    """
    engine = release.get("engine") or {}
    if not engine or not shell or not appupdate.is_newer(engine["version"], current):
        return {}
    floor = "0"
    if engine.get("manifest_url"):
        try:
            floor = str(_json(engine["manifest_url"]).get("min_shell") or "0")
        except Exception:  # noqa: BLE001 - no manifest is no engine update, not a failed check
            return {}
    if appupdate.version_key(shell) < appupdate.version_key(floor):
        return {}
    return {**engine, "min_shell": floor}


def _fits(zf: zipfile.ZipFile, info: dict, shell: str) -> None:
    """The zip is the engine the release said it was, for the app it would run under."""
    try:
        manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
    except (KeyError, ValueError) as cause:
        raise ValueError(f"the engine download has no {MANIFEST}") from cause
    if manifest.get("version") != info["version"]:
        raise ValueError("the engine download is not the version the release named")
    floor = str(manifest.get("min_shell") or "0")
    if shell and appupdate.version_key(shell) < appupdate.version_key(floor):
        raise ValueError(f"this engine needs Kriko {floor} or newer; use the installer")


def _safe_target(root: Path, name: str) -> Path:
    """Where a zip member goes, and never outside `root`."""
    parts = [p for p in name.replace("\\", "/").split("/") if p]
    if not parts or name.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
        raise ValueError(f"the engine download holds an unsafe path: {name!r}")
    target = root.joinpath(*parts)
    if root.resolve() not in target.resolve().parents and target.resolve() != root.resolve():
        raise ValueError(f"the engine download holds an unsafe path: {name!r}")
    return target


def _unpack(zf: zipfile.ZipFile, into: Path) -> None:
    files = [m for m in zf.infolist() if not m.is_dir()]
    if len(files) > MAX_FILES or sum(m.file_size for m in files) > MAX_UNPACKED_BYTES:
        raise ValueError("the engine download is larger than any Kriko engine")
    for member in files:
        target = _safe_target(into, member.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, 1 << 20)


def download(info: dict, folder: Path) -> Path:
    """Fetch the engine zip named by `offer`, verified against the release checksums."""
    if not info.get("url") or not info.get("sums_url"):
        raise ValueError("this release publishes no checksums, so its engine is not offered")
    with appupdate._open(info["sums_url"], appupdate.API_TIMEOUT) as response:
        wanted = appupdate.parse_sums(response.read(1 << 20).decode("utf-8")).get(info["name"], "")
    if not wanted:
        raise ValueError(f"{info['name']} is not in the release's SHA256SUMS.txt")
    target = folder / info["name"]
    digest = hashlib.sha256()
    read = 0
    with appupdate._open(info["url"], appupdate.DOWNLOAD_TIMEOUT) as response, open(target, "wb") as out:
        while chunk := response.read(1 << 16):
            read += len(chunk)
            if read > MAX_ZIP_BYTES:
                raise ValueError("the engine download is larger than any Kriko engine")
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != wanted:
        target.unlink(missing_ok=True)
        raise ValueError("the download does not match the release checksum; discarded")
    return target


def stage(info: dict, *, root: Path | None = None, shell: str | None = None) -> dict:
    """Download, check and unpack an engine into its own folder. The shell uses it at its next start.

    Nothing is written into an existing engine folder: the new one is built in a
    `.part` folder and renamed into place once it is whole, and `ready` goes in
    last. A failure at any step leaves the engines exactly as they were.
    """
    root = root or engines_root()
    shell = shell_version() if shell is None else shell
    version = info["version"]
    final = root / version
    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="kriko-engine-", dir=root))
    try:
        archive = download(info, scratch)
        part = scratch / "unpacked"
        with zipfile.ZipFile(archive) as zf:
            _fits(zf, info, shell)
            _unpack(zf, part)
        # The zip is the Windows engine; the second name is only for a build run elsewhere.
        if not any((part / name).is_file() for name in (sidecar_name(), "kriko-sidecar.exe")):
            raise ValueError(f"the engine download holds no {sidecar_name()}")
        if final.exists():
            shutil.rmtree(final)
        part.replace(final)
        (final / READY).write_text(version, encoding="utf-8")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"staged": version, "path": str(final)}


def prune(running: str, root: Path | None = None) -> list[str]:
    """Remove engine folders that can never be chosen again; the engine running now stays.

    An older engine than the one running is never started over it, a `bad` one
    is never started at all, and a folder left by an update that stopped halfway
    is nothing. A newer ready engine is the staged update, and stays.
    """
    root = root or engines_root()
    if not root.is_dir():
        return []
    gone = []
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name == running:
            continue
        unfinished = entry.name.startswith("kriko-engine-") or not (entry / READY).exists()
        # An update still being unpacked is not leftover: only the old is.
        if unfinished and time.time() - entry.stat().st_mtime < _UNFINISHED_GRACE_S:
            continue
        stale = (
            unfinished
            or (entry / BAD).exists()
            or appupdate.version_key(entry.name) < appupdate.version_key(running)
        )
        if stale:
            shutil.rmtree(entry, ignore_errors=True)
            gone.append(entry.name)
    return gone


def running_from(root: Path | None = None) -> bool:
    """Whether this process was started from a staged engine rather than the one the app carries."""
    try:
        return (root or engines_root()).resolve() in Path(sys.executable).resolve().parents
    except OSError:
        return False
