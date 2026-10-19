"""Local data snapshots. Restores are staged and applied before database startup.

Provider key files and the process environment are never included. Each SQLite
file is copied with SQLite's backup API so live WAL contents are included.
"""

import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MEMBERS = {"app.sqlite", "knowledge.sqlite", "snapshot.json"}


def _copy_database(source: Path, destination: Path) -> None:
    original = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    copied = sqlite3.connect(str(destination))
    try:
        original.backup(copied)
    finally:
        original.close()
        copied.close()


def _make_room(previous: Path) -> None:
    """Before a new `.before-restore` is written, keep the one already there as `.prev`.

    The safety copy must hold the state just before the restore now running. It
    used to be written only when none existed, so a second restore left the
    first one's copy in place and the work done between the two was in neither.
    One older generation is kept, not every one: these are whole databases.
    """
    if not previous.exists():
        return
    older = previous.with_name(previous.name + ".prev")
    if previous.is_dir():
        if older.exists():
            shutil.rmtree(older)
    else:
        older.unlink(missing_ok=True)
    os.replace(previous, older)


def _draft_member(name: str) -> bool:
    path = Path(name)
    return (not path.is_absolute() and len(path.parts) >= 3 and path.parts[0] == "drafts"
            and all(part not in {"..", "."} for part in path.parts)
            and "\\" not in name and ":" not in name
            and path.suffix.lower() in {".toml", ".yaml", ".yml", ".json", ".md", ".kpack"})


def export(settings) -> bytes:
    output = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="kriko-snapshot-") as directory:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, path in (("app.sqlite", settings.app_state_path), ("knowledge.sqlite", settings.store_path)):
                if not Path(path).exists():
                    continue
                _copy_database(Path(path), Path(directory) / name)
                archive.write(Path(directory) / name, name)
            drafts = Path(settings.store_path).parent / "drafts"
            if drafts.exists():
                for path in sorted(drafts.rglob("*")):
                    name = "drafts/" + path.relative_to(drafts).as_posix()
                    if path.is_file() and not path.is_symlink() and _draft_member(name):
                        archive.write(path, name)
            archive.writestr("snapshot.json", json.dumps({
                "format": 1, "created_at": datetime.now(UTC).isoformat(), "keys_included": False,
                "drafts_included": True,
                "contents": "Saved checks, conversations, settings, installed catalog revisions and data-only catalog drafts. Provider key files are excluded."}))
    if output.tell() > MAX_ARCHIVE:
        raise ValueError("This snapshot exceeds the 32 MB transfer limit. Copy the data folder while Kriko is stopped.")
    return output.getvalue()


def stage(settings, raw: bytes) -> dict:
    if len(raw) > MAX_ARCHIVE:
        raise ValueError("Choose a snapshot up to 32 MB.")
    folder = settings.app_state_path.parent / "restore-pending"
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="restore-check-", dir=folder.parent) as directory:
        checked = Path(directory)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (any(name not in MEMBERS and not _draft_member(name) for name in names) or len(names) != len(set(names))
                    or not {"app.sqlite", "snapshot.json"} <= set(names)
                    or sum(entry.file_size for entry in entries) > MAX_EXPANDED):
                raise ValueError("This is not a supported Kriko snapshot.")
            for entry in entries:
                if entry.flag_bits & 1:
                    raise ValueError("Encrypted archives are not supported.")
                target = checked / entry.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry))
        metadata = json.loads((checked / "snapshot.json").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("format") != 1:
            raise ValueError("This snapshot uses an unsupported format.")
        for name in ("app.sqlite", "knowledge.sqlite"):
            path = checked / name
            if not path.exists():
                continue
            conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("The snapshot contains a damaged database.")
                required = "lookups" if name == "app.sqlite" else "subjects"
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (required,)).fetchone():
                    raise ValueError("The snapshot contains an unexpected database.")
            finally:
                conn.close()
        if folder.exists():
            raise ValueError("A restore is already staged. Restart Kriko to complete it before choosing another snapshot.")
        shutil.copytree(checked, folder)
    return {"restart_required": True, "snapshot": metadata}


def apply_pending(settings) -> bool:
    """Called before any app/store connections exist in the new engine process."""
    folder = settings.app_state_path.parent / "restore-pending"
    if not (folder / "snapshot.json").exists():
        return False
    for name, destination in (("app.sqlite", settings.app_state_path), ("knowledge.sqlite", settings.store_path)):
        source = folder / name
        if not source.exists():
            continue
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        previous = destination.with_suffix(destination.suffix + ".before-restore")
        if destination.exists():
            _make_room(previous)
            _copy_database(destination, previous)
        replacement = destination.with_suffix(destination.suffix + ".restoring")
        shutil.copy2(source, replacement)
        for suffix in ("-wal", "-shm"):
            Path(str(destination) + suffix).unlink(missing_ok=True)
        os.replace(replacement, destination)
    metadata = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    if metadata.get("drafts_included") or (folder / "drafts").exists():
        target = Path(settings.store_path).parent / "drafts"
        previous = target.with_name("drafts.before-restore")
        replacement = target.with_name("drafts.restoring")
        if replacement.exists():
            shutil.rmtree(replacement)
        if (folder / "drafts").exists():
            shutil.copytree(folder / "drafts", replacement)
        else:
            replacement.mkdir(parents=True)
        if target.exists():
            _make_room(previous)
            shutil.copytree(target, previous)
        if target.exists():
            shutil.rmtree(target)
        os.replace(replacement, target)
    shutil.rmtree(folder)
    return True
