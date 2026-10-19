"""One ordering for pack versions, because there were two and they disagreed.

`updates.decide` decides whether an index offers something newer; `packstore`
refuses a downgrade at install time. Each carried its own comparator, and for
`"1.2.3a"` against `"1.2.30"` they returned opposite answers — so in one run the
index could call an artifact newer while the installer called it older. A pack
index and an installer disagreeing about "newer" is not a style problem.

Not semver: packs are not required to use it, and a full implementation would
have to adjudicate build metadata no pack ships. What is required is that two
dotted version strings order *somehow*, the same way in every caller, without
raising on a suffix.
"""


def key(version: str) -> tuple:
    """A dotted version as something sortable.

    Digits compare as numbers, so `0.10.0` beats `0.9.0`. A segment keeps its
    leading number and then its remaining text, so `3a` sorts above `3` and
    below `30` — a re-release of the third segment, not a twentieth-century one.
    A segment with no leading digit sorts after every numbered segment in that
    position, which keeps `v1.2` behind `1.2`.
    """
    out = []
    for piece in str(version).split("."):
        digits = ""
        for character in piece:
            if not character.isdigit():
                break
            digits += character
        if digits:
            out.append((0, int(digits), piece[len(digits):]))
        else:
            out.append((1, 0, piece))
    return tuple(out)
