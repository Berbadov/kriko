"""Who is allowed to talk to a server on a fixed, guessable port.

Kriko binds 127.0.0.1 and has no accounts, which was the whole argument for
having no authorisation: there is nothing multi-tenant to protect. That
argument holds for the *network* and does not hold for the *browser*. The
sidecar also listens on 8787 — a constant, published in this repository and
hardcoded in the extension — and every page the reader visits runs script
that can reach it.

Two attacks, and they need different checks.

**A cross-site request from an ordinary page.** `Origin` is stamped by the
browser and cannot be forged by script. Most of the damage is already out of
reach — a JSON body is not a simple request, so it is preflighted, and we
send no CORS headers, so the browser refuses. But a simple GET executes even
though the page cannot read the reply, and `GET /api/focus` is
consume-once: a page could quietly burn a nudge the reader was about to act
on. Checking `Origin` closes it, and costs nothing.

**DNS rebinding.** An attacker points `example.invalid` at 127.0.0.1, and now
their page *is* same-origin with this server: `Origin` is their own site,
which is theirs to set, and the browser is satisfied. `Origin` cannot catch
this. `Host` can, because the browser sends the name the reader's page asked
for and the attack requires that name to be a public DNS record.

Which is the rule below: a `Host` carrying a dot must be one we recognise.
A public name always has one; `localhost`, `testserver` and a bare hostname
resolve nowhere an attacker controls. That is why there is no test-only
exemption here — a rule with a hole cut in it for the suite is a rule the
suite stops testing.

Fails closed, and says why: a 403 whose body names the header it objected to,
because the one person who will ever see it is the reader, and "Forbidden"
would send them to reinstall the extension.
"""

from urllib.parse import urlsplit

#: Browser extensions. Their origin is `<scheme>://<extension id>`, and the id
#: is not knowable in advance — it changes per browser and per install — so the
#: scheme is what is matched. Any extension the reader has installed can reach
#: this server, which is the same trust the reader already extended by
#: installing it; the alternative is a token, and that is a 1.0.x decision
#: rather than a 1.0.0 one (see the audit's Q5).
EXTENSION_SCHEMES = ("chrome-extension", "moz-extension", "safari-web-extension")

#: Hosts this server answers to. `tauri.localhost` is the desktop shell's own
#: origin on Windows, where the webview does not use the http:// URL.
LOOPBACK_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0", "tauri.localhost"}
)

#: Non-http schemes the desktop shell's webview may load the SPA from.
SHELL_SCHEMES = ("tauri", "asset")


def _bare_host(value: str) -> str:
    """`127.0.0.1:8787` → `127.0.0.1`; keeps a bracketed IPv6 literal whole."""
    host = value.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.split(":", 1)[0]


def host_is_ours(header: str | None) -> bool:
    """Is this the name of a server on this machine, or a rebinding attempt?

    A missing `Host` is allowed: HTTP/1.0 omits it, and that is what
    `wait_until_healthy` in the desktop shell speaks — a hand-rolled request
    over a raw TcpStream, because pulling in an HTTP client to poll one
    endpoint was the wrong trade. Rejecting it would mean the window never
    opens.
    """
    if not header:
        return True
    host = _bare_host(header)
    if host in LOOPBACK_HOSTS:
        return True
    # No dot: not a public DNS name, so not a rebinding target. A bare
    # hostname on a LAN resolves only for whoever is already on it, and they
    # can reach the port directly anyway.
    return "." not in host


def origin_is_allowed(header: str | None) -> bool:
    """Is this request coming from somewhere entitled to drive the app?

    A missing `Origin` is allowed, and that is not the hole it looks like.
    Browsers stamp it on every cross-site request and on every POST; what
    arrives without one is a same-origin GET (already entitled), a native
    client, or `curl` — and none of those is the attack this guards against.
    Something that can set arbitrary headers is not being stopped by a header
    check in the first place.
    """
    if not header:
        return True
    origin = header.strip().lower()
    if origin == "null":
        # A sandboxed iframe or a `file://` page. Nothing legitimate here
        # arrives that way, and it is the one origin an attacker can obtain
        # without owning a domain.
        return False
    parts = urlsplit(origin)
    if parts.scheme in EXTENSION_SCHEMES or parts.scheme in SHELL_SCHEMES:
        return True
    if parts.scheme in ("http", "https"):
        return _bare_host(parts.netloc) in LOOPBACK_HOSTS
    return False


def terminal_origin_is_allowed(header: str | None) -> bool:
    if not header:
        return True
    origin = header.strip().lower()
    if origin == "null":
        return False
    parts = urlsplit(origin)
    if parts.scheme in SHELL_SCHEMES:
        return True
    if parts.scheme in ("http", "https"):
        return _bare_host(parts.netloc) in LOOPBACK_HOSTS
    return False


def refuse(origin: str | None, host: str | None) -> str | None:
    """The reason to refuse this request, or ``None`` to serve it."""
    if not origin_is_allowed(origin):
        return (
            f"This app only answers requests from itself and from the Kriko "
            f"browser extension. Origin {origin!r} is neither."
        )
    if not host_is_ours(host):
        return (
            f"This app answers on 127.0.0.1 only. A request addressed to "
            f"{host!r} reached it, which means a name outside this machine "
            f"resolves here — close the page that sent it."
        )
    return None
