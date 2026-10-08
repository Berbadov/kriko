"""Listing addresses without fragments or tracking parameters.

Product-bearing query parameters stay: different variants must not share cards.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return ""
        host = parts.hostname.lower().removeprefix("www.")
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port and port != {"http": 80, "https": 443}[parts.scheme.lower()]:
            host += f":{port}"
        query = sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                       if not key.lower().startswith("utm_")
                       and key.lower() not in ("gclid", "fbclid", "msclkid"))
        return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/") or "/",
                           urlencode(query), ""))
    except ValueError:
        return ""
