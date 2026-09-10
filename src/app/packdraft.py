"""A pack an agent can author, in a place it cannot escape.

Until now an agent's write surface was three tools — `submit_findings`,
`install_pack`, `set_pack_enabled` — and the first of those only adds claims to
a subject a pack already declares. The reader, meanwhile, could press one
button and get a whole contract-passing pack directory (`POST
/api/packs/scaffold`). So the one job that most wants an agent — reading a
category nobody has modelled yet and writing down its identity keys, its
vocabulary, its bar and its searches — was the one job an agent could not do.
That is B96, and the reader's words were "the pack building must be guided with
agents".

**The whole design is the boundary, so it is stated before the code.** Letting
an agent write files is the single most dangerous thing in this repo, and every
line below exists to make the blast radius a directory:

1. **One directory.** Everything is written under `~/.kriko/drafts/<slug>/`.
   The slug is derived from the pack id, not taken from the caller, and every
   path is resolved and re-checked against that root — a `..`, a symlink or an
   absolute path fails rather than being cleaned up and obeyed.
2. **A fixed set of names.** `WRITABLE` is the list of files a draft may hold.
   `build.py`, `coverage.py` and `pipeline/` are absent on purpose: a pack may
   ship Python, and a pack an *agent* wrote may not, because installing it
   would mean running code the reader never read. This is the same door
   `docs/PACK_CONTRACT.md` keeps shut for adapters, one layer further out.
3. **Nothing is installed.** A draft is files and, on request, a `.kpack`
   beside them. Reaching the store is a separate press by the reader, on a
   screen that lists what the agent wrote. An agent that also calls
   `install_pack` is doing something the reader can see and undo, and the
   drafts list is where they see it.
4. **Sizes are capped**, because an agent in a loop is a disk-filling agent.

None of this is in `kriko/` — the engine writes packs (`kriko.pack.scaffold`)
but owns no policy about who may ask it to. This module is that policy, and it
belongs to the interface that exposes the tools.
"""

from dataclasses import dataclass
from pathlib import Path

from kriko.pack.build import build
from kriko.pack.manifest import load
from kriko.pack.scaffold import scaffold

#: What a drafted pack may contain. Suffix-checked as well as name-checked:
#: `data/*.yaml` is a directory an author fills with rows, and every one of
#: them is data by extension. Nothing here can be executed by installing it.
WRITABLE_FILES = (
    "README.md",
    "pack.toml",
    "research/principle.md",
    "research/templates.yaml",
    "research/skill.md",
)

#: Directories a draft may add files to, and the only suffix allowed in them.
WRITABLE_DIRS = (
    ("data", ".yaml"),
    ("vocabulary", ".yaml"),
    ("trust", ".yaml"),
    ("adapters", ".yaml"),
)

#: One file, and one draft. Generous for prose, ruinous for nothing.
MAX_BYTES = 512 * 1024
MAX_FILES = 200


class DraftRefused(ValueError):
    """A write that the boundary above turned away, with the reason."""


@dataclass(frozen=True)
class Draft:
    slug: str
    root: Path

    def files(self) -> list[str]:
        return sorted(
            str(path.relative_to(self.root)).replace("\\", "/")
            for path in self.root.rglob("*")  # any-order: sorted() above
            if path.is_file()
        )

    def artifact(self) -> Path | None:
        found = sorted(self.root.parent.glob(f"{self.slug}.kpack"))
        return found[0] if found else None


def slug_for(pack_id: str) -> str:
    """A directory name from a pack id, derived rather than accepted.

    The caller never names the directory: an agent that could would eventually
    name one `../../.claude`. Everything outside a small alphabet becomes a
    dash, and an id that reduces to nothing is refused rather than defaulted.
    """
    kept = [
        char if (char.isalnum() or char in "-_") else "-"
        for char in (pack_id or "").strip().lower()
    ]
    slug = "".join(kept).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if not slug or slug in {".", ".."} or len(slug) > 80:
        raise DraftRefused(
            f"pack_id {pack_id!r} does not reduce to a usable directory name"
        )
    return slug


def drafts_root(store_path) -> Path:
    """`~/.kriko/drafts`, derived from wherever the store is.

    Same trick as `mcp_server._app_state_path`: the two live in one directory
    by construction, so a test pointing the store at a temporary path gets
    temporary drafts without knowing this exists.
    """
    return Path(store_path).expanduser().parent / "drafts"


def _resolved(root: Path, relative: str) -> Path:
    """The path a relative name means, or a refusal.

    Both halves matter. The name has to be one `WRITABLE` allows, *and* the
    resolved path has to still be inside the root — the first check stops a
    wrong file, the second stops a right-looking name that resolves elsewhere
    through a symlink or a Windows short name.
    """
    name = (relative or "").strip().replace("\\", "/").lstrip("/")
    if not name or ".." in name.split("/"):
        raise DraftRefused(f"{relative!r} is not a path inside the draft")
    if name not in WRITABLE_FILES:
        head, _, tail = name.partition("/")
        allowed = dict(WRITABLE_DIRS).get(head)
        if not allowed or not tail or "/" in tail or not tail.endswith(allowed):
            raise DraftRefused(
                f"{name!r} is not a file a drafted pack may hold. Allowed: "
                + ", ".join(WRITABLE_FILES)
                + ", and "
                + ", ".join(f"{d}/*{s}" for d, s in WRITABLE_DIRS)
            )
    target = (root / name).resolve()
    if root.resolve() not in target.parents:
        raise DraftRefused(f"{name!r} resolves outside the draft directory")
    return target


def create(
    store_path,
    *,
    pack_id: str,
    name: str,
    identity: dict,
    version: str = "0.1.0",
) -> Draft:
    """Scaffold a draft. Refuses to write over one that already exists.

    The engine's own scaffold does the writing, so a drafted pack starts at
    exactly the floor `packs/drill/` sits at and the contract test already
    covers — an agent authoring a pack is editing rows, not inventing a layout.
    """
    slug = slug_for(pack_id)
    root = drafts_root(store_path) / slug
    root.parent.mkdir(parents=True, exist_ok=True)
    scaffold(root, pack_id=pack_id, name=name, identity=identity, version=version)
    return Draft(slug=slug, root=root)


def write(store_path, *, slug: str, path: str, text: str) -> str:
    """Replace one file in one draft. Returns the relative path written."""
    draft = open_draft(store_path, slug)
    target = _resolved(draft.root, path)
    body = text if isinstance(text, str) else str(text)
    if len(body.encode("utf-8")) > MAX_BYTES:
        raise DraftRefused(
            f"{path!r} is larger than {MAX_BYTES // 1024} KiB — a pack's rows "
            f"belong in several files under data/, not in one"
        )
    if not target.exists() and len(draft.files()) >= MAX_FILES:
        raise DraftRefused(f"a draft holds at most {MAX_FILES} files")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return str(target.relative_to(draft.root)).replace("\\", "/")


def open_draft(store_path, slug: str) -> Draft:
    wanted = slug_for(slug)
    root = drafts_root(store_path) / wanted
    if not root.is_dir():
        raise DraftRefused(f"no draft named {wanted!r}")
    return Draft(slug=wanted, root=root)


def listing(store_path) -> list[dict]:
    """Every draft, with enough to decide whether to install it.

    A draft that no longer loads is listed with its error rather than hidden:
    the reader pressing Install needs to know it will fail, and the agent that
    wrote it needs to be told which edit broke it.
    """
    root = drafts_root(store_path)
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        row = {
            "slug": child.name,
            "root": str(child),
            "files": Draft(child.name, child).files(),
            "artifact": None,
            "pack_id": "",
            "name": "",
            "version": "",
            "error": "",
        }
        artifact = Draft(child.name, child).artifact()
        row["artifact"] = str(artifact) if artifact else None
        try:
            manifest = load(child)
        except Exception as exc:  # noqa: BLE001 — reported, not raised
            row["error"] = str(exc)
        else:
            row["pack_id"] = manifest.pack_id
            row["name"] = manifest.name
            row["version"] = manifest.version
        out.append(row)
    return out


def build_artifact(store_path, slug: str) -> Path:
    """Build the draft into a `.kpack` beside its directory. Installs nothing.

    Separate from installing on purpose (see the module docstring, rule 3): a
    build is how an agent finds out its rows load, and it costs the reader's
    store nothing if they do not.
    """
    draft = open_draft(store_path, slug)
    out = draft.root.parent / f"{draft.slug}.kpack"
    build(draft.root, out)
    return out
