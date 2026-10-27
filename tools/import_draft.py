"""Turn a finished catalog draft into a catalog the repository ships.

    PYTHONPATH=src python tools/import_draft.py <draft directory> [--name <directory>]

A draft the engine authored and researched is a working copy, and three things in it are not
fit for a catalog other readers install:

  * claims nobody sourced: an agent's proposals, written at `confidence: 0.5` with no page and
    no quote. A shared catalog carries a claim only with the page and quote it came from;
  * the sentence in which the agent narrates how it found a claim ("Found via the ... search"),
    which says nothing about the product and reads as a defect on a public page;
  * site adapters the agent wrote from memory rather than from reading a page.

This copies the draft to `packs/<name>`, keeps only claims that carry evidence, strips the
narrating sentence, drops the adapters, writes a README that says what the catalog is, and gives
the manifest the id, license and publisher the other catalogs declare. A claim whose words are
too short once the narration is gone is dropped rather than published thin. A catalog that ships
search queries also ships how to aim them (`research/skill.md`); a draft that has none gets one
written from the identity keys its own manifest declares. Nothing here knows a category: the
draft's own data is the input.
"""

import argparse
import re
import shutil
import sys
import tomllib
from pathlib import Path

import yaml

LICENSE = "CC-BY-SA-4.0"
PUBLISHER = "kriko"
ORIGIN = "https://github.com/kriko/kriko"
SHORTEST_BODY = 60
#: The sentence an agent writes about its own search, not about the product: it opens by saying where
#: the claim came from and, before its first full stop or semicolon, names a search, query or seed.
NARRATION = re.compile(r"^(?:found via|came from|surfaced|sourced|retrieved|from|via)\b(?:[^.;]|\.(?=\S))*\b(?:search(?:es)?|quer(?:y|ies)|seeds?|rewrites?)\b", re.I)
#: A sentence in which the agent talks about its own tools, wherever it stands in the body.
OWN_TOOLS = re.compile(r"\b(?:my fetcher|the fetcher|search-returned|search tool)\b", re.I)
#: What follows a semicolon in such a sentence is kept when it is long enough to be a sentence of its own.
REMAINDER = 40
SKIPPED = {".installed", "__pycache__", "adapters"}
HEADER = ("# Claims — what is known to go wrong, each with the page it came from and the quote\n"
          "# that was read there. A claim without both is not in this file.\n")


def plain(body: str) -> str:
    """The body without the sentences that narrate how it was found."""
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", " ".join(str(body).split())):
        if OWN_TOOLS.search(sentence):
            continue
        if not NARRATION.match(sentence):
            kept.append(sentence)
            continue
        tail = sentence.partition(";")[2].strip()
        if len(tail) >= REMAINDER:
            kept.append(tail[0].upper() + tail[1:])
    return " ".join(kept).strip()


def keep(claims: list) -> list:
    """The evidenced claims, with their words cleaned; the ones left too thin are dropped."""
    kept = []
    for claim in claims:
        if not isinstance(claim, dict) or not claim.get("evidence"):
            continue
        words = claim.get("text") or {}
        for language, one in list(words.items()):
            one["body"] = plain(one.get("body", ""))
            if len(one["body"]) < SHORTEST_BODY:
                del words[language]
        if words:
            kept.append(claim)
    return kept


def manifest(text: str, name: str, icon: str = "") -> str:
    """The manifest with the id a published catalog carries and the lines it declares; `icon` names its drawing."""
    found = re.search(r'^id\s*=\s*"([^"]+)"', text, re.M)
    pack_id = found.group(1) if found else name.replace("-", ".")
    if not pack_id.startswith("org."):
        text = re.sub(r'^id\s*=\s*"[^"]+"', f'id = "org.kriko.{pack_id}"', text, count=1, flags=re.M)
    extra = "".join(f'{key} = "{value}"\n' for key, value in (("license", LICENSE), ("publisher", PUBLISHER), ("origin", ORIGIN),
                                                              ("icon", icon))
                    if value and not re.search(rf"^{key}\s*=", text, re.M))
    version = re.search(r"^version\s*=.*\n", text, re.M)
    return text[:version.end()] + extra + text[version.end():] if version and extra else text


def readme(title: str, products: int, claims: int, languages: list) -> str:
    return (f"# {title}\n\n"
            f"What owners and repairers report going wrong with specific products. It covers {products} "
            f"products and holds {claims} sourced claims. Every claim carries the page it came from and the "
            f"quote that was read there, so each can be checked against its source.\n\n"
            f"It was authored and researched by the Kriko Agent and installed with the app's catalog "
            f"update. What it surfaces, and what it leaves out, is in `research/principle.md`. "
            f"The claims are written in {', '.join(languages)}; a quote stays in the language of its page.\n\n"
            f"Licensed {LICENSE}.\n")


def skill(toml: str, title: str) -> str:
    """How to identify a product of this catalog before searching, from the identity keys it declares."""
    identity = tomllib.loads(toml).get("identity") or {}
    told = "".join(f"   - a **{kind}**: {', '.join(f'`{key}`' for key in keys)}\n" for kind, keys in identity.items())
    return (f"# Identifying a product in {title} before researching it\n\n"
            "A listing's name is not a subject. Resolve what this catalog tells products apart by *before*\n"
            "searching, and search on that.\n\n"
            "1. **Resolve identity before searching.** This catalog tells its subjects apart by:\n\n"
            f"{told}\n"
            "   Read the keys from the installed catalog at run time, never from memory: the list changes\n"
            "   when the catalog does.\n"
            "2. **Search the discriminating attribute, not the label.** What goes wrong is reported against\n"
            "   the model, version or configuration, not against a brand. A brand alone finds marketing,\n"
            "   not failure reports.\n"
            "3. **One product versus its family.** A report about a sibling product can inform a search; it\n"
            "   is never filed as a fact about this one unless the claim says which parts the two share.\n"
            "4. **Refuse rather than guess.** If the listing does not fix every key above, report what is\n"
            "   missing and what would settle it, and leave the subject unresearched instead of aiming at a\n"
            "   neighbour. A confident wrong answer is worse than none.\n"
            "5. **The bar is `principle.md`, in full.** Read it before filing anything.\n")


def title_of(text: str, fallback: str) -> str:
    found = re.search(r'^name\s*=\s*"([^"]+)"', text, re.M)
    return found.group(1) if found else fallback


def import_draft(draft: Path, packs: Path, name: str, icon: str = "") -> tuple[Path, int, int]:
    """Copy `draft` to `packs/<name>`; returns the directory, the claims kept and the claims dropped."""
    target = packs / name
    if target.exists():
        raise FileExistsError(f"{target} already exists; a catalog is replaced by editing it, not by importing over it")
    shutil.copytree(draft, target, ignore=lambda _dir, names: [n for n in names if n in SKIPPED])
    path = target / "data" / "claims.yaml"
    claims = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    kept = keep(claims)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(HEADER + yaml.safe_dump(kept, allow_unicode=True, sort_keys=False, width=100))
    toml = (target / "pack.toml").read_text(encoding="utf-8")
    with open(target / "pack.toml", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(manifest(toml, name, icon))
    if (target / "research" / "templates.yaml").exists() and not (target / "research" / "skill.md").exists():
        with open(target / "research" / "skill.md", "w", encoding="utf-8", newline="\n") as handle:
            handle.write(skill(toml, title_of(toml, name)))
    languages = sorted({language for claim in kept for language in claim["text"]}) or ["en"]
    products = len(yaml.safe_load((target / "data" / "subjects.yaml").read_text(encoding="utf-8")) or [])
    with open(target / "README.md", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(readme(title_of(toml, name), products, len(kept), languages))
    return target, len(kept), len(claims) - len(kept)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("draft", type=Path, help="a finished draft directory")
    parser.add_argument("--name", help="the directory under packs/ (default: the draft's own name)")
    parser.add_argument("--icon", default="", help="the drawing its pages show, by name (ICONS in site/tools/render_problems.py)")
    parser.add_argument("--packs", type=Path, default=Path(__file__).resolve().parents[1] / "packs")
    args = parser.parse_args()
    target, kept, dropped = import_draft(args.draft, args.packs, args.name or args.draft.name, args.icon)
    print(f"{target}: {kept} claim(s) kept, {dropped} dropped for want of a source or of words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
