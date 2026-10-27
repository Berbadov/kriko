"""Tell the search engines that take IndexNow which pages of kriko.cc exist.

    python site/tools/indexnow.py            # what would be sent
    python site/tools/indexnow.py --send     # send it

Bing, Yandex and the other engines behind the IndexNow protocol crawl what they are told
about within hours, where waiting to be found takes weeks. The proof that kriko.cc is ours is
a file at its root named for the key and holding the key (`site/<key>.txt`); it takes no
account anywhere. The list sent is every address in the sitemaps, so it is exactly what the
site publishes. Run it after a deploy, once the pages are live: an engine that fetches an
address that is not there yet writes the site off for a while.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HOST = "kriko.cc"
ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 10000  # the protocol's ceiling for one request
#: The engine's front door turns away the default urllib agent with a 403, so the request says who is asking.
HEADERS = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "kriko-indexnow/1 (+https://kriko.cc)"}
SITEMAPS = ("sitemap.xml", "sitemap-problems.xml")


def find_key(site: Path) -> str:
    """The key: the one `<key>.txt` at the root whose text is its own name."""
    for candidate in sorted(site.glob("*.txt")):
        if re.fullmatch(r"[0-9a-f]{8,128}", candidate.stem) and candidate.read_text(encoding="utf-8").strip() == candidate.stem:
            return candidate.stem
    raise SystemExit("no key file: put <key>.txt, holding the key, at the root of the site")


def addresses(site: Path) -> list[str]:
    """Every address the sitemaps list, once, in order."""
    found: list[str] = []
    for name in SITEMAPS:
        if (site / name).is_file():
            found += re.findall(r"<loc>([^<]+)</loc>", (site / name).read_text(encoding="utf-8"))
    return list(dict.fromkeys(found))


def requests(site: Path) -> list[dict]:
    """The bodies to send: the host, the key, where the key can be checked, and up to BATCH addresses."""
    key = find_key(site)
    urls = addresses(site)
    return [{"host": HOST, "key": key, "keyLocation": f"https://{HOST}/{key}.txt", "urlList": urls[n:n + BATCH]}
            for n in range(0, len(urls), BATCH)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--send", action="store_true", help="send the request; without it nothing leaves this machine")
    args = parser.parse_args()
    bodies = requests(args.site)
    total = sum(len(body["urlList"]) for body in bodies)
    if not args.send:
        print(f"would send {total} addresses in {len(bodies)} request(s) to {ENDPOINT}")
        return 0
    for body in bodies:
        request = urllib.request.Request(ENDPOINT, json.dumps(body).encode(), HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=60) as reply:
                print(f"{len(body['urlList'])} addresses: HTTP {reply.status}")
        except urllib.error.HTTPError as refused:
            print(f"{len(body['urlList'])} addresses: HTTP {refused.code} {refused.reason}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
