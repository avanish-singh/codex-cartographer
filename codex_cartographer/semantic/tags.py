"""Heuristic semantic tagging — no config files in v1."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from codex_cartographer.parsers.base import ModuleUnit
from codex_cartographer.semantic.model import (
    TAG_CORE,
    TAG_ENTRY,
    TAG_EXTERNAL,
    TAG_IO,
    TAG_TEST,
    TAG_UNPARSED,
    TAG_UTILITY,
    GraphNode,
    KIND_EXTERNAL,
    KIND_FUNCTION,
    KIND_MODULE,
    KIND_UNPARSED,
)

# Libraries that typically mark I/O boundaries.
IO_LIBRARIES = {
    # Python
    "os",
    "sys",
    "pathlib",
    "io",
    "json",
    "csv",
    "sqlite3",
    "http",
    "urllib",
    "requests",
    "aiohttp",
    "flask",
    "fastapi",
    "django",
    "socket",
    "subprocess",
    "logging",
    "argparse",
    "click",
    "typer",
    # JS/TS
    "fs",
    "path",
    "http",
    "https",
    "net",
    "child_process",
    "express",
    "axios",
    "node:fs",
    "node:path",
    "node:http",
    "readline",
    # C / C++ / Java / Go / Rust / MATLAB
    "stdio",
    "stdio.h",
    "iostream",
    "fstream",
    "cstdio",
    "unistd.h",
    "fcntl.h",
    "sys/socket.h",
    "java.io",
    "java.net",
    "java.nio",
    "fmt",
    "bufio",
    "net/http",
    "std::io",
    "std::fs",
    "std::net",
    "System.IO",
}

# MATLAB/Octave/R/Julia mark I/O via calls rather than imports.
IO_CALL_HINTS = {
    "fprintf", "disp", "load", "save", "readtable", "csvread", "xlsread", "fopen",
    "imread", "saveas", "plot", "figure", "print", "printf", "scanf", "fscanf",
    "read.csv", "write.csv", "readRDS", "println", "cout", "cin",
}

UTILITY_NAME_RE = re.compile(
    r"(util|utils|helper|helpers|common|shared|lib|format|parse|string|array)",
    re.I,
)
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(\.|_)(test|spec)\.(py|jsx?|tsx?)$",
    re.I,
)


def module_tags(module: ModuleUnit) -> list[str]:
    """Tags for a whole module node."""
    tags: list[str] = []
    path = module.file.replace("\\", "/")

    if module.parse_error and not (module.functions or module.classes):
        tags.append(TAG_UNPARSED)

    if TEST_PATH_RE.search(path):
        tags.append(TAG_TEST)

    if module.has_main_guard:
        tags.append(TAG_ENTRY)

    # main.py / index.js / cli.py / main.c heuristics
    stem = PurePosixPath(path).name.lower()
    if stem in {
        "main.py", "cli.py", "app.py", "index.js", "index.ts", "main.js", "main.ts",
        "main.c", "main.cpp", "main.cc", "main.go", "main.rs", "main.java", "program.cs",
        "main.m", "run.m", "app.r", "main.jl",
    }:
        if TAG_ENTRY not in tags:
            tags.append(TAG_ENTRY)

    if _module_touches_io(module):
        tags.append(TAG_IO)

    if UTILITY_NAME_RE.search(path):
        tags.append(TAG_UTILITY)
    elif TAG_TEST not in tags and TAG_ENTRY not in tags and TAG_UNPARSED not in tags:
        tags.append(TAG_CORE)

    return tags


def function_tags(module: ModuleUnit, func_name: str, file_tags: list[str]) -> list[str]:
    """Tags for a function / method node."""
    tags: list[str] = []
    if TAG_TEST in file_tags or func_name.startswith("test_") or func_name.endswith("_test"):
        tags.append(TAG_TEST)
    if func_name in {"main", "cli", "run", "app"} or (
        module.has_main_guard and func_name == "main"
    ):
        tags.append(TAG_ENTRY)
    if UTILITY_NAME_RE.search(func_name):
        tags.append(TAG_UTILITY)
    if TAG_IO in file_tags:
        # Functions in I/O modules inherit a soft I/O tag.
        tags.append(TAG_IO)
    if not tags:
        tags.append(TAG_CORE if TAG_CORE in file_tags else TAG_UTILITY)
    return tags


def apply_node_kind_tags(node: GraphNode) -> None:
    """Ensure kind-level tags are present."""
    if node.kind == KIND_EXTERNAL and TAG_EXTERNAL not in node.tags:
        node.tags.append(TAG_EXTERNAL)
    if node.kind == KIND_UNPARSED and TAG_UNPARSED not in node.tags:
        node.tags.append(TAG_UNPARSED)
    if node.kind == KIND_MODULE and not node.tags:
        node.tags.append(TAG_CORE)
    if node.kind == KIND_FUNCTION and not node.tags:
        node.tags.append(TAG_CORE)


def _module_touches_io(module: ModuleUnit) -> bool:
    for imp in module.imports:
        root = imp.module.split("/")[0].split(".")[0]
        # strip node: prefix
        root = root.replace("node:", "")
        if root in IO_LIBRARIES or imp.module in IO_LIBRARIES:
            return True
        for name in imp.names:
            if name.split(".")[0] in IO_LIBRARIES:
                return True
    # Call-based hints (MATLAB/Octave/R/Julia/C have no import for stdio-ish I/O).
    all_funcs = list(module.functions)
    for cls in module.classes:
        all_funcs.extend(cls.methods)
    for func in all_funcs:
        for call in func.calls:
            if call.callee.split(".")[-1] in IO_CALL_HINTS or call.callee in IO_CALL_HINTS:
                return True
    return False
