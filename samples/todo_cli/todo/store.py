"""JSON-backed persistence for todos (I/O boundary)."""

from __future__ import annotations

import json
from pathlib import Path

from todo.models import Todo


class TodoStore:
    """Load and save todos from a JSON file."""

    def __init__(self, path: str | Path = "todos.json") -> None:
        self.path = Path(path)

    def load(self) -> list[Todo]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Todo.from_dict(item) for item in raw]

    def save(self, todos: list[Todo]) -> None:
        payload = [t.to_dict() for t in todos]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def next_id(self, todos: list[Todo]) -> int:
        if not todos:
            return 1
        return max(t.id for t in todos) + 1
