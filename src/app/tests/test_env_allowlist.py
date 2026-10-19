"""The keys file may set the variables this app knows, and no others.

`PROVIDERS` is the allowlist, and the module docstring says what it is for: "an
endpoint that let a caller write any `KEY=value` into a file the process later
loads into its own environment would be an arbitrary-environment-variable
write". `save` enforced that list. `load` did not — it copied every name it
parsed, so `~/.kriko/env` could carry `PYTHONPATH`, `LD_PRELOAD` or
`NODE_OPTIONS` into every child process the app starts. The file is the
reader's own, which is why this is a boundary rather than an attack; it is the
boundary the module claims to have.
"""

from app import keys


def test_only_a_known_variable_is_loaded(tmp_path):
    path = tmp_path / "env"
    path.write_text(
        "EXA_API_KEY=exa-key\n"
        "PYTHONPATH=/tmp/evil\n"
        "NODE_OPTIONS=--require /tmp/evil.js\n"
        "LD_PRELOAD=/tmp/evil.so\n",
        encoding="utf-8",
    )
    environ: dict[str, str] = {}
    assert keys.load(path, environ) == ["EXA_API_KEY"]
    assert environ == {"EXA_API_KEY": "exa-key"}


def test_every_declared_provider_is_still_loaded(tmp_path):
    path = tmp_path / "env"
    path.write_text(
        "".join(f"{provider.env}=k-{provider.id}\n" for provider in keys.PROVIDERS),
        encoding="utf-8",
    )
    environ: dict[str, str] = {}
    assert set(keys.load(path, environ)) == {p.env for p in keys.PROVIDERS}


def test_a_real_environment_variable_still_wins(tmp_path):
    """The documented precedence: someone running from a shell keeps their key."""
    path = tmp_path / "env"
    path.write_text("EXA_API_KEY=from-file\n", encoding="utf-8")
    environ = {"EXA_API_KEY": "from-shell"}
    assert keys.load(path, environ) == []
    assert environ["EXA_API_KEY"] == "from-shell"
