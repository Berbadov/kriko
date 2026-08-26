"""`pack.toml` — a pack's identity and its rules for what makes a subject distinct.

A pack is authored as a directory and shipped as a single file. The directory is
what a reviewer reads and `git diff` shows; the file is what installs in one
command. This module reads the directory half.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Manifest:
    root: Path
    pack_id: str
    name: str
    version: str
    publisher: str = ""
    license: str = ""
    origin_url: str = ""
    # Which attribute keys form a subject's identity, per subject kind. This is
    # the pack's most consequential declaration: it decides what counts as "the
    # same product" and therefore which rows merge with another pack's.
    identity_keys: dict[str, list[str]] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def vocabulary_dir(self) -> Path:
        return self.root / "vocabulary"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"


def load(root) -> Manifest:
    root = Path(root)
    path = root / "pack.toml"
    if not path.exists():
        raise FileNotFoundError(f"no pack.toml in {root}")

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    pack = raw.get("pack", {})

    for required in ("id", "name", "version"):
        if not pack.get(required):
            raise ValueError(f"{path}: [pack] is missing required key {required!r}")

    identity = {k: list(v) for k, v in (raw.get("identity") or {}).items() if v}
    if not identity:
        raise ValueError(
            f"{path}: [identity] must declare at least one subject kind and its "
            "identity attribute keys — without them every subject of a kind "
            "would hash to the same id"
        )

    return Manifest(
        root=root,
        pack_id=pack["id"],
        name=pack["name"],
        version=str(pack["version"]),
        publisher=pack.get("publisher", ""),
        license=pack.get("license", ""),
        origin_url=pack.get("origin", ""),
        identity_keys=identity,
        raw=raw,
    )
