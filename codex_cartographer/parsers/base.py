"""
Language-agnostic parse units.

Parsers never build the final graph. They only extract structured facts
that the semantic-model layer turns into nodes and edges.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImportRef:
    """An import statement discovered in a module."""

    module: str
    names: list[str] = field(default_factory=list)
    alias: str | None = None
    line: int = 0
    is_relative: bool = False


@dataclass
class CallRef:
    """A function/method call site."""

    callee: str
    line: int = 0
    argument_names: list[str] = field(default_factory=list)


@dataclass
class VariableUnit:
    """A notable variable (module-level or parameter-adjacent)."""

    name: str
    line: int = 0
    annotation: str | None = None
    assigned_from: str | None = None  # RHS name, if simple


@dataclass
class FunctionUnit:
    """A function or method."""

    name: str
    qualified_name: str
    line_start: int
    line_end: int
    snippet: str
    parameters: list[str] = field(default_factory=list)
    returns: list[str] = field(default_factory=list)  # simple return names
    calls: list[CallRef] = field(default_factory=list)
    assignments: list[VariableUnit] = field(default_factory=list)
    is_method: bool = False
    is_async: bool = False
    decorators: list[str] = field(default_factory=list)


@dataclass
class ClassUnit:
    """A class definition."""

    name: str
    qualified_name: str
    line_start: int
    line_end: int
    snippet: str
    bases: list[str] = field(default_factory=list)
    methods: list[FunctionUnit] = field(default_factory=list)
    attributes: list[VariableUnit] = field(default_factory=list)


@dataclass
class ModuleUnit:
    """Top-level facts for one source file."""

    file: str
    language: str
    docstring: str | None = None
    imports: list[ImportRef] = field(default_factory=list)
    classes: list[ClassUnit] = field(default_factory=list)
    functions: list[FunctionUnit] = field(default_factory=list)
    variables: list[VariableUnit] = field(default_factory=list)
    instantiations: list[CallRef] = field(default_factory=list)  # ClassName(...)
    top_level_calls: list[CallRef] = field(default_factory=list)  # script-level calls
    has_main_guard: bool = False
    parse_error: str | None = None
    raw_content: str = ""


@dataclass
class ParseResult:
    """Outcome of parsing one file (success or graceful failure)."""

    module: ModuleUnit
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Debug helper — not the canonical graph format."""
        return {
            "file": self.module.file,
            "language": self.module.language,
            "success": self.success,
            "parse_error": self.module.parse_error,
            "imports": len(self.module.imports),
            "classes": len(self.module.classes),
            "functions": len(self.module.functions),
        }


class LanguageParser(ABC):
    """Pluggable parser interface. Implement this to add a language."""

    language: str
    extensions: tuple[str, ...]

    @abstractmethod
    def parse(self, content: str, relative_path: str) -> ParseResult:
        """Parse *content* into a ModuleUnit. Must not raise on bad input."""
