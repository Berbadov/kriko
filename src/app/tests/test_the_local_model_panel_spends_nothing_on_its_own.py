"""The Local model panel downloads and deletes only when the reader presses a button.

A model is gigabytes of bandwidth and disk, and removing one is a re-download.
So reading the panel is free of side effects: the public library is fetched
from the web only when the reader asks for it, a download starts only from a
button or the Get form, and a removal asks first. These hold on the source,
because the engine cannot tell a press from a mount.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
PANEL = (UI / "ui" / "panels" / "Local.tsx").read_text(encoding="utf-8")
SECTION = (UI / "ui" / "settings" / "LocalAI.tsx").read_text(encoding="utf-8")
HOOK = (UI / "engine" / "local.ts").read_text(encoding="utf-8")


def test_the_library_is_read_only_when_the_reader_asks():
    effects = re.findall(r"useEffect\(\(\) => \{(.*?)\n  \}, \[", HOOK, re.S)
    assert effects, "no effects found, so this test checks nothing"
    for body in effects:
        assert "openLibrary" not in body and "available=true" not in body
    assert "onClick={() => void local.openLibrary()}" in PANEL


def test_a_download_starts_only_from_a_press_or_a_submitted_form():
    # The model pieces and the Local AI section: the section's own downloads
    # (the recommended model) are presses too.
    calls = re.findall(r"startPull\(", PANEL) + re.findall(r"startPull\(", SECTION)
    assert len(calls) == 6, "a new caller of startPull needs a look: is it a press?"
    for text in (PANEL, SECTION):
        for call in re.finditer(r"startPull\(", text):
            before = text[max(0, call.start() - 260) : call.start()]
            assert "onClick" in before or "onSubmit" in before or "onGet" in before, before


def test_nothing_is_asked_of_the_model_or_the_library_on_mount():
    # Sending a question is a press on Send, and the hook runs it only through `ask`.
    assert SECTION.count("trial.ask(") == 1
    before = SECTION[: SECTION.index("trial.ask(")]
    assert "const send = () =>" in before[-200:]
    trial = HOOK[HOOK.index("export function useTryLocal") :]
    assert "useEffect(() => {\n    alive.current = true" in trial
    assert trial.count("useEffect(") == 1, "the try hook has no effect that could ask"
    assert "'/api/local-models/try'" in trial


def test_a_removal_asks_before_it_reaches_the_engine():
    row = PANEL[PANEL.index("function ModelRow") :]
    assert "onClick={() => setAsking(true)}" in row
    assert row.count("onRemove()") == 1
    # The only call sits in the branch that is drawn once the reader has been asked.
    assert row.index("{asking ? (") < row.index("onRemove()") < row.index(") : (")


def test_the_engine_is_asked_for_removal_by_name_through_ollama_only():
    assert HOOK.count("'/api/local-models/remove', { runtime: 'ollama', model }") == 1
