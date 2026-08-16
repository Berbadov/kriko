"""Small shared helpers for reading YAML files at C speed (libyaml when present).

The catalog YAML (backend/data/parts/**) is parsed on hot paths — the hub's
state poll and stoplist derivation in stoplists.py. Using CSafeLoader instead
of the pure-Python safe_load is ~13x faster and never changes the parsed
value, only the speed. Callers needing the "empty mapping on rougher input"
behaviour get it from the single loader below instead of re-implementing the
try/except at every call site.
"""

import yaml
from pathlib import Path


def load_yaml(path: Path) -> dict:
    """Parse ``path`` into a dict, tolerantly.

    Returns ``{}`` for an unreadable/malformed document or a non-mapping top
    level; otherwise the parsed mapping. The loader choice (CSafeLoader when
    libyaml is installed, else SafeLoader) changes only speed, not values.
    """
    loader = getattr(yaml, "CSafeLoader", None) or yaml.SafeLoader
    try:
        data = yaml.load(path.read_text(), Loader=loader)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}
