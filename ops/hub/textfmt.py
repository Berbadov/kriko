"""Pure formatting and identifier validation for the hub.

Extracted from web.py: nothing here reads request state, module-level
configuration, or the filesystem, so it is testable on its own and web.py
is that much shorter. The two charsets live here rather than beside the
agent code because both web.py and hub.agents validate against them.
"""

from __future__ import annotations

import json
import re
import time

from fastapi import HTTPException

# Catalog-shaped identifiers only. make/model reach a subprocess argv, so
# anything with a path separator, a space, or a shell metacharacter is refused
# outright rather than escaped — there is no legitimate model key that needs one.
_SAFE_NAME = re.compile(r"[a-z0-9_]{1,40}")

# An LLM model id also reaches argv, so it gets the same treatment as make and
# model — a slightly wider charset because provider ids carry `/`, `.` and `-`.
_SAFE_MODEL = re.compile(r"[A-Za-z0-9_./:-]{1,80}")


def _split_key(key: str) -> tuple[str, str]:
    """'renault_megane_4' -> ('renault', 'megane_4'), validated."""
    make, _, model = key.partition("_")
    if not _SAFE_NAME.fullmatch(make) or not _SAFE_NAME.fullmatch(model or ""):
        raise HTTPException(400, f"malformed model key: {key!r}")
    return make, model



def _brief(obj, limit: int = 100) -> str:
    """Compact one-line hint of a tool's input/output, for the progress view."""
    try:
        s = json.dumps(obj, ensure_ascii=False) if obj is not None else ""
    except (TypeError, ValueError):
        s = str(obj)
    s = " ".join(s.split())
    return s[:limit] + ("…" if len(s) > limit else "")


def _fmt_opencode_event(line: str) -> str | None:
    """Render one `opencode run --format json` event as a readable progress
    line, so the browser shows each tool call and answer the moment it
    happens instead of a silent pane. Returns None for events with nothing
    worth showing (non-JSON lines are never fed here)."""
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    etype, part = ev.get("type", ""), ev.get("part") or {}

    if etype == "text":
        return part.get("text") or None
    if etype == "step_start":
        return "· model working…"
    if etype == "step_finish":
        tok = (part.get("tokens") or {}).get("total")
        cost = part.get("cost")
        bits = [f"{tok} tok" for tok in (tok,) if tok is not None]
        try:
            bits.append(f"${float(cost):.4f}")
        except (TypeError, ValueError):
            pass
        return "✓ step done" + (" · " + " · ".join(bits) if bits else "")
    if etype in ("tool_use", "tool_use_permission"):
        tool = part.get("tool") or part.get("name") or "tool"
        state = part.get("state") or {}
        status = state.get("status") or etype.rsplit("_", 1)[-1]
        if status in ("error", "rejected"):
            return f"✗ {tool} failed — {_brief(state.get('error'), 140)}"
        if status == "running":
            return f"→ {tool} {_brief(state.get('input'))}".rstrip()
        out = state.get("output")
        # completed: hint at the result — parsed JSON gets compacted, text
        # output shows its first meaningful line
        hint = ""
        try:
            parsed = json.loads(out) if isinstance(out, str) else None
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            hint = _brief(parsed, 80)
        elif out:
            hint = next((l.strip() for l in str(out).splitlines() if l.strip()), "")
        return f"✓ {tool}" + (f" — {hint[:80]}" if hint else "")
    return None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
