"""Where a reader's API keys live, and what may be said about them.

Kriko's default plane costs nothing and needs no key. The paid plane needs two,
and until now the only way to supply them was to set an environment variable
before launching — which for a double-clicked desktop app means "impossible".
So there is a file:

    ~/.kriko/env          KEY=value, one per line, mode 0600

**Loaded into `os.environ` at startup, before anything reads a key.** That is
the design decision that keeps everything downstream simple: a provider adapter
calls `os.environ.get`, exactly as it did when the only way in was a shell, and
neither the adapters nor the pack pipeline need to know this file exists. It
also means the precedence falls out for free — `load` never overwrites a
variable that is already set, so **a real environment variable always wins**.
Someone running the app from a shell with `EXA_API_KEY` exported gets that key,
and the settings screen reports the source as `environment` rather than
pretending the file is in charge.

**Not the OS keychain**, and that is a judgement rather than an oversight.
Keychain access costs a `keyring` dependency plus a Linux fallback for machines
with no Secret Service, and it would sit next to `~/.kriko/knowledge.sqlite` —
a file already readable by anything running as this user. Mode 0600 beside an
already-readable store is the honest threat model: it stops another *account*
on a shared machine, which is the threat this actually has, and it does not
claim to stop a process running as the reader.

**Nothing here returns a key.** `status()` answers presence and the last four
characters, and that is the only shape any interface gets. A settings screen
that could read a key back is a settings screen that can leak one to a browser
history, a screenshot or a support log, and there is no feature that needs it:
replacing a key you cannot see costs one paste.
"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.web.settings import KRIKO_HOME


@dataclass(frozen=True)
class Provider:
    """One key a reader can set, and what setting it enables.

    `purpose` is the sentence the settings screen shows, and it is here rather
    than in the UI because it is a promise about what leaves this machine — it
    must be written once, next to the thing that makes it true.
    """

    id: str
    label: str
    env: str
    purpose: str
    #: True when the paid plane runs without it. `ready()` is "can the paid
    #: plane run at all", and a *second* search provider is a choice rather
    #: than a requirement — demanding both keys would make adding a provider a
    #: way to break an installation that was working.
    optional: bool = False


#: The providers this app knows how to spend at. A list, not a free-form
#: dictionary of environment variable names: an endpoint that let a caller
#: write any `KEY=value` into a file the process later loads into its own
#: environment would be an arbitrary-environment-variable write, reachable from
#: a browser on localhost. Two named providers is the whole feature.
PROVIDERS = (
    Provider(
        id="exa",
        label="Exa",
        env="EXA_API_KEY",
        purpose="Receives your search queries — the words built from a "
        "subject's own attributes. Never a page you visited and never a "
        "listing URL.",
    ),
    Provider(
        id="tavily",
        label="Tavily",
        env="TAVILY_API_KEY",
        purpose="The other search provider. Receives the same queries Exa "
        "would — words built from a subject's own attributes. Never a page you "
        "visited and never a listing URL. Set either one; Settings picks which "
        "is used.",
        optional=True,
    ),
    Provider(
        id="openai",
        label="OpenAI (or any OpenAI-compatible endpoint)",
        env="OPENAI_API_KEY",
        purpose="Receives the text of the pages research fetched, and returns "
        "the claims it can quote from them. Never your browsing history.",
    ),
    Provider(
        id="anthropic",
        label="Anthropic",
        env="ANTHROPIC_API_KEY",
        purpose="The other completion provider. Receives the text of the "
        "pages research fetched, and returns the claims it can quote from "
        "them. Never your browsing history. Set either this or OpenAI; "
        "Settings picks which model is used, and it can differ per stage of "
        "a run.",
        optional=True,
    ),
    Provider(
        id="mistral",
        label="Mistral",
        env="MISTRAL_API_KEY",
        purpose="Runs the Mistral API agent: receives each run's brief — the "
        "product's name and what its listing says about it — and searches the "
        "web for it with Mistral's own search. Also a completion model for the "
        "paid plane. Never your browsing history. One key does both.",
        optional=True,
    ),
)

BY_ID = {provider.id: provider for provider in PROVIDERS}

#: The providers that answer "search the web", in the order preferred when the
#: reader has not chosen. A closed engineering vocabulary — these are integrations
#: this app has code for, not data that grows with pack coverage.
SEARCH_PROVIDERS = ("exa", "tavily")

#: The providers that answer "read this text and tell me what it supports".
#: Same shape as SEARCH_PROVIDERS and for the same reason: once there are two,
#: having one of them is enough, and requiring both would make adding a choice
#: a way to break an installation that was working.
COMPLETION_PROVIDERS = ("openai", "anthropic", "mistral")


def env_path(home: Path | None = None) -> Path:
    return (home or KRIKO_HOME) / "env"


def load(path: Path | None = None, environ: dict | None = None) -> list[str]:
    """Put the file's keys into the environment, and say which ones landed.

    Never overwrites: see the module docstring on precedence. Returns the
    variable names it set, so a startup log can say *how many* keys were
    loaded without saying what any of them is.
    """
    target = environ if environ is not None else os.environ
    file = path or env_path()
    set_now = []
    for name, value in parse(_read(file)).items():
        if name not in target:
            target[name] = value
            set_now.append(name)
    return set_now


def parse(text: str) -> dict[str, str]:
    """`KEY=value` lines into a dict, tolerantly.

    `#` comments, blank lines, `export ` prefixes and surrounding quotes are
    all accepted, because the file people will paste into this is the file they
    already know from every other tool. A line without `=` is skipped rather
    than raising: one bad line must not cost the other key.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name:
            out[name] = value
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def hint(value: str) -> str:
    """The most that may be shown of a key: its last four characters.

    Four is enough to tell two keys apart when replacing one and not enough to
    be worth capturing. A short value is shown as a length, never truncated to
    something guessable.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return "…" + value[-4:]


def status(path: Path | None = None, environ: dict | None = None) -> list[dict]:
    """Presence, source and hint for every known provider. Never a key.

    The shape an interface gets. `source` matters because it is the difference
    between "your paste took effect" and "something in your shell is
    overriding it", and a reader with an exported variable who cannot see that
    would replace the file's key repeatedly and watch nothing change.
    """
    target = environ if environ is not None else os.environ
    stored = parse(_read(path or env_path()))
    out = []
    for provider in PROVIDERS:
        live = str(target.get(provider.env) or "").strip()
        saved = str(stored.get(provider.env) or "").strip()
        # `environment` only when the two genuinely differ or nothing is
        # stored: after `load`, the file's key *is* the environment variable,
        # and calling that "environment" would hide the file the reader edited.
        source = ""
        if live and (not saved or live != saved):
            source = "environment"
        elif saved:
            source = "file"
        out.append(
            {
                "id": provider.id,
                "label": provider.label,
                "env": provider.env,
                "purpose": provider.purpose,
                "present": bool(live or saved),
                "hint": hint(live or saved),
                "source": source,
            }
        )
    return out


def ready(path: Path | None = None, environ: dict | None = None, *,
          provider: str = "") -> bool:
    """Can the paid plane run at all?

    It searches *and* reads, so it needs a search key **and** a completion key.
    Half-configured is not a degraded mode, it is a run that fails on its first
    document, and the API card stays inert until both are there.

    Both halves are a *choice* rather than a name: Exa or Tavily; OpenAI,
    Anthropic or Mistral. Requiring every one of a group would make adding a second
    provider a way to break an installation that was working — the opposite of
    what a choice is for. Anything outside the two pairs and not optional is
    still required outright.

    `provider` narrows the completion half to the one the run's model needs
    (`prefs.paid_plane_ready`). Any key is the right answer for "are the keys
    in", and the wrong one for "will a run work": a Mistral key saved for the
    API agent made a plane on OpenAI's default model look runnable (B153).
    """
    rows = {item["id"]: item["present"] for item in status(path, environ)}
    searchers = [rows.get(one, False) for one in SEARCH_PROVIDERS]
    completers = [rows.get(one, False) for one in ((provider,) if provider else COMPLETION_PROVIDERS)]
    required = [
        rows.get(provider.id, False)
        for provider in PROVIDERS
        if provider.id not in SEARCH_PROVIDERS
        and provider.id not in COMPLETION_PROVIDERS
        and not provider.optional
    ]
    return any(searchers) and any(completers) and all(required)


def search_providers(path: Path | None = None, environ: dict | None = None) -> list[str]:
    """Which search providers this installation could actually use, in order.

    Preference is the reader's (`app.sqlite` settings, read by
    `app/providers/__init__.py`); this is only what is *possible*, which is a
    question about keys.
    """
    rows = {item["id"]: item["present"] for item in status(path, environ)}
    return [one for one in SEARCH_PROVIDERS if rows.get(one)]


def save(values: dict, path: Path | None = None) -> list[str]:
    """Write the given providers' keys to `~/.kriko/env`, mode 0600.

    Only the providers named in `PROVIDERS` — see the note there on why this is
    not a general-purpose environment writer. An empty or missing value leaves
    the stored key alone; **clearing is `remove`**, so a settings form that
    submits blank fields for keys it never showed cannot wipe them.

    The write is atomic and the mode is set on the temporary file *before* the
    content goes in, because a key that exists at 0644 for even a moment has
    already been readable.
    """
    file = path or env_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    stored = parse(_read(file))
    written = []
    for key, value in (values or {}).items():
        provider = BY_ID.get(str(key).strip().lower())
        value = str(value or "").strip()
        if provider is None or not value:
            continue
        stored[provider.env] = value
        written.append(provider.id)
    _write(file, stored)
    return written


def remove(provider_id: str, path: Path | None = None) -> bool:
    """Forget one provider's key. True if there was one to forget."""
    provider = BY_ID.get(str(provider_id).strip().lower())
    if provider is None:
        return False
    file = path or env_path()
    stored = parse(_read(file))
    if provider.env not in stored:
        return False
    del stored[provider.env]
    _write(file, stored)
    # The process's own environment too: a key removed in Settings that the
    # next research run still spends with is not removed.
    os.environ.pop(provider.env, None)
    return True


def _write(path: Path, values: dict[str, str]) -> None:
    body = "".join(f"{name}={value}\n" for name, value in sorted(values.items()))
    temporary = path.with_suffix(".tmp")
    handle = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
    )
    with open(handle, "w", encoding="utf-8") as stream:
        stream.write(body)
    os.replace(temporary, path)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows has no mode bits to set; the ACL is the account's own


def require(provider_id: str) -> str:
    """The key for one provider, or refuse to build a plane without it.

    The one function that returns a key, and it returns it to a provider
    adapter in the same process — never through an endpoint. `MissingKey`
    rather than an empty string so the failure is a screen the reader can act
    on instead of a 401 from a vendor.
    """
    from app.providers import MissingKey

    provider = BY_ID.get(str(provider_id).strip().lower())
    if provider is None:
        raise MissingKey(f"unknown provider {provider_id!r}")
    value = str(os.environ.get(provider.env) or "").strip()
    if not value:
        value = str(parse(_read(env_path())).get(provider.env) or "").strip()
    if not value:
        raise MissingKey(
            f"{provider.label} needs a key — set one in Settings → Research "
            f"(or export {provider.env})"
        )
    return value
