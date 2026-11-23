"""Command-line entry point for the sample todo app."""

from __future__ import annotations

import argparse
import sys

from todo.formatters import format_list
from todo.models import Todo
from todo.store import TodoStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo", description="Tiny todo CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Add a todo")
    add.add_argument("title", help="Todo title")

    sub.add_parser("list", help="List todos")

    done = sub.add_parser("done", help="Mark a todo done")
    done.add_argument("id", type=int, help="Todo id")

    return parser


def cmd_add(store: TodoStore, title: str) -> int:
    todos = store.load()
    todo = Todo(id=store.next_id(todos), title=title)
    todos.append(todo)
    store.save(todos)
    print(f"Added #{todo.id}: {todo.title}")
    return 0


def cmd_list(store: TodoStore) -> int:
    todos = store.load()
    print(format_list(todos))
    return 0


def cmd_done(store: TodoStore, todo_id: int) -> int:
    todos = store.load()
    for todo in todos:
        if todo.id == todo_id:
            todo.mark_done()
            store.save(todos)
            print(f"Done #{todo.id}")
            return 0
    print(f"No todo with id {todo_id}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = TodoStore()
    if args.command == "add":
        return cmd_add(store, args.title)
    if args.command == "list":
        return cmd_list(store)
    if args.command == "done":
        return cmd_done(store, args.id)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
