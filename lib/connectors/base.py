"""Source connector abstraction. Each connector fetches Posts for a query."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class Post:
    id: str
    source: str
    text: str
    author: str | None = None
    url: str | None = None
    ts: int = 0
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Connector(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, query: str, limit: int = 50) -> list[Post]:
        ...
