"""Deciding whether an installed pack is stale — and refusing to guess.

Knowledge changes on a different clock from the application. A pack gains
claims every time research lands; the binary around it changes rarely. So the
interesting update path is not "is there a new Kriko" but "is there a new
version of what Kriko knows", and the store has carried `origin_url`, `version`
and `content_digest` on every pack row since the schema was written.

This module is the decision, not the download. It takes an index someone else
fetched and the rows already installed, and answers what should happen. No
network here on purpose: the engine must stay testable without one, and the
layer that owns HTTP is the interface (`app/web/tasks.py`).

**Two digests, deliberately.** `content_digest` is computed over sorted row ids
— it identifies *what a pack knows*, and is stable across rebuilds that change
nothing but a timestamp. `sha256` is over the file's bytes, and is the only
thing that can verify a download arrived intact. Comparing the first decides
whether to fetch; checking the second decides whether to trust what arrived.
Using one for the other's job is how a corrupted download gets installed, or a
byte-identical rebuild gets treated as new knowledge.
"""

import json
from dataclasses import dataclass

from kriko.pack.version import key as version_key

#: What the decision was, most actionable first.
AVAILABLE = "available"
UP_TO_DATE = "up_to_date"
UNKNOWN = "unknown"
REFUSED = "refused"


@dataclass(frozen=True)
class Candidate:
    """One pack, as offered by an index."""

    pack_id: str
    version: str
    url: str
    content_digest: str = ""
    sha256: str = ""
    size: int = 0
    published_at: str = ""
    name: str = ""


@dataclass(frozen=True)
class Decision:
    pack_id: str
    state: str
    reason: str
    installed_version: str = ""
    offered_version: str = ""
    candidate: Candidate | None = None

    @property
    def actionable(self) -> bool:
        return self.state == AVAILABLE


def parse_index(text: str) -> list[Candidate]:
    """Read a `packs.json`.

    Shape: `{"packs": [{pack_id, version, url, content_digest, sha256, ...}]}`.
    A list at the top level is accepted too — an index with one pack in it is a
    thing people will hand-write, and failing on the obvious spelling of it
    would be pedantry.
    """
    data = json.loads(text)
    rows = data.get("packs", []) if isinstance(data, dict) else data
    candidates = []
    for row in rows:
        if not row.get("pack_id") or not row.get("url"):
            # A row that names no pack or no file cannot be acted on. Skipped
            # rather than raised: one malformed entry must not hide the rest of
            # a working index.
            continue
        candidates.append(
            Candidate(
                pack_id=str(row["pack_id"]),
                version=str(row.get("version", "")),
                url=str(row["url"]),
                content_digest=str(row.get("content_digest", "")),
                sha256=str(row.get("sha256", "")),
                size=_size_bytes(row.get("size")),
                published_at=str(row.get("published_at", "")),
                name=str(row.get("name", "")),
            )
        )
    return candidates


def _parts(version: str) -> tuple:
    """Sortable form of a version string. One implementation, in `pack/version`.

    This module and `store/packstore.py` each grew their own, and they disagreed
    about `"1.2.3a"` against `"1.2.30"` — the index and the installer could call
    the same artifact newer and older in the same run. `version.key` is now the
    only ordering, so `decide` and `install`'s downgrade guard cannot diverge.
    """
    return version_key(version)


def _size_bytes(value) -> int:
    """A declared size in bytes, or 0 when it cannot be read.

    `int(row.get("size") or 0)` used to raise on `"1.2 MB"` — a hand-written
    index row — and one such row killed the whole index, which is the outcome
    the loop above goes out of its way to avoid for a row that names no pack.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().lower().replace(",", "")
    if not text:
        return 0
    scale = 1
    for suffix, factor in (("gib", 1024 ** 3), ("gb", 1000 ** 3),
                           ("mib", 1024 ** 2), ("mb", 1000 ** 2),
                           ("kib", 1024), ("kb", 1000), ("b", 1)):
        if text.endswith(suffix):
            text, scale = text[: -len(suffix)].strip(), factor
            break
    try:
        return int(float(text) * scale)
    except ValueError:
        return 0


def comparable(version: str) -> bool:
    """Can this version be ordered at all? An empty or blank one cannot."""
    return bool(version.strip())


def decide(installed, candidate: Candidate | None) -> Decision:
    """What should happen to one installed pack, given what is on offer.

    `installed` is a row (or mapping) from the `packs` table.
    """
    pack_id = installed["pack_id"]
    current = (installed["version"] or "").strip()
    digest = (installed["content_digest"] or "").strip()

    if candidate is None:
        return Decision(
            pack_id, UNKNOWN, "no index entry for this pack", current
        )
    offered = candidate.version.strip()

    if not comparable(current) or not comparable(offered):
        return Decision(
            pack_id,
            UNKNOWN,
            "one of the versions is blank, so they cannot be ordered",
            current,
            offered,
            candidate,
        )

    if offered == current:
        # Same version, different knowledge. packstore.install refuses this and
        # so does this: a version is an immutable identifier, and silently
        # accepting a republished one means two machines can both believe they
        # run 1.2.0 and disagree about what it says.
        if candidate.content_digest and digest and candidate.content_digest != digest:
            return Decision(
                pack_id,
                REFUSED,
                f"version {offered} is offered with a different content digest "
                f"than the one installed — a version may not be republished",
                current,
                offered,
                candidate,
            )
        return Decision(pack_id, UP_TO_DATE, "newest version installed",
                        current, offered, candidate)

    if _parts(offered) < _parts(current):
        return Decision(
            pack_id,
            UP_TO_DATE,
            f"the index offers {offered}, older than the installed {current}",
            current,
            offered,
            candidate,
        )

    if candidate.content_digest and candidate.content_digest == digest:
        # Renumbered, same knowledge. Downloading it would churn a revision for
        # no change in what the pack can answer.
        return Decision(
            pack_id,
            UP_TO_DATE,
            f"{offered} carries the same content digest as the installed "
            f"{current} — nothing new to learn",
            current,
            offered,
            candidate,
        )

    return Decision(pack_id, AVAILABLE, f"{current} → {offered}",
                    current, offered, candidate)


def plan(installed_rows, candidates) -> list[Decision]:
    """Decide for every installed pack. Order follows the installed rows."""
    by_id = {c.pack_id: c for c in candidates}
    return [decide(row, by_id.get(row["pack_id"])) for row in installed_rows]
