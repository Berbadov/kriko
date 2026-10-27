"""Add a language to a catalog's claims: English is written first, this writes the second.

    PYTHONPATH=src python tools/translate_catalog.py packs/<name> --to tr

An agent's research is written in one language (the engine stores an accepted claim's
words as English), but a catalog may ship its claims in several: `text:` in
`data/claims.yaml` is a mapping from language to `title`, `body` and `advice`. This reads
every claim that has English words and no words in `--to`, has them translated, writes
them beside the English, and adds the language to `languages` in `pack.toml`.

Only a claim's words are translated. Its evidence (the page and the quote) is never touched:
a quote stays in the language its page was written in, which is what makes it checkable.

Already-translated claims are left exactly as they are, so a second run costs nothing and a
reviewed translation is never overwritten. The translator is DeepSeek Chat on the reader's
own `DEEPSEEK_API_KEY`; the claim text sent is the public text the catalog already ships.
"""

import argparse
import json
import re
import sys
import tomllib
import urllib.request
from pathlib import Path
from typing import Callable

import yaml

LANGUAGES = {"tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish"}
FIELDS = ("title", "body", "advice")
BATCH = 6
ENDPOINT = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

Translator = Callable[[list[dict], str], list[dict]]


def _rule(language: str) -> str:
    return (
        f"Translate the fields of each JSON object into {language}. Keep model names, part codes, "
        "numbers, currencies and website names exactly as written. Translate any quoted words too, "
        "keeping the quotation marks. Do not add, drop or soften anything. Reply with one JSON array, "
        "the same length and order as the input, each element an object with the same keys, and "
        "nothing else."
    )


def deepseek(items: list[dict], language: str) -> list[dict]:
    """Translate a batch through DeepSeek Chat; raises when the reply is not the batch back."""
    from app import keys

    body = {
        "model": MODEL, "temperature": 0.2, "max_tokens": 8000,
        "messages": [{"role": "system", "content": _rule(language)},
                     {"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
    }
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"authorization": "Bearer " + keys.require("deepseek"), "content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        text = json.loads(response.read())["choices"][0]["message"]["content"]
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ValueError("the translator did not return a JSON array")
    return json.loads(match.group(0))


def _clean(items: list[dict], got: list[dict]) -> list[dict]:
    if not isinstance(got, list) or len(got) != len(items):
        raise ValueError(f"asked for {len(items)} translations, got {len(got) if isinstance(got, list) else 'none'}")
    out = []
    for want, one in zip(items, got):
        if not isinstance(one, dict):
            raise ValueError("a translation is not an object")
        row = {key: str(one.get(key) or "").strip() for key in FIELDS if want.get(key)}
        if any(not row.get(key) for key in FIELDS if want.get(key)):
            raise ValueError("a translation came back with a field empty")
        out.append(row)
    return out


def _translate(batch: list[dict], language: str, translator: Translator) -> list[dict]:
    """One batch, retried smaller when its reply is not the batch back."""
    try:
        return _clean(batch, translator(batch, language))
    except (ValueError, KeyError, json.JSONDecodeError):
        if len(batch) == 1:
            raise
        middle = len(batch) // 2
        return _translate(batch[:middle], language, translator) + _translate(batch[middle:], language, translator)


def _name_in(text: str, to: str, language: str, translator: Translator) -> str:
    """The manifest with the catalog's own name added in `to` under `[names]`, unless it is there.

    A page in the second language names the catalog in that language; the manifest's `name`
    stays what the catalog calls itself.
    """
    found = re.search(r'^name\s*=\s*"([^"]+)"', text, re.M)
    if not found or tomllib.loads(text).get("names", {}).get(to):
        return text
    name = _translate([{"title": found.group(1)}], language, translator)[0]["title"]
    line = f"{to} = {json.dumps(name, ensure_ascii=False)}\n"
    if "[names]" in text:
        return text.replace("[names]\n", "[names]\n" + line, 1)
    return text.rstrip("\n") + "\n\n# The catalog's name in each other language its pages are written in.\n[names]\n" + line


def translate_file(root: Path, to: str, translator: Translator = deepseek) -> int:
    """Translate the claims under `root` that lack `to`; returns how many were added."""
    path = root / "data" / "claims.yaml"
    raw = path.read_text(encoding="utf-8") if path.exists() else ""  # a catalog with its own builder has none
    preamble = "".join(line for line in raw.splitlines(keepends=True) if line.startswith("#"))
    claims = yaml.safe_load(raw) or []
    todo = [c for c in claims if isinstance(c, dict) and (c.get("text") or {}).get("en") and not (c["text"].get(to))]
    language = LANGUAGES.get(to, to)
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        sent = [{key: c["text"]["en"].get(key, "") for key in FIELDS} for c in batch]
        for claim, words in zip(batch, _translate(sent, language, translator)):
            claim["text"][to] = words
    if todo:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(preamble + yaml.safe_dump(claims, allow_unicode=True, sort_keys=False, width=100))
    manifest = root / "pack.toml"
    original = text = manifest.read_text(encoding="utf-8")
    text = _name_in(text, to, language, translator)
    found = re.search(r"^languages\s*=\s*\[(.*?)\]", text, re.M)
    if found and f'"{to}"' not in found.group(1):
        kept = [part.strip() for part in found.group(1).split(",") if part.strip()]
        text = text[:found.start()] + "languages = [" + ", ".join(kept + [f'"{to}"']) + "]" + text[found.end():]
    if text != original:
        with open(manifest, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    return len(todo)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("catalog", type=Path, help="a catalog directory, like packs/<name>")
    parser.add_argument("--to", required=True, choices=sorted(LANGUAGES), help="the language to add")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    added = translate_file(args.catalog, args.to)
    print(f"{args.catalog}: {added} claim(s) translated into {LANGUAGES[args.to]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
