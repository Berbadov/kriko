"""Chat page reads validate DNS destinations and each redirect hop."""

import socket
from email.message import Message

from app import chatweb
from app.providers import network


class Response:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.body = body
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.closed = True

    def getcode(self):
        return self.status

    def read(self, limit):
        return self.body[:limit]


def _dns(monkeypatch, addresses):
    def lookup(host, port, **kwargs):
        found = addresses.get(host)
        if found is None:
            raise socket.gaierror("unknown host")
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET,
             socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
            for address in found
        ]

    monkeypatch.setattr(socket, "getaddrinfo", lookup)


def test_a_successful_http_response_containing_a_bot_check_is_not_evidence(monkeypatch):
    _dns(monkeypatch, {"source.example": ["93.184.216.34"]})
    page = Response(200, body=(b"<html><body><p>Checking your browser before accessing "
                               b"the site.</p></body></html>"))
    monkeypatch.setattr(network, "urlopen", lambda *_args, **_kwargs: page)
    assert chatweb.reader()("https://source.example/blocked").text == ""


def test_dns_validation_rejects_private_and_mixed_addresses(monkeypatch):
    _dns(monkeypatch, {
        "public.example": ["93.184.216.34"],
        "mixed.example": ["93.184.216.34", "10.0.0.8"],
        "private.example": ["192.168.1.20"],
    })

    assert chatweb._public_url("https://public.example/page")
    assert chatweb._public_url("https://mixed.example/page") == ""
    assert chatweb._public_url("http://private.example/admin") == ""
    assert chatweb._public_url("http://user:pass@public.example/") == ""


def test_redirect_to_private_literal_is_not_requested(monkeypatch):
    _dns(monkeypatch, {"source.example": ["93.184.216.34"]})
    calls = []

    def open_url(url, **kwargs):
        calls.append(url)
        return Response(302, headers={"Location": "http://127.0.0.1/admin"})

    monkeypatch.setattr(network, "urlopen", open_url)
    page = chatweb.reader()("https://source.example/redirect")

    assert page.text == ""
    assert calls == ["https://source.example/redirect"]


def test_each_redirect_host_is_resolved_before_its_request(monkeypatch):
    _dns(monkeypatch, {
        "source.example": ["93.184.216.34"],
        "private.example": ["10.10.0.4"],
    })
    calls = []

    def open_url(url, **kwargs):
        calls.append(url)
        return Response(302, headers={"Location": "https://private.example/article"})

    monkeypatch.setattr(network, "urlopen", open_url)
    page = chatweb.reader()("https://source.example/redirect")

    assert page.text == ""
    assert calls == ["https://source.example/redirect"]


def test_page_reader_checks_cancellation_before_following_a_redirect(monkeypatch):
    _dns(monkeypatch, {"source.example": ["93.184.216.34"]})
    requests = []
    checks = 0

    def check_cancelled():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise RuntimeError("cancelled")

    def open_url(url, **kwargs):
        requests.append(url)
        return Response(302, headers={"Location": "https://source.example/next"})

    monkeypatch.setattr(network, "urlopen", open_url)
    read = chatweb.reader(check_cancelled=check_cancelled)

    import pytest
    with pytest.raises(RuntimeError, match="cancelled"):
        read("https://source.example/start")

    assert requests == ["https://source.example/start"]


def test_public_redirect_chain_reads_page_text_and_uses_shared_network(monkeypatch):
    _dns(monkeypatch, {
        "source.example": ["93.184.216.34"],
        "article.example": ["2606:2800:220:1:248:1893:25c8:1946"],
    })
    calls = []
    check = lambda: None
    markup = b"<html><head><title>Manual</title></head><body><p>Use specification RN17.</p></body></html>"

    def open_url(url, *, timeout, check, opener, **kwargs):
        calls.append((url, timeout, check, opener))
        if len(calls) == 1:
            return Response(302, headers={"Location": "https://article.example/manual"})
        return Response(200, body=markup)

    monkeypatch.setattr(network, "urlopen", open_url)
    page = chatweb.reader(timeout=4.5, check_cancelled=check)("https://source.example/redirect")

    assert "Use specification RN17." in page.text
    assert [call[0] for call in calls] == [
        "https://source.example/redirect", "https://article.example/manual"]
    assert all(call[1] == 4.5 and call[2] is check and callable(call[3]) for call in calls)
