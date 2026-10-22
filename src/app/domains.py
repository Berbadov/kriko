"""Offline public-suffix and registrable-domain handling for the app."""

from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit


@lru_cache(maxsize=1)
def _suffix_rules() -> tuple[set[str], set[str], set[str]]:
    """Load the bundled PSL snapshot, including its MPL attribution."""
    raw = files("app").joinpath("public_suffix_list.dat").read_text(encoding="utf-8")
    normal: set[str] = set()
    wildcard: set[str] = set()
    exceptions: set[str] = set()
    for line in raw.splitlines():
        rule = line.strip()
        if not rule or rule.startswith("//"):
            continue
        target = exceptions if rule.startswith("!") else wildcard if rule.startswith("*.") else normal
        rule = rule.removeprefix("!").removeprefix("*.")
        target.add(rule.encode("idna").decode("ascii").lower())
    return normal, wildcard, exceptions


def publisher(url: str) -> str:
    """Registrable domain from the bundled public-suffix list; no network."""
    host = (urlsplit(url if "://" in url else f"//{url}").hostname or "").lower().rstrip(".")
    if not host:
        return ""
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    host = host.encode("idna").decode("ascii")
    labels = host.split(".")
    normal, wildcard, exceptions = _suffix_rules()
    suffix_length = 1
    for index in range(len(labels)):
        suffix = ".".join(labels[index:])
        if suffix in exceptions:
            suffix_length = len(labels) - index - 1
            break
        if suffix in normal:
            suffix_length = max(suffix_length, len(labels) - index)
        if index + 1 < len(labels) and ".".join(labels[index + 1:]) in wildcard:
            suffix_length = max(suffix_length, len(labels) - index)
    return ".".join(labels[-(suffix_length + 1):])
