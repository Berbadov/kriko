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
                size=int(row.get("size") or 0),
                published_at=str(row.get("published_at", "")),
                name=str(row.get("name", "")),
            )
        )
    return candidates


def _parts(version: str) -> tuple:
    """Sortable form of a version string.

    Numeric segments compare as numbers so 0.10.0 beats 0.9.0, and anything
    non-numeric compares as text. Not a full semver implementation — this needs
    to order two strings, not to adjudicate build metadata — but it must never
    claim an ordering it cannot support, which is what `comparable` is for.
    """
    out = []
    for chunk in version.replace("-", ".").split("."):
        out.append((0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk))
    return tuple(out)


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
