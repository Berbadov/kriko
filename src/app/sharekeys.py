"""Shared access: a password that spends the owner's keys, inside this app only.

The reader's words: *"i give them a password they paste it into settings and
then they can use kriko agent easily on my api keys. which are secure right now.
so password should not work outside of kriko app"* — and, for people who have
not been given one, *"a few query allowance for the first timer unknown people
that want to test the app. still using my keys but its limited on kriko agent"*.

What travels is one **access code** and one **password**, and neither is the
key:

* The code is the owner's Mercury and DeepSeek keys, sealed with AES-256-GCM
  under a key derived from the password with **scrypt** — the same shape the
  relay already uses (`app/cloud.py`: HKDF-SHA256 and AESGCM).
* The derivation also mixes in a **build pepper**: a secret that lives in the
  shipped application and is not in this repository. A code plus a password,
  without the app, decrypts to nothing. That is what makes the password
  *"not work outside kriko app"* rather than merely hard to guess.
* What the app stores afterwards is sealed again under a **device key** kept in
  the reader's own `~/.kriko/device.key`; on Windows that key is protected with
  DPAPI, so the copy of `~/.kriko` does not carry access to another machine.
  The keys are never written in the clear and never returned by any endpoint.

The trial is the same seal with no password at all: a bundle the owner bakes
into a build (`tools/make_trial_access.py`) and an app-side count of questions,
kept here beside the grant. It is a courtesy, not a wall — a reader who deletes
their own state starts the count again — which is why the owner's protection is
the provider-side spend limit on the trial key and rotating it per release, and
why this module says so instead of pretending otherwise.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: What a sealed access code starts with, so a wrong paste is refused as itself
#: rather than as a wrong password.
PREFIX = b"KSA1"
#: The associated data of a grant and of a trial bundle: different purposes, so
#: one cannot be replayed as the other.
GRANT_AAD = b"kriko/shared-access/grant/v1"
TRIAL_AAD = b"kriko/shared-access/trial/v1"
#: What the app keeps on the reader's own disk: the opened grant, sealed again
#: so the owner's keys are never written in the clear.
DEVICE_AAD = b"kriko/shared-access/device/v1"
#: What a trial allows before it asks for a password: the reader's "a few query
#: allowance". Counted in Kriko Agent questions, not in searches.
TRIAL_QUESTIONS = 10
#: scrypt's cost. 2**15 with r=8 is about 32 MB and 60-90 ms on the machine this
#: was written on: enough to make guessing a password expensive, cheap enough to
#: pay once when the code is pasted.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
_SCRYPT_MAXMEM = 96 * 1024 * 1024

#: The providers a shared code carries. The fixed stack of Kriko Agent, which is
#: what this access is for.
SHARED_PROVIDERS = ("mercury", "deepseek")


class ShareError(Exception):
    """A code, a password or an allowance the reader has to be told about."""


def home() -> Path:
    from app.web.settings import KRIKO_HOME

    return Path(KRIKO_HOME)


def state_path(where: Path | None = None) -> Path:
    return (where or home()) / "shared.json"


def device_path(where: Path | None = None) -> Path:
    return (where or home()) / "device.key"


# ── the build pepper ────────────────────────────────────────────────────


def _baked_pepper() -> str:
    """The pepper this build was made with, or "" when it has none.

    `tools/make_share_pepper.py` writes `app/sharekeys_pepper.py` at build time.
    It is not in the repository, and a build without one says so through
    `status()["bound"] is False` rather than pretending the seal is app-bound.
    """
    try:
        from app.sharekeys_pepper import PEPPER  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — a build without a pepper is a real state
        return ""
    return str(PEPPER or "")


def pepper() -> bytes:
    value = os.environ.get("KRIKO_SHARE_PEPPER") or _baked_pepper()
    return value.encode("utf-8")


def bound() -> bool:
    """Whether this build carries a pepper, i.e. whether a code is app-bound."""
    return bool(pepper())


# ── the device key ──────────────────────────────────────────────────────


def _dpapi(raw: bytes, *, protect: bool) -> bytes | None:
    """Windows DPAPI, or `None` where it does not exist.

    The key is bound to the Windows account that made it, which is what stops a
    copied `~/.kriko` from opening anywhere else. Anything else — a Mac, a Linux
    box — gets the 0600 file, and `status()` says which one is in use.
    """
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    # `buffer` is held for the life of the call: the blob points into it, and a
    # temporary would be collected before CryptProtectData read it.
    buffer = ctypes.create_string_buffer(raw, len(raw))
    source = DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    out = DATA_BLOB()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = (ctypes.byref(source), None, None, None, None, 0, ctypes.byref(out))
    if not call(*args):
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def device_key(where: Path | None = None) -> bytes:
    """This installation's own secret: 32 bytes, made on first use.

    Not a password and never shown: it only wraps the grant that has already
    been opened once, so the reader is not asked for their password again every
    morning.
    """
    path = device_path(where)
    if path.exists():
        raw = path.read_bytes()
        opened = _dpapi(raw, protect=False)
        return opened if opened else raw
    raw = secrets.token_bytes(32)
    protected = _dpapi(raw, protect=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(protected or raw)
    _private(path)
    return raw


def _private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:  # noqa: BLE001 — Windows has no mode to set; ACLs are the file's own
        pass


# ── sealing ─────────────────────────────────────────────────────────────


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt_key(password: str, salt: bytes) -> bytes:
    """The password's key, with this build's pepper in it.

    The pepper is mixed into the passphrase rather than into the salt so that a
    code sealed by a build with a pepper cannot be opened by one without it, in
    either direction.
    """
    material = "\0".join([password, pepper().hex()]).encode("utf-8")
    return hashlib.scrypt(material, salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                          dklen=32, maxmem=_SCRYPT_MAXMEM)


def _pepper_key(purpose: bytes) -> bytes:
    """A key that needs the build and nothing else — what the trial uses."""
    return hashlib.scrypt(pepper() or b"kriko-without-a-pepper", salt=purpose,
                          n=2**14, r=8, p=1, dklen=32, maxmem=_SCRYPT_MAXMEM)


def _seal(payload: dict, key: bytes, aad: bytes) -> str:
    nonce = secrets.token_bytes(12)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sealed = AESGCM(key).encrypt(nonce, data, aad)
    return _b64(PREFIX + nonce + sealed)


def _open(code: str, key: bytes, aad: bytes) -> dict:
    text = str(code or "").strip().replace("\n", "").replace(" ", "")
    try:
        blob = _unb64(text)
    except Exception as error:  # noqa: BLE001 — a mistyped paste is one answer
        raise ShareError("That does not look like an access code. Copy the whole line.") from error
    if not blob.startswith(PREFIX) or len(blob) < len(PREFIX) + 12 + 16:
        raise ShareError("That does not look like an access code. Copy the whole line.")
    nonce = blob[len(PREFIX):len(PREFIX) + 12]
    try:
        opened = AESGCM(key).decrypt(nonce, blob[len(PREFIX) + 12:], aad)
    except Exception as error:  # noqa: BLE001 — a wrong password and a damaged code are the same thing to a reader
        raise ShareError(
            "Could not open it: the password is not the one this code was made with, "
            "or the code was changed on the way."
        ) from error
    try:
        payload = json.loads(opened)
    except ValueError as error:  # noqa: BLE001
        raise ShareError("The code opened, but carried nothing readable.") from error
    if not isinstance(payload, dict):
        raise ShareError("The code opened, but carried nothing readable.")
    return payload


def _keys_of(payload: dict) -> dict[str, str]:
    out = {name: str(payload.get(name) or "").strip() for name in SHARED_PROVIDERS}
    return {name: value for name, value in out.items() if value}


# ── the two directions ──────────────────────────────────────────────────


def make_access(password: str, values: dict[str, str]) -> str:
    """The owner's side: seal these keys under this password, and return a code.

    The code is the whole secret, and it is meant to be sent down whatever
    channel the owner already trusts the friend on — a message, spoken aloud,
    a piece of paper. The password travels separately, or the code is worth
    nothing to whoever reads it on the way.
    """
    if len(str(password or "")) < 8:
        raise ShareError("Choose a password of at least 8 characters.")
    carried = _keys_of(values)
    if not carried:
        raise ShareError("Save the Mercury and DeepSeek keys on this computer first.")
    salt = secrets.token_bytes(16)
    key = _scrypt_key(password, salt)
    return _b64(PREFIX + salt) + "." + _seal(carried, key, GRANT_AAD)


def open_access(code: str, password: str) -> dict[str, str]:
    """The friend's side: open an access code with the password that came with it."""
    text = str(code or "").strip().replace("\n", "").replace(" ", "")
    head, _, body = text.partition(".")
    if not body:
        raise ShareError("That does not look like an access code. Copy the whole line.")
    try:
        blob = _unb64(head)
    except Exception as error:  # noqa: BLE001
        raise ShareError("That does not look like an access code. Copy the whole line.") from error
    if not blob.startswith(PREFIX) or len(blob) != len(PREFIX) + 16:
        raise ShareError("That does not look like an access code. Copy the whole line.")
    salt = blob[len(PREFIX):]
    if not password:
        raise ShareError("Paste the password that came with the code as well.")
    return _keys_of(_open(body, _scrypt_key(password, salt), GRANT_AAD))


def make_trial(values: dict[str, str], questions: int = TRIAL_QUESTIONS) -> str:
    """The owner's side of the trial: a bundle only this build can open.

    No password, because there is nobody to give one to: the bundle is baked
    into a build and a stranger opens it by installing the app. Its protection
    is the pepper, the app-side count, and — the one that actually holds — the
    spend limit the owner puts on the key it carries. `questions` is the owner's
    number and travels in the bundle, so a build can be stingier than the
    default without a code change.
    """
    carried = _keys_of(values)
    if not carried:
        raise ShareError("A trial bundle needs the keys it carries.")
    carried["questions"] = str(max(1, int(questions)))
    return _seal(carried, _pepper_key(TRIAL_AAD), TRIAL_AAD)


def open_trial(code: str) -> dict[str, str]:
    return _keys_of(_open(code, _pepper_key(TRIAL_AAD), TRIAL_AAD))


def trial_limit(code: str) -> int:
    """How many questions the baked bundle allows. The owner's number, or ours."""
    try:
        carried = _open(code, _pepper_key(TRIAL_AAD), TRIAL_AAD)
        return max(1, int(carried.get("questions") or TRIAL_QUESTIONS))
    except (ShareError, TypeError, ValueError):
        return TRIAL_QUESTIONS


# ── what is kept on this machine ────────────────────────────────────────

#: The trial bundle a build carries, if any. `tools/make_trial_access.py` writes
#: it beside this module; a build without one offers no trial.
#:
#: JSON rather than a bare line on purpose: `packaging/kriko-sidecar.spec`
#: bundles every `src/app/*.json` (and `pyproject.toml` declares them as package
#: data), so a bundle that is there travels inside the frozen sidecar and a
#: bundle that is not there is simply absent. A `.txt` would have needed a new
#: line in both places, and a missing one is a FileNotFoundError at startup.
TRIAL_FILE = Path(__file__).with_name("trial_access.json")


def _baked_trial() -> str:
    try:
        data = json.loads(TRIAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str((data or {}).get("bundle") or "") if isinstance(data, dict) else ""


def write_trial(bundle: str, *, where: Path | None = None) -> Path:
    """Keep a baked bundle where this module looks for it."""
    path = where or TRIAL_FILE
    path.write_text(json.dumps({"bundle": bundle}, indent=2) + "\n", encoding="utf-8")
    return path


def read_state(where: Path | None = None) -> dict:
    try:
        data = json.loads(state_path(where).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(state: dict, where: Path | None = None) -> None:
    path = state_path(where)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, sort_keys=True, indent=2), encoding="utf-8")
    _private(path)


def _wrap(values: dict[str, str], where: Path | None) -> str:
    """Keep opened keys sealed under this installation's own device key."""
    nonce = secrets.token_bytes(12)
    data = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sealed = AESGCM(device_key(where)).encrypt(nonce, data, DEVICE_AAD)
    return _b64(nonce + sealed)


def _unwrap(sealed: str, where: Path | None) -> dict[str, str]:
    try:
        blob = _unb64(sealed)
        opened = AESGCM(device_key(where)).decrypt(blob[:12], blob[12:], DEVICE_AAD)
        values = json.loads(opened)
    except Exception:  # noqa: BLE001 — a device key that changed is a grant to paste again
        return {}
    return values if isinstance(values, dict) else {}


def unlock(code: str, password: str, *, label: str = "", where: Path | None = None) -> dict:
    """Open a code, keep it, and report what it grants. The password is not kept."""
    values = open_access(code, password)
    if not values:
        raise ShareError("That code carries no keys.")
    state = read_state(where)
    state["grant"] = {
        "label": str(label or "")[:80],
        "sealed": _wrap(values, where),
        "providers": sorted(values),
    }
    state.pop("refused", None)
    write_state(state, where)
    return {"providers": sorted(values), "label": state["grant"]["label"]}


def forget(where: Path | None = None) -> None:
    state = read_state(where)
    state.pop("grant", None)
    write_state(state, where)


def _trial_state(state: dict) -> dict:
    trial = state.get("trial")
    return trial if isinstance(trial, dict) else {}


def allowance(where: Path | None = None) -> dict:
    """The trial's count, for the screen: how many questions are left, if any."""
    state = read_state(where)
    trial = _trial_state(state)
    bundle = _baked_trial()
    limit = int(trial.get("limit") or trial_limit(bundle) or TRIAL_QUESTIONS)
    used = int(trial.get("used") or 0)
    return {"limit": limit, "used": used, "left": max(0, limit - used),
            "available": bool(bundle) and limit > used}


def _granted_values(where: Path | None) -> tuple[dict[str, str], str]:
    """`(keys, source)` — the password grant first, then the trial."""
    state = read_state(where)
    grant = state.get("grant")
    if isinstance(grant, dict) and grant.get("sealed"):
        values = _unwrap(str(grant["sealed"]), where)
        if values:
            return values, "shared"
    if allowance(where)["available"]:
        try:
            return open_trial(_baked_trial()), "trial"
        except ShareError:
            return {}, ""
    return {}, ""


def granted(provider: str, *, where: Path | None = None) -> str:
    """The shared key for this provider, or "" when there is none to use."""
    values, _source = _granted_values(where)
    return str(values.get(provider) or "")


def origin(provider: str, *, where: Path | None = None) -> str:
    """`"shared"` or `"trial"` when this provider's key comes from an access
    code, else "". Both are the owner's keys; only the trial is counted."""
    values, source = _granted_values(where)
    return source if values.get(provider) else ""


def refusal(provider: str, *, where: Path | None = None) -> str:
    """Why there is no shared key, when that is the interesting answer."""
    state = read_state(where)
    grant = state.get("grant")
    if isinstance(grant, dict) and grant.get("sealed") and not _unwrap(str(grant["sealed"]), where):
        return ("The shared access on this computer could not be opened — it was made on "
                "another computer, or the Kriko data folder was copied from one. Paste "
                "the code and password again.")
    trial = allowance(where)
    if trial["used"] and not trial["available"]:
        return (f"The free Kriko Agent trial for this computer is used up "
                f"({trial['used']} of {trial['limit']} questions). Paste an access code "
                "and password, or add your own Mercury and DeepSeek keys in Settings.")
    return ""


def charge(where: Path | None = None) -> int:
    """Count one answered question against the trial. Returns how many are left."""
    state = read_state(where)
    trial = dict(_trial_state(state))
    trial["limit"] = int(trial.get("limit") or TRIAL_QUESTIONS)
    trial["used"] = int(trial.get("used") or 0) + 1
    state["trial"] = trial
    write_state(state, where)
    return max(0, trial["limit"] - trial["used"])


def status(where: Path | None = None) -> dict:
    """What the screen may know: never a key, never a password."""
    state = read_state(where)
    grant = state.get("grant")
    held = isinstance(grant, dict) and bool(grant.get("sealed"))
    providers, source = _granted_values(where)
    return {
        "bound": bound(),
        "device": "dpapi" if sys.platform == "win32" else "file",
        "grant": {"present": held and bool(providers),
                  "label": str((grant or {}).get("label") or ""),
                  "providers": sorted(providers),
                  "state": source},
        "trial": allowance(where),
        "providers": list(SHARED_PROVIDERS),
    }
