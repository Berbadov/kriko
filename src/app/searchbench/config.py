"""Explicit candidates and dated prices; unknown cost stays unknown."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Model:
    provider: str
    key_env: str
    base_url: str
    model: str
    input_usd: float | None
    cached_usd: float | None
    output_usd: float | None
    effort: str = ""


# USD / million tokens, verified 2026-10-20. Mercury 3 includes launch discount.
# DeepSeek has time-dependent pricing: retain usage rather than guess a rate.
MODELS = {
    "mercury-3": Model("mercury", "MERCURY_API_KEY", "https://api.inceptionlabs.ai/v1", "mercury-3", .10, .01, .35, "instant"),
    "mercury-2.5": Model("mercury", "MERCURY_API_KEY", "https://api.inceptionlabs.ai/v1", "mercury-2.5", .20, .02, .75, "low"),
    "ministral-14b": Model("mistral", "MISTRAL_AGENT_API_KEY", "https://api.mistral.ai/v1", "ministral-14b-2512", .20, .02, .20),
    "ministral-8b": Model("mistral", "MISTRAL_AGENT_API_KEY", "https://api.mistral.ai/v1", "ministral-8b-2512", .15, .015, .15),
    "mistral-large-4": Model("mistral", "MISTRAL_AGENT_API_KEY", "https://api.mistral.ai/v1", "mistral-large-4", .68, .07, 2.09, "none"),
    "deepseek-control": Model("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-flash", None, None, None),
}

SEARCHES = {
    "deepseek-content": ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com", "content"),
    "deepseek-snippets": ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com", "snippets"),
    "exa-lite": ("exa", "EXA_API_KEY", "https://api.exa.ai", "lite"),
    "exa-auto": ("exa", "EXA_API_KEY", "https://api.exa.ai", "auto"),
    "tavily-fast": ("tavily", "TAVILY_API_KEY", "https://api.tavily.com", "fast"),
    "tavily-ultra-fast": ("tavily", "TAVILY_API_KEY", "https://api.tavily.com", "ultra-fast"),
}


PROFILE_LABELS = {
    "m25-deepseek": "Mercury 2.5 · DeepSeek",
    "m3-deepseek": "Mercury 3 · DeepSeek",
    "m8-deepseek": "Ministral 8B · DeepSeek",
    "m14-deepseek": "Ministral 14B · DeepSeek",
    "large4-deepseek": "Large 4 · DeepSeek",
    "m25-exa": "Mercury 2.5 · Exa",
    "m25-tavily": "Mercury 2.5 · Tavily",
    "m25-federated": "Mercury 2.5 · all searches",
    "m25-verify-m3": "DeepSeek · 2.5 → 3",
    "m25-federated-verify-m3": "All searches · 2.5 → 3",
    "m25-parallel": "Mercury 2.5 · parallel",
}
def load_keys(path: Path) -> None:
    """Load only named credentials from an explicitly selected dotenv file."""
    from app.keys import parse

    allowed = {m.key_env for m in MODELS.values()} | {s[1] for s in SEARCHES.values()}
    if sys.platform == "win32":
        # Desktop processes may predate a setx or Settings environment change.
        import winreg

        for hive, location in ((winreg.HKEY_CURRENT_USER, "Environment"),
                               (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, location) as registry:
                    for name in allowed:
                        try:
                            value, _ = winreg.QueryValueEx(registry, name)
                            if isinstance(value, str) and value.strip():
                                os.environ.setdefault(name, value.strip())
                        except OSError:
                            pass
            except OSError:
                pass
    if path.is_file():
        for name, value in parse(path.read_text(encoding="utf-8-sig")).items():
            if name in allowed and value:
                os.environ.setdefault(name, value)


def token_cost(model: Model, usage: dict) -> float | None:
    from app.searchbench.metrics import normalized_usage

    if any(v is None for v in (model.input_usd, model.cached_usd, model.output_usd)):
        return None
    tokens = normalized_usage(usage)
    if tokens["input"] is None or tokens["output"] is None:
        return None
    cached = min(tokens["input"], tokens["cached_input"] or 0)
    return ((tokens["input"] - cached) * model.input_usd
            + cached * model.cached_usd + tokens["output"] * model.output_usd) / 1_000_000
