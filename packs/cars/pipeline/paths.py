"""Filesystem locations owned by the cars research pipeline."""

from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
PACK_ROOT = PIPELINE_ROOT.parent
REPO_ROOT = PACK_ROOT.parent.parent
DATA_DIR = PACK_ROOT / "data"
CACHE_DIR = PIPELINE_ROOT / "cache"
CURATED_DIR = PIPELINE_ROOT / "sources" / "curated"
EXPORT_DIR = PIPELINE_ROOT / "ledger_export"
GOLD_PATH = PIPELINE_ROOT / "gold" / "gold.yaml"
