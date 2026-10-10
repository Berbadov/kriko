"""The three things a reader asked for, each held by the failure it fixes.

    i can only use claude code not antigravity … I need opencode and Mistral
    Vibe Code as well as working antigravity to do cheap tests; I dont want to
    burn claude code tokens on it. The scaling is also important; I dont want
    to my agent to search 30 sources, maybe iwant 3

Three separate defects, and every one of them was invisible from inside the
app:

* **Antigravity ran and reported nothing.** Headless, `agy` allows
  `search_web` unasked and auto-denies `read_url_content`, because print mode
  cannot answer a permission prompt. So a run searched six times, tried to
  read its first page, was refused, and exited **0** with an empty reply after
  spending 80k tokens of the reader's quota.
* **Mistral Vibe was installed and never driven**, carrying an "unverified"
  reason that had stopped being true the moment somebody ran it.
* **The depth dial reached nothing.** `app/scale.py` had four presets and a
  cost estimate for each; the harness plane never learned the number, so Quick
  and Deep sent the same prompt and differed only in how many of the findings
  were *kept* afterwards.

The tests below are written against the shapes the real CLIs produced, caught
while fixing each one. None of them spawns a CLI.
"""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from app import packauthor
from app.providers import harness as harness_mod
from app.providers.harness import HarnessResearcher


def _one(ident: str):
    from app.tests.harness_fixtures import row
    return row(ident)


# ── the depth dial, all the way down ─────────────────────────────────────────


def test_a_budget_is_stated_to_the_agent_before_it_spends_anything():
    """The ceiling is in the prompt, not only in the bookkeeping afterwards.

    Truncating the reply — all that `raw[: max_documents * 8]` ever did —
    saves the reader nothing: by then thirty searches have run on their
    subscription and only the arithmetic is smaller.
    """
    said = harness_mod.budget_clause(3)
    assert "3 source" in said
    # A ceiling with no permission to stop early is an instruction to pad, and
    # a run that pads reports findings it did not read.
    assert "stop when you reach" in said.lower()
    # And it must never read as "finding nothing is fine".
    assert "report what you have" in said.lower()


def test_no_budget_says_nothing_rather_than_saying_zero():
    """Every caller before the dial existed passes nothing and must be
    unchanged by its arrival — a prompt that gained "read at most 0 pages"
    would be a plane that stopped working on the CLI path."""
    assert harness_mod.budget_clause(0) == ""


def test_the_dial_reaches_the_cli_that_can_enforce_it(monkeypatch):
    """A ceiling the CLI itself applies is the only one that saves money.

    `vibe` is the one here that stops itself on a dollar figure and a turn
    count, both documented as applying only in the programmatic mode this
    plane runs in.
    """
    monkeypatch.setattr(harness_mod, "locate", lambda one: f"/usr/bin/{one.executable}")
    monkeypatch.setattr(
        harness_mod, "declared",
        lambda _: frozenset({"--output", "--agent", "--enabled-tools", "--prompt",
                             "--trust", "--max-price", "--max-turns"}),
    )
    vector = harness_mod.command_for(_one("mistral-vibe"),
                                     max_documents=3, budget_usd=0.5)
    assert "--max-price" in vector and "0.50" in vector
    # Turns are generous per source on purpose: a run killed one turn short of
    # its report has spent everything and returned nothing.
    assert int(vector[vector.index("--max-turns") + 1]) >= 3


def test_a_ceiling_a_cli_cannot_take_is_dropped_not_refused(monkeypatch):
    """Losing a ceiling is a worse run; losing the plane over a flag this
    machine's build has never heard of is the `--verbose` mistake again."""
    monkeypatch.setattr(harness_mod, "locate", lambda one: f"/usr/bin/{one.executable}")
    monkeypatch.setattr(
        harness_mod, "declared",
        lambda _: frozenset({"--output", "--agent", "--enabled-tools", "--prompt",
                             "--trust"}),
    )
    vector = harness_mod.command_for(_one("mistral-vibe"),
                                     max_documents=3, budget_usd=0.5)
    assert "--max-price" not in vector and "--max-turns" not in vector
    assert vector[0].endswith("vibe")


def test_the_contract_forbids_the_tools_that_end_an_antigravity_run():
    """One `ls`-shaped reflex costs the whole run on this plane.

    Verified against the real CLI: the agent opened by running a shell command
    to look at its own empty working directory, was auto-denied, and the run
    ended there — exit 0, empty reply. The prompt is the only thing that can
    stop a tool call nothing is watching to approve.
    """
    low = harness_mod.CONTRACT.lower()
    assert "shell command" in low and "working directory" in low
    assert "ends the whole run" in low


# ── Antigravity: the permission that was never granted ───────────────────────


def test_antigravity_runs_under_a_home_that_grants_it_web_reading():
    """The grant lasts exactly one run and touches nothing the reader owns.

    Path and grammar were read off the binary and then confirmed by running
    it: `~/.gemini/antigravity-cli/settings.json`, holding rules shaped
    `read_url(*)`. Writing that into the reader's own file would leave a
    standing permission behind; writing it into a `HOME` that vanishes is the
    same grant with an end.
    """
    researcher = HarnessResearcher(_one("antigravity-cli"))
    with researcher._workspace():
        home = Path(researcher._run_env["USERPROFILE"])
        cwd = researcher._run_cwd
        settings = json.loads(
            (home / ".gemini" / "antigravity-cli" / "settings.json")
            .read_text(encoding="utf-8")
        )
    assert settings["permissions"]["allow"] == ["read_url(*)"]
    # A neutral working directory too, so a file the agent writes lands
    # somewhere that goes away rather than in the reader's own tree.
    assert cwd and Path(cwd) != Path.home()
    # And nothing survives the run.
    assert researcher._run_env == {}
    assert researcher._run_cwd is None


def test_the_sandbox_is_a_declared_property_not_a_protocol_guess():
    """`sandbox_home` is the field `_workspace` branches on, so a new CLI opts
    in by saying so rather than by being added to a tuple somewhere."""
    assert _one("antigravity-cli").sandbox_home is True
    assert _one("mistral-vibe").sandbox_home is True
    # And a CLI that runs in the reader's own environment says that too.
    assert _one("claude-code").sandbox_home is False


# ── Mistral Vibe: a reply with no result object at the end ───────────────────


def test_vibe_is_driven_with_a_builtin_agent_and_no_profile_to_maintain():
    """The earlier vector named a *custom* agent (`kriko-research`), which is
    why this row could never be verified: the file it needed had a shape
    nobody had read. `auto-approve` is builtin, and `--enabled-tools` is
    documented as disabling everything it does not name."""
    one = _one("mistral-vibe")
    assert not one.unusable
    assert "auto-approve" in one.args
    assert one.args.count("--enabled-tools") == 2
    assert "web_search" in one.args and "web_fetch" in one.args
    # Without it the run stops on a trust prompt headless mode cannot answer.
    assert "--trust" in one.args


def test_vibes_model_is_a_per_run_choice_even_with_no_flag_for_one():
    """It has no `--model`. Its model is a config field whose layer reads
    `VIBE_*` out of the environment, so the choice is per-run after all —
    and `command_for` must not refuse a model on the grounds of the missing
    flag."""
    one = _one("mistral-vibe")
    assert not one.model_flag
    assert one.model_env == "VIBE_ACTIVE_MODEL"


def test_vibe_model_choice_is_applied_as_the_environment_it_reads(monkeypatch):
    monkeypatch.setattr(harness_mod, "locate", lambda one: f"/usr/bin/{one.executable}")
    monkeypatch.setattr(
        harness_mod, "declared",
        lambda _: frozenset({"--output", "--agent", "--enabled-tools", "--prompt",
                             "--trust"}),
    )
    # A fake executable name, because `conftest` rightly refuses to let a test
    # start the reader's own CLI — and nothing here is about the binary. What
    # is under test is that the choice reaches the environment the CLI reads
    # its config from, which is the only per-run switch this one offers.
    researcher = HarnessResearcher(
        replace(_one("mistral-vibe"), executable="kriko-fake-vibe"),
        model="mistral-large-latest",
    )
    captured = {}

    def _stream(command, stdin_read, say):
        captured["env"] = dict(researcher._run_env)
        return 0, "", ""

    monkeypatch.setattr(researcher, "_stream", _stream)
    researcher.ask("anything")
    assert captured["env"]["VIBE_ACTIVE_MODEL"] == "mistral-large-latest"


def test_vibes_reply_is_read_out_of_its_history_entries():
    """`--output streaming` prints one history entry per message and **no
    result object**, so there is nothing for `_envelope` to find. Without this
    the whole NDJSON stream reaches `_payload` as prose, and the fence inside
    it is already JSON-escaped past recognition."""
    researcher = HarnessResearcher(_one("mistral-vibe"))
    stream = "\n".join(json.dumps(row) for row in [
        {"type": "message", "role": "user", "generationStatus": "completed",
         "content": [{"type": "text", "text": "the brief"}]},
        {"type": "message", "role": "assistant", "generationStatus": "pending",
         "content": [{"type": "text", "text": "half a thought"}]},
        {"type": "message", "role": "assistant", "generationStatus": "completed",
         "content": [{"type": "text", "text": '```json\n{"findings": []}\n```'}]},
    ])
    said = researcher._unwrap(stream)
    # The reader's own turn is not the reply, and an unfinished one is not yet.
    assert "the brief" not in said and "half a thought" not in said
    assert harness_mod._payload(said) == {"findings": []}


def test_a_vibe_stream_that_parses_to_nothing_is_handed_back_whole():
    """The same rule the other CLIs get: a reply this cannot read is prose,
    not an error. The findings fence may still be in it."""
    researcher = HarnessResearcher(_one("mistral-vibe"))
    assert researcher._unwrap("not json at all") == "not json at all"


# ── the job log: whole thoughts, once each ───────────────────────────────────


def test_a_streamed_reply_is_logged_as_sentences_rather_than_fragments():
    """Antigravity streams its answer a few characters at a time — "em OR
    issue", '"findings": [ { "titl', 'e": ' — so narrating each fragment
    turned one run's log into forty lines of shredded JSON."""
    researcher = HarnessResearcher(_one("antigravity-cli"))
    said = [
        researcher._narrate(json.dumps({
            "event": "step_update",
            "step_update": {"step_type": "agent_response", "state": state,
                            "text_delta": piece},
        }))
        for piece, state in [("I read two ", "ACTIVE"), ("pages", "ACTIVE"),
                             (" and found one fault.", "DONE")]
    ]
    assert [line for line in said if line] == [
        "I read two pages and found one fault."
    ]


def test_one_line_per_tool_call_not_two():
    """The CLI reports each step twice — ACTIVE when it starts and DONE when
    it finishes — with the same name and the same arguments."""
    researcher = HarnessResearcher(_one("antigravity-cli"))
    step = {"step_type": "tool", "tool_name": "search_web",
            "tool_info": {"name": "search_web",
                          "parameters": {"query": "a query"}}}
    active = json.dumps({"event": "step_update",
                         "step_update": {**step, "state": "ACTIVE"}})
    done = json.dumps({"event": "step_update",
                       "step_update": {**step, "state": "DONE"}})
    assert researcher._narrate(active) == ""
    assert "a query" in researcher._narrate(done)


# ── probing a CLI must always come back ──────────────────────────────────────


def test_asking_a_cli_about_itself_cannot_hang_the_screen():
    """`locate` once matched an unrelated Electron application called
    OpenCode; Kriko ran it with `--help` and never returned.

    `subprocess.run(timeout=…)` is not enough on Windows: it kills the process
    it started and then waits for the *pipes*, which a GUI app's surviving
    children hold open forever. Every screen that lists the planes waits on
    this call.
    """
    assert harness_mod._ask("a-command-that-does-not-exist-anywhere") == ""


def test_the_opencode_row_does_not_guess_a_directory_that_collides():
    """A fallback guess that is wrong must cost nothing. Windows paths are
    case-insensitive, so `AppData/Local/Programs` matched
    `…/Programs/OpenCode/OpenCode.exe` — a different application entirely."""
    homes = _one("opencode").homes
    assert "AppData/Local/Programs" not in homes
    assert ".opencode/bin" in homes


@pytest.mark.parametrize("ident", ["opencode", "mistral-vibe"])
def test_an_install_hint_is_one_the_reader_can_actually_paste(ident):
    """`curl … | bash` is the right line on macOS and Linux and is not
    runnable on the machine this reader is on. A hint nobody can paste teaches
    them the screen is decorative."""
    hint = _one(ident).install_hint
    assert hint
    if os.name == "nt":
        assert "| bash" not in hint


# ── an authored pack can be seen in a browser ────────────────────────────────

_PACK = {
    "pack_id": "test.buds", "name": "Wireless earbuds",
    "lineup": ["Galaxy Buds 3", "AirPods Pro 2"],
    "languages": ["en"], "markets": ["EU"],
    "identity": {"product": ["brand", "series"]},
    "principle": "Only config-specific failures.",
    "templates": ["{label} common problems"],
    "domains": [{"id": "audio", "label": "Audio"}],
    "subjects": [{"kind": "product", "label": "Galaxy Buds 3",
                  "identity": {"brand": "samsung", "series": "buds3"}}],
    "claims": [{"subject": {"kind": "product",
                            "identity": {"brand": "samsung", "series": "buds3"}},
                "domain": "audio", "severity": "medium",
                "title": "Driver rattle", "body": "b", "advice": "a"}],
}


def _authored(tmp_path, adapters):
    reply = "```json\n" + json.dumps({**_PACK, "adapters": adapters}) + "\n```"
    return packauthor.author(tmp_path / "knowledge.sqlite", reply,
                             category="earbuds")


def test_an_authored_pack_ships_an_adapter_so_it_can_be_seen(tmp_path):
    """**This is "new packs cannot be recognised in the web extension".**

    The boundary for shipping one has been open since drafts existed —
    `packdraft.WRITABLE_DIRS` allows `adapters/*.json` — and nothing ever
    asked an agent for one. So every pack an agent wrote had subjects, claims,
    and no way for the extension to recognise a page: the reader stood on a
    listing for exactly the product they had just authored a pack about, and
    the panel had nothing to say.
    """
    out = _authored(tmp_path, [{
        "site": "https://www.example-shop.com/a/path",
        "subject_kind": "product",
        "match": ["*://*.example-shop.com/*-p-*"],
        "identity": {"brand": {"labels": ["Marka", "Brand"], "from": "title"}},
    }])
    assert out["adapters"] == ["example-shop.com"]
    written = [one for one in out["files"] if one.startswith("adapters/")]
    assert written == ["adapters/example-shop_com.json"]
    body = json.loads(
        (Path(out["root"]) / written[0]).read_text(encoding="utf-8"))
    # A URL is normalised to the bare host it names — `site` becomes a browser
    # permission, so it is the one field here with teeth.
    assert body["site"] == "example-shop.com"
    assert body["identity"]["brand"]["labels"] == ["marka", "brand"]
    assert body["identity"]["brand"]["from"] == "title"


def test_an_adapter_may_not_claim_a_site_it_is_not_for(tmp_path):
    """A wildcard, a scheme or a path in `site` means the agent misunderstood
    what the field is — and the field is a host permission in somebody's
    browser. So is an identity key the pack never declared, which could only
    ever read nothing."""
    out = _authored(tmp_path, [
        {"site": "*", "subject_kind": "product",
         "identity": {"brand": {"labels": ["b"]}}},
        {"site": "ok-shop.com", "subject_kind": "nosuchkind",
         "identity": {"brand": {"labels": ["b"]}}},
        {"site": "other.com", "subject_kind": "product",
         "identity": {"nothing_declared": {"labels": ["b"]}}},
    ])
    assert out["adapters"] == []


def test_a_malformed_adapter_costs_the_adapter_and_not_the_pack(tmp_path):
    """A pack is its subjects and claims; an adapter is how one client reaches
    them. Losing twenty minutes of somebody's subscription over a malformed
    optional block would be the wrong trade."""
    out = _authored(tmp_path, ["not an object",
                               {"site": "fine.com", "subject_kind": "product",
                                "identity": {}}])
    assert out["adapters"] == []
    assert out["subjects"] == 1 and out["claims"] == 1


def test_a_pack_with_no_adapters_says_so_rather_than_omitting_the_answer(tmp_path):
    """Reported even when empty, because a pack with no adapter is knowledge
    no browser panel can reach — a gap worth learning from the run rather than
    from pressing the extension button on a page and getting nothing."""
    reply = "```json\n" + json.dumps(_PACK) + "\n```"
    out = packauthor.author(tmp_path / "knowledge.sqlite", reply,
                            category="earbuds")
    assert out["adapters"] == []


def test_the_authoring_contract_asks_for_the_adapter_and_says_why():
    """An agent that is not told a pack is invisible without one will not
    write one, and every pack authored before this was."""
    low = packauthor.CONTRACT.lower()
    assert "adapters" in low
    assert "invisible in the browser" in low
    # And the one rule with teeth is stated as such.
    assert "bare hostname" in low
