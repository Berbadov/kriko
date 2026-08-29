"""Source adapter protocol — every source must satisfy this interface."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Document:
    text: str
    url: str
    site_or_channel: str
    meta: dict = field(default_factory=dict)  # e.g. {"model_hint": "Megane IV", "engine_hint": "K9K"}


class Source(Protocol):
    def fetch(self, make: str, model: str) -> list[Document]:
        """Fetch documents for (make, model). Must be fault-tolerant — never raise."""
        ...
