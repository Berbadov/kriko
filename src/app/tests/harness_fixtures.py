"""Captured descriptors for parser tests of CLIs outside the desktop roster.

These do not register agents. The supported roster is tested separately;
historical output/parser fixtures should not depend on a UI offering a CLI.
"""
import os

from app.providers import harness

CAPTURED = (
harness.Harness(
        "opencode",
        "opencode",
        "opencode",
        ("run", "--agent", "kriko-harness"),
        download_url="https://opencode.ai/download",
        needs_account="a model account or API key of your own (or a free/local model)",
        structured=False,
        model_flag="--model",
        model_unlisted=True,
        model_source="models",
        model_hint="provider/name, as `opencode models` lists them",
        # The bash installer is the right line on macOS and Linux and is not
        # runnable on the reader's machine, which is Windows. A hint nobody
        # can paste is a hint that teaches the reader the screen is decorative.
        install_hint=(
            "npm install -g opencode-ai"
            if os.name == "nt"
            else "curl -fsSL https://opencode.ai/install | bash"
        ),
        # Its own installer puts the binary in `~/.opencode/bin`, and Windows
        # installs land under `%LOCALAPPDATA%\Programs\opencode`. Neither is
        # on the `PATH` a desktop shell inherits at login — which is the whole
        # reason `locate` looks past `PATH` at all.
        # Its own installer puts the binary in `~/.opencode/bin`, and npm's
        # global install puts a shim in `%APPDATA%\npm`. Neither is on the
        # `PATH` a desktop shell inherits at login, which is the whole reason
        # `locate` looks past `PATH`.
        #
        # **`AppData/Local/Programs` is deliberately not here, and the default
        # list is why this row needs its own.** Windows paths are
        # case-insensitive, so that directory matched
        # `…/Programs/OpenCode/OpenCode.exe` — an unrelated Electron
        # application with the same name — and Kriko then ran a GUI app with
        # `--help` and waited for it. A fallback guess that is wrong must cost
        # nothing, and a guess that matches the wrong binary costs everything.
        homes=(
            ".opencode/bin",
            ".local/bin",
            "AppData/Roaming/npm",
            ".npm-global/bin",
            "node_modules/.bin",
            "bin",
        ),
    ),
harness.Harness(
        "github-copilot", "GitHub Copilot CLI", "copilot",
        ("--output-format", "json", "--allow-all-tools", "--no-ask-user",
         "--available-tools", "web_fetch",
         "--disable-builtin-mcps", "--no-custom-instructions",
         "--no-auto-update", "--no-color", "--log-level", "none"),
        download_url="https://docs.github.com/copilot/how-tos/copilot-cli",
        install_hint=(
            "winget install GitHub.Copilot"
            if os.name == "nt"
            else "npm install -g @github/copilot"
        ),
        needs_account="a GitHub Copilot subscription; run `copilot login` once first",
        protocol="copilot", prompt_argument=False, prompt_flag="-p",
        required=("--output-format", "--allow-all-tools", "--available-tools"),
        model_flag="--model", model_unlisted=True, model_source="help",
        model_hint=(
            "a model id your Copilot plan includes — it refuses an unavailable "
            "one by name before spending anything"
        ),
        effort_flag="--effort",
        effort_choices=("low", "medium", "high", "xhigh"),
        effort_hint="reasoning effort — `copilot --help` names these four",
        capabilities=("headless", "streaming", "web-fetch", "model-selection"),
        contract_note=(
            "\n**This agent has no web search tool — only `web_fetch`.** Where "
            "the brief says to search, fetch a search engine's own results page "
            "instead (a plain HTML endpoint, not a JavaScript one), read the "
            "links off it, and fetch the pages worth reading. Everything else "
            "about the contract above is unchanged: report what you actually "
            "read, quote it verbatim, and invent nothing.\n"
        ),
        # winget puts the shim under `Links`, the payload under `Packages`,
        # and npm's global install somewhere else again. None of the three is
        # reliably on the `PATH` a desktop shell inherits at login.
        homes=(
            "AppData/Local/Microsoft/WinGet/Links",
            "AppData/Local/copilot/bin",
            "AppData/Roaming/npm",
            ".npm-global/bin",
            "node_modules/.bin",
            ".local/bin",
            "bin",
        ),
    ),
)


def row(ident):
    return next(one for one in (*harness.KNOWN, *CAPTURED) if one.id == ident)
