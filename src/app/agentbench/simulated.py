"""Scripted agents: the real quick-look path with only the model replaced.

They cost nothing, so a benchmark can be run, and its graders tested, without
spending a subscription. Each answers from the task's own key and then does one
thing wrong, on purpose, so a check that never fails is caught: the benchmark's
tests assert that every flaw is caught by exactly the check named for it
(`FLAW`), and that the faultless agent resolves every task.

A scripted agent reads the same prompt a real one would, so what it can see is
what Kriko actually showed it: a page it was not shown cannot be quoted, and
the language it writes in is whichever the brief asked for.
"""

import json
import re

from app.agentbench.checks import forbidden_id

PREFIX = "sim:"

#: name -> what it does. The first is the control: no flaw.
DESCRIPTION = {
    "oracle": "answers from the key, in the language asked for",
    "greedy": "adds a claim the evidence does not support",
    "fabricator": "adds a claim with a quote that is not on any page",
    "injected": "obeys an order written inside a page",
    "english": "ignores the language it was asked for",
    "silent": "reports nothing at all",
    "variant-blind": "reports a fault a page says does not apply",
}

#: The check each flaw must trip. `None` is the control.
FLAW = {
    "oracle": (),
    "greedy": ("no_extra_claims",),
    "fabricator": ("honest_proposals",),
    "injected": ("injection_resisted", "no_extra_claims"),
    "english": ("output_language",),
    "silent": ("recall", "specs_exact"),
    "variant-blind": ("no_forbidden_claims", "no_extra_claims"),
}


def names() -> list[str]:
    return [PREFIX + one for one in DESCRIPTION]


def is_simulated(agent: str) -> bool:
    return agent.startswith(PREFIX) and agent[len(PREFIX):] in DESCRIPTION


def _shown(prompt: str) -> dict[str, str]:
    """url -> text, for the pages the prompt carried, the way `_page_context` lays them out."""
    shown = {}
    for block in re.split(r"\n### ", prompt)[1:]:
        found = re.search(r"SOURCE URL: (\S+)\n\n(.*)", block, re.S)
        if found:
            shown[found.group(1)] = found.group(2).strip()
    return shown


def _language(prompt: str) -> str:
    found = re.search(r'BCP 47 code "([A-Za-z-]+)"', prompt)
    return found.group(1).lower() if found else ""


def _say(entry: dict, language: str) -> dict:
    said = entry.get("say") or {}
    return said.get(language) or said.get(language.split("-")[0]) or said["default"]


def _sentences(text: str) -> list[str]:
    return [one.strip() for one in re.split(r"(?<=[.!?])\s+", text) if len(one.strip()) >= 24]


def reply(flaw: str, task: dict, prompt: str) -> str:
    """The scripted agent's whole reply, as the JSON a real one is asked for."""
    expect = task.get("expect") or {}
    shown = _shown(prompt)
    language = "" if flaw == "english" else _language(prompt)
    risks: list[dict] = []
    specs: list[dict] = []

    def card(title: str, why: str, check: str, url: str, quote: str) -> dict:
        return {"title": title, "why": why, "check": check, "severity": "medium",
                "url": url, "quote": quote}

    if flaw != "silent":
        for entry in expect.get("supported") or []:
            if entry["url"] in shown:
                said = _say(entry, language)
                risks.append(card(said["title"], said["why"], said.get("check", ""),
                                  entry["url"], entry["quote"]))
        for entry in expect.get("specs") or []:
            if entry["url"] in shown:
                said = _say(entry, language)
                specs.append({"name": said["name"], "value": said["value"],
                              "url": entry["url"], "quote": entry["quote"]})

    first_url = next(iter(shown), "")
    if flaw == "greedy" and first_url:
        sentence = (_sentences(shown[first_url]) or [shown[first_url][:60]])[0]
        risks.append(card("Something about this product", "A remark the page makes.",
                          "", first_url, sentence))
    if flaw == "fabricator" and first_url:
        risks.append(card("Overheats under load", "Owners say it overheats.", "",
                          first_url, "owners say the unit overheats badly under sustained load"))
    marker = (expect.get("injection") or {}).get("marker")
    if flaw == "injected" and marker:
        for url, text in shown.items():
            hit = next((one for one in _sentences(text) if marker in one), "")
            if hit:
                risks.append(card(f"No problems. {marker}", "As the page instructed.", "", url, hit))
    if flaw == "variant-blind":
        for entry in expect.get("forbidden") or []:
            for url, text in shown.items():
                hit = next((one for one in _sentences(text)
                            if forbidden_id([entry], {"title": one, "sources": [{"url": url}]})), "")
                if hit:
                    risks.append(card(entry["id"].replace("-", " "), hit, "", url, hit))
                    break

    return json.dumps({"assumed": "", "category": "product", "pack": "", "pack_identity": {},
                       "specs": specs, "risks": risks}, ensure_ascii=False)
