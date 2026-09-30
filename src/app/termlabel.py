"""A pack term's English label, read from its stored form (B173)."""

import yaml


def term_label(label_json: str, fallback: str) -> str:
    """The builder stores a term's labels as YAML text (JSON is a subset), so
    it is read as YAML. Anything unreadable falls back to the term's id."""
    try:
        loaded = yaml.safe_load(label_json or "") or {}
    except yaml.YAMLError:
        return fallback
    return str(loaded.get("en") or fallback) if isinstance(loaded, dict) else fallback
