"""Source adapter protocol — every source must satisfy this interface."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Tier(str, Enum):
    A = "A"   # specialist repair/technical — highest weight
    B = "B"   # owner/engine forums — medium weight
    C = "C"   # YouTube transcripts, blogs — lowest weight; never served uncorroborated


@dataclass
class Document:
    text: str
    url: str
    tier: Tier
    site_or_channel: str
    meta: dict = field(default_factory=dict)  # e.g. {"model_hint": "Megane IV", "engine_hint": "K9K"}


class Source(Protocol):
    tier: Tier

    def fetch(self, make: str, model: str) -> list[Document]:
        """Fetch documents for (make, model). Must be fault-tolerant — never raise."""
        ...
