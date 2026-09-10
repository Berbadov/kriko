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
    # Which languages this pack's own text is written in, primary first, as
    # BCP-47 codes. Not decoration: `research/templates.yaml` ships queries in
    # the language the sources are written in, and until 2026-09-10 nothing
    # anywhere declared what that was — so a brief handed an agent seven
    # queries in two languages and told it neither. Empty means the pack never
    # said, which is treated as `("en",)` and reported by the contract test
    # rather than guessed at.
    languages: tuple[str, ...] = ()
    # Which markets its claims are about, as region codes. A pack may serve a
    # market whose language it does not ship queries in, and vice versa —
    # "recalls in the EU" is not the same fact as "forums in German".
    markets: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict)

    @property
    def primary_language(self) -> str:
        """The language a template that names none is written in."""
        return self.languages[0] if self.languages else "en"

    @property
    def vocabulary_dir(self) -> Path:
        return self.root / "vocabulary"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"


def _codes(value, path: Path, key: str) -> tuple[str, ...]:
    """A list of short codes, from either a list or a single string.

    Tolerant of `market = "TR"` as well as `markets = ["TR", "EU"]` because
    both are what an author writes, and rejecting one of them would be a
    contract that fails on a typo rather than on a mistake. Order is kept: the
    first language is the primary one.
    """
    if value is None or value == "":
        return ()
    items = [value] if isinstance(value, str) else list(value)
    out: list[str] = []
    for item in items:
        code = str(item).strip()
        if not code:
            continue
        if len(code) > 16 or not code.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"{path}: [pack] {key} must be short codes like \"en\" or "
                f"\"pt-BR\", not {code!r}"
            )
        if code not in out:
            out.append(code)
    return tuple(out)


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

    languages = _codes(pack.get("languages"), path, "languages")
    markets = _codes(pack.get("markets") or pack.get("market"), path, "markets")

    return Manifest(
        root=root,
        pack_id=pack["id"],
        name=pack["name"],
        version=str(pack["version"]),
        publisher=pack.get("publisher", ""),
        license=pack.get("license", ""),
        origin_url=pack.get("origin", ""),
        identity_keys=identity,
        languages=languages,
        markets=markets,
        raw=raw,
    )
