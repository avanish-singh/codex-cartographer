"""Formatting helpers for CLI output."""

from __future__ import annotations

from todo.models import Todo


def format_todo(todo: Todo) -> str:
    """Render one todo as a single line."""
    mark = "x" if todo.done else " "
    return f"[{mark}] #{todo.id} {todo.title}"


def format_list(todos: list[Todo]) -> str:
    """Render a collection of todos."""
    if not todos:
        return "(no todos yet)"
    return "\n".join(format_todo(t) for t in todos)
