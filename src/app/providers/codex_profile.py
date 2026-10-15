"""Owned, reusable Codex homes without the user's tools or instructions."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

from app.loginpath import child_env
from app.providers.codex_transport import CodexProfile, CodexTransport


_LOCK = threading.RLock()
_HOMES: dict[str, tempfile.TemporaryDirectory] = {}
_TRANSPORT: CodexTransport | None = None
_INHERITED = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL",
)


def profile(executable: str, *, model: str = "", effort: str = "",
            namespace: str = "") -> CodexProfile:
    """Snapshot intended account state, and reuse only an identical profile.

    Credential bytes affect only a private hash and the owned auth file. They
    never enter run manifests or subprocess arguments. A login/account change
    creates a different profile rather than modifying a live worker's home.
    """
    original = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        auth = (original / "auth.json").read_bytes()
    except FileNotFoundError:
        auth = b""
    inherited = {name: os.environ[name] for name in _INHERITED if name in os.environ}
    resolved = Path(executable).resolve()
    stat = resolved.stat()
    identity = hashlib.sha256(json.dumps({
        "executable": str(resolved), "mtime": stat.st_mtime_ns, "size": stat.st_size,
        "account": hashlib.sha256(auth).hexdigest(), "environment": inherited,
        "model": model, "effort": effort, "namespace": namespace,
    }, sort_keys=True).encode()).hexdigest()
    with _LOCK:
        folder = _HOMES.get(identity)
        if folder is None:
            folder = tempfile.TemporaryDirectory(prefix="kriko-codex-")
            root = Path(folder.name)
            home, work = root / "home", root / "work"
            home.mkdir(mode=0o700)
            work.mkdir(mode=0o700)
            if auth:
                target = home / "auth.json"
                target.write_bytes(auth)
                target.chmod(0o600)
            (home / "config.toml").write_text(
                'approval_policy = "never"\nsandbox_mode = "read-only"\n'
                'web_search = "disabled"\n[features]\nshell_tool = false\n'
                'multi_agent = false\n[analytics]\nenabled = false\n', encoding="utf-8",
            )
            _HOMES[identity] = folder
        root = Path(folder.name)
    # Preserve the application's discovered executable path and OS variables;
    # the transport imposes CODEX_HOME/HOME and strips ambient agent settings.
    env = child_env(extra_dirs=(str(resolved.parent),))
    env = {name: value for name, value in env.items()
           if name.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
    env.update(inherited)
    return CodexProfile(str(resolved), str(root / "home"), str(root / "work"),
                        model=model, effort=effort, env=env,
                        account_fingerprint=hashlib.sha256(auth).hexdigest())


def transport() -> CodexTransport:
    global _TRANSPORT
    with _LOCK:
        if _TRANSPORT is None:
            _TRANSPORT = CodexTransport()
        return _TRANSPORT


def release_idle() -> None:
    """Make room for another provider without interrupting active research."""
    with _LOCK:
        owner = _TRANSPORT
    if owner is not None:
        owner.release_idle()


def shutdown() -> None:
    global _TRANSPORT
    with _LOCK:
        owner, _TRANSPORT = _TRANSPORT, None
    if owner is not None:
        owner.close()
    with _LOCK:
        folders = list(_HOMES.values())
        _HOMES.clear()
    for folder in folders:
        folder.cleanup()


atexit.register(shutdown)
