"""
Regex-driven parser for languages without a dedicated AST backend.

Covers C, C++, C#, Java, Kotlin, Swift, Go, Rust, PHP, Ruby, R, Julia and
MATLAB/Octave. Precision is lower than ``ast``/tree-sitter, but every
file becomes a module node with functions, classes, imports and calls so
large mixed-language projects still map end-to-end.

Adding a language = adding a ``LanguageSpec`` to ``LANGUAGE_SPECS``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from codex_cartographer.parsers.base import (
    CallRef,
    ClassUnit,
    FunctionUnit,
    ImportRef,
    LanguageParser,
    ModuleUnit,
    ParseResult,
    VariableUnit,
)

# Words that look like calls/functions but are not.
_KEYWORDS = {
    "if", "else", "for", "while", "do", "switch", "case", "return", "sizeof",
    "typedef", "struct", "union", "enum", "class", "namespace", "using",
    "new", "delete", "throw", "try", "catch", "elseif", "end", "function",
    "defined", "static_cast", "dynamic_cast", "reinterpret_cast", "const_cast",
    "template", "typename", "public", "private", "protected", "virtual",
    "override", "operator", "goto", "break", "continue", "default", "void",
    "int", "float", "double", "char", "long", "short", "unsigned", "bool",
    "match", "loop", "impl", "fn", "let", "mut", "func", "go", "defer",
    "select", "range", "print", "println", "import", "package", "require",
    "when", "until", "unless", "begin", "rescue", "ensure", "yield", "in",
    "and", "or", "not", "is", "then", "otherwise", "parfor", "with",
}

_C_TYPE_KEYWORDS_RE = re.compile(
    r"^\s*(?:(?:static|inline|extern|virtual|const|constexpr|unsigned|signed|"
    r"public|private|protected|final|override|abstract|synchronized|native|"
    r"template\s*<[^>]*>|friend|explicit|volatile|register|async|internal)\s+)*"
)

_C_FUNCTION_RE = re.compile(
    r"^\s*(?!return\b|else\b|if\b|for\b|while\b|switch\b|case\b|do\b|typedef\b|using\b|new\b|delete\b|throw\b)"
    r"(?P<ret>[\w:<>,\*&\[\]\s~]+?)\s*[\*&]*\s*"
    r"(?P<name>~?[A-Za-z_][\w:]*)\s*\((?P<params>[^;{}()]*)\)\s*"
    r"(?:(?:const|override|final|noexcept|volatile|throws?\s+[\w,\s]+|->\s*[\w:<>\*&]+)\s*)*\{?\s*$"
)


@dataclass
class LanguageSpec:
    language: str
    extensions: tuple[str, ...]
    import_res: list[re.Pattern[str]]
    function_res: list[re.Pattern[str]]
    class_res: list[re.Pattern[str]]
    comment_prefixes: tuple[str, ...]
    block_style: str  # "braces" | "end" | "next_def"
    entry_names: tuple[str, ...] = ("main",)
    block_openers: re.Pattern[str] | None = None  # for "end" style
    io_hints: tuple[str, ...] = ()
    method_res: list[re.Pattern[str]] = field(default_factory=list)


def _r(p: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(p, flags)


# ---------------------------------------------------------------------------
# Language table
# ---------------------------------------------------------------------------
_C_LIKE_CLASS = _r(
    r"^\s*(?:(?:public|private|protected|abstract|final|static|sealed|partial|data|open|internal|export)\s+)*"
    r"(?:class|struct|interface|enum|union|record|trait|protocol|object)\s+(?P<name>[A-Za-z_]\w*)"
    r"(?:\s*<[^>{]*>)?(?:\s*(?::|extends|implements|<)\s*(?:public\s+|private\s+|protected\s+|virtual\s+)?(?P<base>[\w:.<>, ]+?))?\s*\{?\s*$"
)

LANGUAGE_SPECS: list[LanguageSpec] = [
    LanguageSpec(
        language="c",
        extensions=(".c", ".h"),
        import_res=[_r(r'^\s*#\s*include\s*[<"](?P<module>[^>"]+)[>"]')],
        function_res=[_C_FUNCTION_RE],
        class_res=[_r(r"^\s*(?:typedef\s+)?(?:struct|union|enum)\s+(?P<name>[A-Za-z_]\w*)\s*\{?\s*$")],
        comment_prefixes=("//", "/*", "*"),
        block_style="braces",
        io_hints=("stdio.h", "fcntl.h", "unistd.h", "sys/socket.h", "printf", "fopen", "scanf"),
    ),
    LanguageSpec(
        language="cpp",
        extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ipp", ".inl", ".cu", ".cuh"),
        import_res=[_r(r'^\s*#\s*include\s*[<"](?P<module>[^>"]+)[>"]'), _r(r"^\s*import\s+(?P<module>[\w.:]+)\s*;")],
        function_res=[_C_FUNCTION_RE],
        class_res=[_C_LIKE_CLASS],
        comment_prefixes=("//", "/*", "*"),
        block_style="braces",
        io_hints=("iostream", "fstream", "cstdio", "std::cout", "std::cin", "ofstream", "ifstream"),
    ),
    LanguageSpec(
        language="csharp",
        extensions=(".cs",),
        import_res=[_r(r"^\s*using\s+(?:static\s+)?(?P<module>[\w.]+)\s*;")],
        function_res=[_C_FUNCTION_RE],
        class_res=[_C_LIKE_CLASS],
        comment_prefixes=("//", "/*", "*", "///"),
        block_style="braces",
        entry_names=("Main",),
        io_hints=("System.IO", "Console", "File.", "HttpClient"),
    ),
    LanguageSpec(
        language="java",
        extensions=(".java",),
        import_res=[_r(r"^\s*import\s+(?:static\s+)?(?P<module>[\w.\*]+)\s*;")],
        function_res=[_C_FUNCTION_RE],
        class_res=[_C_LIKE_CLASS],
        comment_prefixes=("//", "/*", "*"),
        block_style="braces",
        io_hints=("java.io", "java.net", "java.nio", "System.out", "Scanner"),
    ),
    LanguageSpec(
        language="kotlin",
        extensions=(".kt", ".kts"),
        import_res=[_r(r"^\s*import\s+(?P<module>[\w.\*]+)")],
        function_res=[_r(r"^\s*(?:(?:public|private|protected|internal|override|open|suspend|inline|operator|infix)\s+)*fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?(?P<name>\w+)\s*\((?P<params>[^)]*)\)")],
        class_res=[_C_LIKE_CLASS],
        comment_prefixes=("//", "/*", "*"),
        block_style="braces",
        io_hints=("java.io", "println", "readLine"),
    ),
    LanguageSpec(
        language="swift",
        extensions=(".swift",),
        import_res=[_r(r"^\s*import\s+(?P<module>[\w.]+)")],
        function_res=[_r(r"^\s*(?:(?:public|private|fileprivate|internal|open|static|class|override|mutating|final)\s+)*func\s+(?P<name>\w+)\s*(?:<[^>]*>)?\s*\((?P<params>[^)]*)\)")],
        class_res=[_C_LIKE_CLASS],
        comment_prefixes=("//", "/*", "*"),
        block_style="braces",
        io_hints=("Foundation", "print(", "FileManager", "URLSession"),
    ),
    LanguageSpec(
        language="go",
        extensions=(".go",),
        import_res=[_r(r'^\s*import\s+(?:\w+\s+)?"(?P<module>[^"]+)"'), _r(r'^\s*(?:\w+\s+)?"(?P<module>[\w./-]+)"\s*$')],
        function_res=[_r(r"^\s*func\s+(?:\([^)]*\)\s*)?(?P<name>\w+)\s*(?:\[[^\]]*\])?\s*\((?P<params>[^)]*)\)")],
        class_res=[_r(r"^\s*type\s+(?P<name>\w+)\s+(?:struct|interface)\s*\{?\s*$")],
        comment_prefixes=("//", "/*", "*"),
        block_style="braces",
        io_hints=("fmt", "os", "io", "net/http", "bufio", "encoding/json"),
    ),
    LanguageSpec(
        language="rust",
        extensions=(".rs",),
        import_res=[_r(r"^\s*(?:pub\s+)?use\s+(?P<module>[\w:{}, \*]+)\s*;"), _r(r"^\s*extern\s+crate\s+(?P<module>\w+)")],
        function_res=[_r(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:const\s+)?fn\s+(?P<name>\w+)\s*(?:<[^>]*>)?\s*\((?P<params>[^)]*)\)")],
        class_res=[
            _r(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+(?P<name>\w+)"),
            _r(r"^\s*impl(?:<[^>]*>)?\s+(?:(?P<base>[\w:]+)\s+for\s+)?(?P<name>[\w:]+)"),
        ],
        comment_prefixes=("//", "/*", "*", "///"),
        block_style="braces",
        io_hints=("std::io", "std::fs", "println!", "std::net", "tokio"),
    ),
    LanguageSpec(
        language="php",
        extensions=(".php",),
        import_res=[_r(r"^\s*(?:use|require|require_once|include|include_once)\s*\(?\s*['\"]?(?P<module>[\w\\/.]+)")],
        function_res=[_r(r"^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+&?(?P<name>\w+)\s*\((?P<params>[^)]*)\)")],
        class_res=[_C_LIKE_CLASS],
        comment_prefixes=("//", "#", "/*", "*"),
        block_style="braces",
        io_hints=("fopen", "file_get_contents", "echo", "curl_", "PDO"),
    ),
    LanguageSpec(
        language="ruby",
        extensions=(".rb",),
        import_res=[_r(r"^\s*(?:require|require_relative|load)\s+['\"](?P<module>[^'\"]+)['\"]")],
        function_res=[_r(r"^\s*def\s+(?:self\.)?(?P<name>[\w?!=]+)\s*(?:\((?P<params>[^)]*)\))?")],
        class_res=[_r(r"^\s*(?:class|module)\s+(?P<name>[\w:]+)(?:\s*<\s*(?P<base>[\w:]+))?")],
        comment_prefixes=("#",),
        block_style="end",
        block_openers=_r(r"^\s*(?:def|class|module|if|unless|while|until|for|begin|case|do)\b|\bdo\s*(?:\|[^|]*\|)?\s*$"),
        io_hints=("File.", "puts", "gets", "net/http", "socket"),
    ),
    LanguageSpec(
        language="r",
        extensions=(".r", ".R", ".Rmd"),
        import_res=[_r(r"^\s*(?:library|require)\s*\(\s*['\"]?(?P<module>[\w.]+)"), _r(r"^\s*source\s*\(\s*['\"](?P<module>[^'\"]+)")],
        function_res=[_r(r"^\s*(?P<name>[\w.]+)\s*(?:<-|=)\s*function\s*\((?P<params>[^)]*)\)")],
        class_res=[_r(r"^\s*(?:setClass|setRefClass|R6Class)\s*\(\s*['\"](?P<name>\w+)")],
        comment_prefixes=("#",),
        block_style="braces",
        entry_names=(),
        io_hints=("read.csv", "write.csv", "readRDS", "print(", "cat(", "ggplot", "plot("),
    ),
    LanguageSpec(
        language="julia",
        extensions=(".jl",),
        import_res=[_r(r"^\s*(?:using|import)\s+(?P<module>[\w.,: ]+)")],
        function_res=[
            _r(r"^\s*function\s+(?:[\w.]+\.)?(?P<name>\w+[!]?)\s*(?:\{[^}]*\})?\s*\((?P<params>[^)]*)\)"),
            _r(r"^\s*(?P<name>\w+[!]?)\s*\((?P<params>[^)]*)\)\s*(?:::\s*\w+\s*)?=\s*(?!=)"),
        ],
        class_res=[_r(r"^\s*(?:mutable\s+)?struct\s+(?P<name>\w+)(?:\s*<:\s*(?P<base>[\w.]+))?"), _r(r"^\s*abstract\s+type\s+(?P<name>\w+)(?:\s*<:\s*(?P<base>[\w.]+))?")],
        comment_prefixes=("#",),
        block_style="end",
        block_openers=_r(r"^\s*(?:function|struct|mutable\s+struct|if|for|while|begin|let|try|do|module|macro|quote|abstract\s+type)\b|\bdo\s*$"),
        entry_names=("main",),
        io_hints=("println", "open(", "CSV", "DataFrames", "Plots", "HTTP"),
    ),
    LanguageSpec(
        language="matlab",
        extensions=(".m", ".mlx"),
        import_res=[_r(r"^\s*import\s+(?P<module>[\w.\*]+)"), _r(r"^\s*(?:addpath|run|load)\s*\(?\s*['\"](?P<module>[^'\"]+)")],
        function_res=[_r(r"^\s*function\s+(?:(?:\[[^\]]*\]|[\w~]+)\s*=\s*)?(?P<name>\w+)\s*(?:\((?P<params>[^)]*)\))?")],
        class_res=[_r(r"^\s*classdef\s+(?:\([^)]*\)\s*)?(?P<name>\w+)(?:\s*<\s*(?P<base>[\w.&\s]+))?")],
        comment_prefixes=("%", "#"),
        block_style="next_def",
        entry_names=(),
        io_hints=("fprintf", "disp", "load", "save", "readtable", "csvread", "xlsread", "plot", "figure", "fopen", "imread", "saveas"),
    ),
]

_SPEC_BY_EXT: dict[str, LanguageSpec] = {}
for _spec in LANGUAGE_SPECS:
    for _ext in _spec.extensions:
        _SPEC_BY_EXT[_ext.lower()] = _spec
_SPEC_BY_LANGUAGE: dict[str, LanguageSpec] = {s.language: s for s in LANGUAGE_SPECS}
_SPEC_BY_LANGUAGE["octave"] = _SPEC_BY_LANGUAGE["matlab"]
_SPEC_BY_LANGUAGE["objective-c"] = _SPEC_BY_LANGUAGE["c"]

GENERIC_EXTENSIONS: dict[str, str] = {
    ext: spec.language for ext, spec in _SPEC_BY_EXT.items()
}

_CALL_RE = re.compile(r"(?<![\w.:])([A-Za-z_][\w.:!]*)\s*\(")
# C-family prototype / forward declaration: `int foo(int a);`
_PROTOTYPE_RE = re.compile(r"^\s*(?:[\w:<>,\*&\[\]\s]+?)\s+[\*&]*\s*~?[A-Za-z_][\w:]*\s*\([^;{}]*\)\s*(?:const|noexcept|override|final|=\s*0)?\s*;\s*$")
_OBJC_HINT_RE = re.compile(r"^\s*(?:#import\b|@interface\b|@implementation\b|@end\b)", re.M)


def _strip_strings(text: str) -> str:
    """Blank out string literals so regexes do not fire inside them."""
    return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', text)


def _is_comment(stripped: str, spec: LanguageSpec) -> bool:
    return any(stripped.startswith(p) for p in spec.comment_prefixes)


def _find_brace_end(lines: list[str], start_idx: int) -> int:
    """Return 0-based index of the line closing the block opened at/after start_idx."""
    depth = 0
    opened = False
    for i in range(start_idx, len(lines)):
        text = _strip_strings(lines[i])
        text = re.sub(r"//.*$", "", text)
        for ch in text:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
                if opened and depth <= 0:
                    return i
        if not opened and i > start_idx + 3:
            # No brace within a few lines: treat as one-liner / prototype.
            return start_idx
    return len(lines) - 1


def _find_end_keyword(lines: list[str], start_idx: int, spec: LanguageSpec) -> int:
    depth = 0
    for i in range(start_idx, len(lines)):
        stripped = lines[i].strip()
        if _is_comment(stripped, spec):
            continue
        if spec.block_openers and spec.block_openers.search(stripped):
            depth += 1
        # Count trailing/standalone "end"
        ends = len(re.findall(r"(?<![\w.])end(?![\w.])", _strip_strings(stripped)))
        depth -= ends
        if depth <= 0 and i > start_idx:
            return i
    return len(lines) - 1


def _find_next_def(lines: list[str], start_idx: int, spec: LanguageSpec) -> int:
    for i in range(start_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if any(r.match(stripped) for r in spec.function_res) or any(
            r.match(stripped) for r in spec.class_res
        ):
            return i - 1
    return len(lines) - 1


def _block_end(lines: list[str], start_idx: int, spec: LanguageSpec) -> int:
    if spec.block_style == "braces":
        return _find_brace_end(lines, start_idx)
    if spec.block_style == "end":
        return _find_end_keyword(lines, start_idx, spec)
    return _find_next_def(lines, start_idx, spec)


def _snippet(lines: list[str], start: int, end: int, max_lines: int = 40) -> str:
    end = min(end, len(lines), start + max_lines - 1)
    return "\n".join(lines[start - 1 : end])


def _split_params(params: str | None) -> list[str]:
    if not params:
        return []
    out: list[str] = []
    for chunk in params.split(","):
        chunk = chunk.strip().rstrip(")")
        if not chunk or chunk in {"void", "..."}:
            continue
        # C-style "const Type *name" → name; MATLAB "x" → x; Go "x int" → x
        tokens = re.findall(r"[A-Za-z_]\w*", chunk)
        if not tokens:
            continue
        name = tokens[-1] if not chunk.endswith(tokens[0]) or len(tokens) == 1 else tokens[0]
        if name in {"const", "int", "float", "double", "char", "bool", "void", "string"} and len(tokens) > 1:
            name = tokens[0]
        out.append(name)
    return out


class GenericRegexParser(LanguageParser):
    """Heuristic parser shared by all regex-backed languages."""

    language = "generic"
    extensions = tuple(_SPEC_BY_EXT.keys())
    also_handles = tuple(_SPEC_BY_LANGUAGE.keys())

    def parse(self, content: str, relative_path: str) -> ParseResult:
        ext = "." + relative_path.rsplit(".", 1)[-1].lower() if "." in relative_path else ""
        spec = _SPEC_BY_EXT.get(ext)
        if spec is None:
            module = ModuleUnit(
                file=relative_path,
                language="unknown",
                parse_error=f"No language spec for extension {ext or '(none)'}",
                raw_content=content,
            )
            return ParseResult(module=module, success=False)

        language = spec.language
        # .m files: distinguish Objective-C from MATLAB/Octave.
        if spec.language == "matlab" and _OBJC_HINT_RE.search(content):
            spec = _SPEC_BY_LANGUAGE["c"]
            language = "objective-c"
        elif spec.language == "matlab" and re.search(r"^\s*(?:#|%!|pkg\s+load)", content, re.M):
            language = "octave"

        module = ModuleUnit(file=relative_path, language=language, raw_content=content)
        lines = content.splitlines()
        try:
            self._extract(module, lines, spec)
        except Exception as exc:  # noqa: BLE001 — never crash the run
            module.parse_error = f"Heuristic extraction error: {exc}"
            return ParseResult(module=module, success=bool(module.functions or module.classes))

        if not (module.functions or module.classes or module.imports):
            module.parse_error = "No recognizable definitions (regex heuristics)."
        return ParseResult(module=module, success=True)

    # ------------------------------------------------------------------
    def _extract(self, module: ModuleUnit, lines: list[str], spec: LanguageSpec) -> None:
        claimed: set[int] = set()  # 0-based line indexes already inside a def
        class_stack: list[tuple[ClassUnit, int]] = []  # (class, end_idx)
        top_level_statements = 0
        first_code_line_is_function = None

        i = 0
        while i < len(lines):
            raw = lines[i]
            stripped = raw.strip()
            if not stripped or _is_comment(stripped, spec):
                i += 1
                continue

            # Pop finished classes
            while class_stack and i > class_stack[-1][1]:
                class_stack.pop()

            # Imports
            matched_import = False
            for ir in spec.import_res:
                m = ir.match(stripped)
                if m:
                    mod = m.group("module").strip()
                    module.imports.append(
                        ImportRef(
                            module=mod,
                            names=[mod.rsplit("/", 1)[-1]],
                            line=i + 1,
                            is_relative=mod.startswith(".") or "/" in mod,
                        )
                    )
                    matched_import = True
                    break
            if matched_import:
                i += 1
                continue

            # Classes
            cls_match = None
            for cr in spec.class_res:
                cls_match = cr.match(stripped)
                if cls_match:
                    break
            if cls_match and not stripped.endswith(";"):
                name = cls_match.group("name").split("::")[-1]
                base = cls_match.groupdict().get("base")
                end_idx = _block_end(lines, i, spec)
                parent_q = class_stack[-1][0].qualified_name if class_stack else module.file
                qname = f"{parent_q}::{name}"
                bases = [b.strip() for b in re.split(r"[,&]", base) if b.strip()] if base else []
                existing = next((c for c in module.classes if c.qualified_name == qname), None)
                if existing is not None:
                    # e.g. Rust `struct X` + `impl X`, or a re-opened Ruby class: merge.
                    existing.line_end = max(existing.line_end, end_idx + 1)
                    for b in bases:
                        if b not in existing.bases:
                            existing.bases.append(b)
                    unit = existing
                else:
                    unit = ClassUnit(
                        name=name,
                        qualified_name=qname,
                        line_start=i + 1,
                        line_end=end_idx + 1,
                        snippet=_snippet(lines, i + 1, end_idx + 1),
                        bases=bases,
                    )
                    module.classes.append(unit)
                class_stack.append((unit, end_idx))
                if first_code_line_is_function is None:
                    first_code_line_is_function = True
                i += 1
                continue

            # Functions
            fn_match = None
            for fr in spec.function_res:
                fn_match = fr.match(_strip_strings(stripped))
                if fn_match:
                    break
            if fn_match:
                name = fn_match.group("name").split("::")[-1]
                if name in _KEYWORDS or (spec.block_style == "braces" and stripped.endswith(";")):
                    fn_match = None
            if fn_match:
                # C-like: require a brace on this or the next non-empty lines.
                if spec.block_style == "braces" and "{" not in stripped:
                    look = i + 1
                    has_brace = False
                    while look < len(lines) and look <= i + 2:
                        nxt = lines[look].strip()
                        if nxt.startswith("{"):
                            has_brace = True
                            break
                        if nxt and not nxt.startswith(("//", "/*", "*")):
                            break
                        look += 1
                    if not has_brace and spec.language in {"c", "cpp", "csharp", "java"}:
                        fn_match = None
            if fn_match:
                name = fn_match.group("name").split("::")[-1]
                params = _split_params(fn_match.groupdict().get("params"))
                end_idx = _block_end(lines, i, spec)
                in_class = class_stack[-1][0] if class_stack else None
                parent_q = in_class.qualified_name if in_class else module.file
                unit = FunctionUnit(
                    name=name,
                    qualified_name=f"{parent_q}::{name}",
                    line_start=i + 1,
                    line_end=end_idx + 1,
                    snippet=_snippet(lines, i + 1, end_idx + 1),
                    parameters=params,
                    is_method=in_class is not None,
                )
                self._scan_body(module, unit, lines, i, end_idx, spec)
                if in_class is not None:
                    in_class.methods.append(unit)
                else:
                    module.functions.append(unit)
                for k in range(i, end_idx + 1):
                    claimed.add(k)
                if first_code_line_is_function is None:
                    first_code_line_is_function = True
                i = end_idx + 1 if end_idx > i else i + 1
                continue

            # Top-level variable / statement (scripts: MATLAB, R, Julia, Ruby, PHP …)
            if i not in claimed and not class_stack:
                top_level_statements += 1
                if first_code_line_is_function is None:
                    first_code_line_is_function = False
                clean = _strip_strings(stripped)
                if spec.block_style == "braces" and (_PROTOTYPE_RE.match(clean) or clean.startswith("#")):
                    i += 1  # prototype / preprocessor line — not a call
                    continue
                m = re.match(r"^\s*(?:[\w:<>\[\]\*&]+\s+)?([A-Za-z_]\w*)\s*(?:<-|:=|=)\s*(?!=)(.+?);?\s*$", clean)
                if m and m.group(1) not in _KEYWORDS:
                    module.variables.append(
                        VariableUnit(
                            name=m.group(1),
                            line=i + 1,
                            assigned_from=self._first_identifier(m.group(2)),
                        )
                    )
                for cm in _CALL_RE.finditer(clean):
                    callee = cm.group(1)
                    base = callee.split(".")[-1].split("::")[-1].rstrip("!")
                    if base in _KEYWORDS or len(base) < 2:
                        continue
                    call = CallRef(callee=callee, line=i + 1)
                    module.top_level_calls.append(call)
                    if base[:1].isupper():
                        module.instantiations.append(call)
            i += 1

        # Entry-point heuristics
        names = {f.name for f in module.functions}
        if any(n in names for n in spec.entry_names):
            module.has_main_guard = True
        if spec.language == "matlab" and first_code_line_is_function is False and top_level_statements > 3:
            module.has_main_guard = True  # MATLAB/Octave script file

    def _scan_body(
        self,
        module: ModuleUnit,
        unit: FunctionUnit,
        lines: list[str],
        start_idx: int,
        end_idx: int,
        spec: LanguageSpec,
    ) -> None:
        for k in range(start_idx + 1, end_idx + 1):
            stripped = lines[k].strip()
            if not stripped or _is_comment(stripped, spec):
                continue
            clean = _strip_strings(stripped)
            # returns
            rm = re.match(r"^\s*return\s+([\w.\[\]]+)", clean)
            if rm:
                unit.returns.append(rm.group(1))
            # assignments
            am = re.match(r"^\s*(?:[\w:<>\[\]\*&]+\s+)?([A-Za-z_]\w*)\s*(?:<-|:=|=)\s*(?!=)(.+?);?\s*$", clean)
            if am and am.group(1) not in _KEYWORDS:
                unit.assignments.append(
                    VariableUnit(name=am.group(1), line=k + 1, assigned_from=self._first_identifier(am.group(2)))
                )
            # calls
            for cm in _CALL_RE.finditer(clean):
                callee = cm.group(1)
                base = callee.split(".")[-1].split("::")[-1].rstrip("!")
                if base in _KEYWORDS or base == unit.name or len(base) < 2:
                    continue
                call = CallRef(callee=callee, line=k + 1)
                unit.calls.append(call)
                if base[:1].isupper() or re.search(r"\bnew\s+" + re.escape(callee), clean):
                    module.instantiations.append(call)

    @staticmethod
    def _first_identifier(expr: str) -> str | None:
        m = re.search(r"[A-Za-z_][\w.:]*", expr or "")
        return m.group(0) if m else None
