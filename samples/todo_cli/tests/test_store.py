"""Tests for the sample todo store (also exercises the 'test' semantic tag)."""

from pathlib import Path

from todo.models import Todo
from todo.store import TodoStore


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "todos.json"
    store = TodoStore(path)
    todos = [Todo(id=1, title="Chart the codebase")]
    store.save(todos)
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].title == "Chart the codebase"
