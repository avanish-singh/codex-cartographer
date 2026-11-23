"""Recursively collect source files while honoring .gitignore rules."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pathspec

# Extensions with dedicated AST/tree-sitter parsers.
SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# Regex-backed languages (C/C++/C#/Java/Kotlin/Swift/Go/Rust/PHP/Ruby/R/Julia/MATLAB).
try:  # keep ingestion importable even if the parser package changes
    from codex_cartographer.parsers.generic_parser import GENERIC_EXTENSIONS

    for _ext, _lang in GENERIC_EXTENSIONS.items():
        SUPPORTED_EXTENSIONS.setdefault(_ext, _lang)
except Exception:  # noqa: BLE001
    pass

# Skip files bigger than this (minified bundles, generated code, data blobs).
MAX_FILE_BYTES = 1_500_000

# Always skip these directories even without a .gitignore.
DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".next",
    "coverage",
    "output",
}


@dataclass(frozen=True)
class SourceFile:
    """A single source file discovered during ingestion."""

    path: Path
    relative_path: str
    language: str
    content: str


def _load_gitignore(root: Path) -> pathspec.PathSpec | None:
    """Load .gitignore patterns from *root*, if present."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return None
    lines = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _is_ignored(
    rel_posix: str,
    is_dir: bool,
    spec: pathspec.PathSpec | None,
) -> bool:
    if spec is None:
        return False
    # pathspec matches files; directories often need a trailing slash.
    candidates = [rel_posix]
    if is_dir and not rel_posix.endswith("/"):
        candidates.append(rel_posix + "/")
    return any(spec.match_file(c) for c in candidates)


def collect_source_files(
    root: str | Path,
    *,
    extra_skip_dirs: Iterable[str] | None = None,
) -> list[SourceFile]:
    """
    Walk *root* (file or directory) and return parseable source files.

    Respects .gitignore at the root and skips common build/cache directories.
    Unreadable files are skipped rather than raising.
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Path does not exist: {root_path}")

    skip_dirs = set(DEFAULT_SKIP_DIRS)
    if extra_skip_dirs:
        skip_dirs.update(extra_skip_dirs)

    # Single file mode.
    if root_path.is_file():
        language = SUPPORTED_EXTENSIONS.get(root_path.suffix.lower())
        if language is None:
            return []
        try:
            content = root_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [
            SourceFile(
                path=root_path,
                relative_path=root_path.name,
                language=language,
                content=content,
            )
        ]

    spec = _load_gitignore(root_path)
    collected: list[SourceFile] = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        current = Path(dirpath)
        # Prune directories in-place so os.walk does not descend.
        kept: list[str] = []
        for name in dirnames:
            if name in skip_dirs:
                continue
            child = current / name
            try:
                rel = child.relative_to(root_path).as_posix()
            except ValueError:
                continue
            if _is_ignored(rel, True, spec):
                continue
            kept.append(name)
        dirnames[:] = kept

        for filename in filenames:
            file_path = current / filename
            language = SUPPORTED_EXTENSIONS.get(file_path.suffix.lower())
            if language is None:
                continue
            try:
                rel = file_path.relative_to(root_path).as_posix()
            except ValueError:
                continue
            if _is_ignored(rel, False, spec):
                continue
            # Skip our own package when mapping an enclosing folder accidentally.
            if "codex_cartographer" in rel.split("/"):
                continue
            try:
                if file_path.stat().st_size > MAX_FILE_BYTES:
                    continue
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "\x00" in content[:4096]:  # binary masquerading as source
                continue
            collected.append(
                SourceFile(
                    path=file_path,
                    relative_path=rel,
                    language=language,
                    content=content,
                )
            )

    collected.sort(key=lambda f: f.relative_path)
    return collected
