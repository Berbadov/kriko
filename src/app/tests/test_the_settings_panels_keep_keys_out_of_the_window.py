"""A key goes to the engine and is never kept in the window.

The engine's rule is that no response contains a key
(`test_the_keys_endpoint_never_returns_a_key`). The window has the mirror rule:
it holds a key only while the reader types it, and it never puts one in
shared state, in a URL, or in a stored setting. Neither side's test sees the
other, so the window's half is held here, on the source.

* The key field is a password field, so it is not shown on screen and a browser
  does not offer to remember it as text.
* The field is cleared after a save, so a key does not stay in memory beside
  the screen it was typed on.
* `useKeys` sends the key in the body of a `PUT` and keeps no state that holds
  one: the engine's reply (the last four characters at most) is all it stores.
* Nothing in the panels writes a key to `localStorage` or into an address.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
SETTINGS_PANEL = (UI / "ui" / "panels" / "Settings.tsx").read_text(encoding="utf-8")
HOOKS = (UI / "engine" / "settings.ts").read_text(encoding="utf-8")


def test_the_key_field_is_a_password_field_and_is_cleared_after_a_save():
    form = SETTINGS_PANEL[SETTINGS_PANEL.index("<form") : SETTINGS_PANEL.index("</form>")]
    assert 'type="password"' in form
    assert 'autoComplete="off"' in form
    submit = SETTINGS_PANEL[SETTINGS_PANEL.index("const submit") :]
    submit = submit[: submit.index("\n  }\n")]
    assert submit.index("await onSave(value)") < submit.index("setValue('')"), (
        "the field is cleared before the save finishes, or never"
    )


def test_the_key_travels_in_a_body_and_not_in_an_address():
    sent = re.findall(r"put<[^>]*>\(\s*'/api/keys'[^)]*\)", HOOKS)
    assert sent and all("values" in call for call in sent), sent
    for call in re.findall(r"(?:get|put|post|del)<[^>]*>\(\s*[`'][^`']*[`']", HOOKS):
        assert "value" not in call.split("(", 1)[1], f"a key in an address: {call}"


def test_no_state_in_the_key_hook_holds_a_key():
    hook = HOOKS[HOOKS.index("export function useKeys") : HOOKS.index("export function useSpent")]
    states = re.findall(r"const \[(\w+), set\w+\] = useState", hook)
    assert states == ["doc", "problem", "tested"], (
        f"useKeys keeps {states}: a new piece of state may be holding a key"
    )


def test_the_panels_store_nothing_in_the_browser():
    for name in ("Settings.tsx", "Agents.tsx"):
        text = (UI / "ui" / "panels" / name).read_text(encoding="utf-8")
        assert "localStorage" not in text and "sessionStorage" not in text, name
    assert "localStorage" not in HOOKS
