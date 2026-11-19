"""Domain model for todo items."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class Entity:
    """Base record with a numeric identity."""

    id: int

    def identity(self) -> str:
        return f"#{self.id}"


@dataclass
class Todo(Entity):
    """A single todo item."""

    title: str = ""
    done: bool = False
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def mark_done(self) -> None:
        """Flip the completion flag."""
        self.done = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Todo:
        return cls(
            id=int(data["id"]),
            title=str(data["title"]),
            done=bool(data.get("done", False)),
            created_at=str(data.get("created_at", "")),
        )
