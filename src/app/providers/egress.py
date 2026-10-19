"""Which URLs may this machine fetch on someone else's behalf?

Every address here arrives from somewhere other than the reader: a search
result, a source a model named, a pack index in a query parameter that any page
can set. The threat is not the public internet — it is this machine's own
surface:

* `127.0.0.1:8787` is the sidecar's API. It is unauthenticated *by design*
  (loopback was the whole argument), and it can install packs, write agent
  configuration and open a terminal;
* `169.254.169.254` is the cloud metadata address, which on a rented machine
  hands out credentials to anything that asks;
* anything else on the reader's network is reachable from here and not from
  whoever supplied the URL.

So a fetch of a chosen URL is refused when its host resolves into non-public
space. A URL the reader wrote into **their own settings** is exempt
(`allow_private=True`): a local index server is a real thing to want, and that
string is the reader's own configuration rather than a third party's.

Two limits, stated rather than implied. A host that does not resolve is *not*
refused — that is the network's job to fail, and reserving `.test` names is how
the suite exercises this path. And the address is checked, then connected to:
a name whose DNS answer changes between the two (a rebinding attack) can still
slip through. Closing that means pinning the resolved address into the
connection, which is a socket-level change this module does not make.
"""

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit


def _addresses(host: str) -> list[str]:
    """Every address this host resolves to, or [] when it does not resolve."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError, UnicodeError):
        return []
    return sorted({str(info[4][0]) for info in infos})


_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    # 100.64.0.0/10 (carrier-grade NAT) is neither private nor global to `ipaddress`:
    # it carries Tailscale addresses, the reader's own network, and Alibaba
    # Cloud's metadata address, 100.100.100.200.
    if isinstance(ip, ipaddress.IPv4Address) and ip in _SHARED_ADDRESS_SPACE:
        return False
    return not (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def reason_to_refuse(url: str, *, allow_private: bool = False) -> str | None:
    """Why this URL must not be fetched, or `None` when it may be."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"refusing a non-http(s) URL: {url!r}"
    if allow_private:
        return None
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return f"refusing a URL that names no host: {url!r}"
    addresses = _addresses(host)
    if not addresses:
        # Unresolvable: let the fetch fail on its own terms, so a reserved
        # name (`.test`) still reaches the code under test.
        return None
    for address in addresses:
        if not _is_public(address):
            return (f"{host!r} resolves to {address}, which is this machine or "
                    f"the reader's own network; Kriko will not fetch it on "
                    f"someone else's behalf")
    return None


class _RefuseUnsafeRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is a second URL the reader never saw: check it like the first."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        refusal = reason_to_refuse(urllib.parse.urljoin(req.full_url, newurl))
        if refusal:
            raise urllib.error.URLError(refusal)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def guarded_opener() -> urllib.request.OpenerDirector:
    """An opener that follows redirects only to hosts `reason_to_refuse` allows.

    `reason_to_refuse` looks at the URL it is given. A public page that answers
    `302 Location: http://127.0.0.1:8787/api/...` would otherwise be followed
    straight to the sidecar's own API. Proxy and CA settings stay as urllib's.
    """
    return urllib.request.build_opener(_RefuseUnsafeRedirects)
