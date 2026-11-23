"""Parser registry — swap or extend languages without touching other layers."""

from __future__ import annotations

from codex_cartographer.ingestion.walker import SourceFile
from codex_cartographer.parsers.base import LanguageParser, ModuleUnit, ParseResult
from codex_cartographer.parsers.generic_parser import GenericRegexParser
from codex_cartographer.parsers.js_ts_parser import JavaScriptTypeScriptParser
from codex_cartographer.parsers.python_parser import PythonParser

_PARSERS: list[LanguageParser] = [
    PythonParser(),
    JavaScriptTypeScriptParser(),
    # Regex-backed fallback for C/C++/C#/Java/Kotlin/Swift/Go/Rust/PHP/Ruby/R/Julia/MATLAB
    GenericRegexParser(),
]

_BY_LANGUAGE: dict[str, LanguageParser] = {}


def _index_parser(parser: LanguageParser) -> None:
    _BY_LANGUAGE[parser.language] = parser
    for ext_lang in getattr(parser, "also_handles", ()):
        _BY_LANGUAGE[ext_lang] = parser


for _parser in _PARSERS:
    _index_parser(_parser)


def get_parser(language: str) -> LanguageParser | None:
    """Return the registered parser for *language*, or None."""
    return _BY_LANGUAGE.get(language)


def supported_languages() -> dict[str, str]:
    """Map language → backend name (for ``--list-languages``)."""
    out: dict[str, str] = {}
    for lang, parser in sorted(_BY_LANGUAGE.items()):
        out[lang] = type(parser).__name__
    return out


def register_parser(parser: LanguageParser) -> None:
    """Register an additional language parser at runtime."""
    _PARSERS.append(parser)
    _index_parser(parser)


def parse_source_file(source: SourceFile) -> ParseResult:
    """
    Dispatch *source* to the right parser.

    Unknown languages become unparsed modules (graceful degradation).
    """
    parser = get_parser(source.language)
    if parser is None:
        module = ModuleUnit(
            file=source.relative_path,
            language=source.language,
            parse_error=f"No parser registered for language: {source.language}",
            raw_content=source.content,
        )
        return ParseResult(module=module, success=False)
    return parser.parse(source.content, source.relative_path)
