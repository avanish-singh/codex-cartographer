"""
Line-by-line walkthrough builder.

Produces an ordered script of steps: each step highlights a source line,
explains it in plain English, and describes a visual action for the 2D/3D
atlas (spawn node, pulse edge, focus, etc.).

No LLM in v1 — explanations are structural heuristics so this module can
later swap in an LLM backend without changing the viz contract.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from codex_cartographer.parsers.base import ClassUnit, FunctionUnit, ModuleUnit, ParseResult
from codex_cartographer.semantic.model import CodeGraph


DEFAULT_MAX_STEPS = 1500

# Step kinds that survive when a big project must be condensed.
_HIGH_PRIORITY_KINDS = {
    "ClassDef", "FunctionDef", "AsyncFunctionDef", "Import", "ImportFrom",
    "definition", "import", "chapter",
}
_MID_PRIORITY_KINDS = {"Return", "Expr", "Assign", "If", "For", "While", "Try", "call", "control"}


def build_walkthrough(
    parse_results: list[ParseResult],
    graph: CodeGraph,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict[str, Any]:
    """
    Build a narrated walkthrough for the mapped sources.

    Walks each file in order with chapter markers. When the project is big,
    steps are condensed (definitions/imports/calls kept, filler dropped) so
    the browser stays responsive. ``max_steps<=0`` disables condensing.
    """
    by_id = {n.id: n for n in graph.nodes}
    # Index nodes by (file, line_start) for visual binding
    line_index: dict[tuple[str, int], list[str]] = {}
    for n in graph.nodes:
        if n.file and n.line_start:
            line_index.setdefault((n.file, n.line_start), []).append(n.id)

    name_index: dict[tuple[str, str], str] = {}
    global_names: dict[str, list[str]] = {}
    for n in graph.nodes:
        if n.file:
            name_index[(n.file, n.name)] = n.id
            if n.kind in {"function", "class"}:
                global_names.setdefault(n.name, []).append(n.id)
    # Cross-file binding: a name defined in exactly one other file resolves globally
    # (MATLAB one-function-per-file, C helpers, R sources …).
    files = {n.file for n in graph.nodes if n.file}
    for name, ids_ in global_names.items():
        if len(ids_) == 1:
            for f in files:
                name_index.setdefault((f, name), ids_[0])

    chapters: list[dict[str, Any]] = []
    all_steps: list[dict[str, Any]] = []

    multi_file = len(parse_results) > 1
    for result in parse_results:
        module = result.module
        lines = module.raw_content.splitlines()
        if not lines:
            continue
        if module.language == "python":
            file_steps = _steps_for_python(module, lines, line_index, name_index, by_id)
        else:
            file_steps = _steps_for_generic(module, lines, line_index, name_index)

        if multi_file:
            file_steps.insert(0, _chapter_step(module, lines, graph, line_index))

        chapter = {
            "file": module.file,
            "language": module.language,
            "line_count": len(lines),
            "step_count": len(file_steps),
        }
        chapters.append(chapter)
        # Offset step ids globally
        for step in file_steps:
            step["id"] = f"s{len(all_steps) + 1}"
            all_steps.append(step)

    condensed = False
    if max_steps and len(all_steps) > max_steps:
        all_steps = _condense_steps(all_steps, max_steps)
        condensed = True
        for idx, step in enumerate(all_steps, start=1):
            step["id"] = f"s{idx}"
        counts: dict[str, int] = {}
        for step in all_steps:
            counts[step["file"]] = counts.get(step["file"], 0) + 1
        for chapter in chapters:
            chapter["step_count"] = counts.get(chapter["file"], 0)

    return {
        "version": 2,
        "mode": "line_by_line",
        "condensed": condensed,
        "max_steps": max_steps,
        "chapters": chapters,
        "steps": all_steps,
        "source_files": {
            r.module.file: r.module.raw_content.splitlines() for r in parse_results
        },
    }


def _chapter_step(
    module: ModuleUnit,
    lines: list[str],
    graph: CodeGraph,
    line_index: dict[tuple[str, int], list[str]],
) -> dict[str, Any]:
    """Opening step for each file in a multi-file project."""
    mod_node = next((n for n in graph.nodes if n.kind in {"module", "unparsed"} and n.file == module.file), None)
    node_ids = [mod_node.id] if mod_node else []
    deps_out = sorted({e.label for e in graph.edges if mod_node and e.source == mod_node.id and e.kind == "import" and e.label})
    used_by = sorted(
        {
            n.file
            for e in graph.edges
            if mod_node and e.target == mod_node.id and e.kind == "import"
            for n in graph.nodes
            if n.id == e.source and n.file
        }
    )
    parts = [
        f"Chapter: `{module.file}` ({module.language}, {len(lines)} lines) with "
        f"{len(module.classes)} class(es) and {len(module.functions) + sum(len(c.methods) for c in module.classes)} function(s)."
    ]
    if deps_out:
        parts.append(f"It depends on: {', '.join(deps_out[:8])}{'…' if len(deps_out) > 8 else ''}.")
    if used_by:
        parts.append(f"It is used by: {', '.join(used_by[:6])}{'…' if len(used_by) > 6 else ''}.")
    if module.parse_error:
        parts.append(f"Parser note: {module.parse_error}")
    return _step(
        module.file,
        1,
        lines[0] if lines else "",
        f"Open file {module.file.rsplit('/', 1)[-1]}",
        " ".join(parts),
        visual={"action": "focus", "nodes": node_ids, "edges": [], "effect": "focus"},
        kind="chapter",
    )


def _condense_steps(steps: list[dict[str, Any]], max_steps: int) -> list[dict[str, Any]]:
    """Keep the most informative steps when a project is too big to narrate fully."""
    keep = [s for s in steps if s["kind"] in _HIGH_PRIORITY_KINDS or (s.get("visual") or {}).get("nodes")]
    if len(keep) < max_steps:
        # Fill remaining budget with mid-priority steps, evenly sampled.
        mids = [s for s in steps if s not in keep and s["kind"] in _MID_PRIORITY_KINDS]
        budget = max_steps - len(keep)
        if mids and budget > 0:
            stride = max(1, len(mids) // budget)
            keep.extend(mids[::stride][:budget])
    elif len(keep) > max_steps:
        stride = max(1, len(keep) // max_steps)
        chapters = [s for s in keep if s["kind"] == "chapter"]
        rest = [s for s in keep if s["kind"] != "chapter"]
        keep = chapters + rest[::stride][: max_steps - len(chapters)]
    order = {id(s): i for i, s in enumerate(steps)}
    keep.sort(key=lambda s: order[id(s)])
    return keep


def _steps_for_python(
    module: ModuleUnit,
    lines: list[str],
    line_index: dict[tuple[str, int], list[str]],
    name_index: dict[tuple[str, str], str],
    by_id: dict,
) -> list[dict[str, Any]]:
    """AST-aware line walk for Python."""
    steps: list[dict[str, Any]] = []
    try:
        tree = ast.parse(module.raw_content, filename=module.file)
    except SyntaxError:
        return _steps_for_generic(module, lines, line_index, name_index)

    # Map lineno → list of AST nodes starting there
    nodes_at: dict[int, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if hasattr(node, "lineno") and isinstance(getattr(node, "lineno"), int):
            nodes_at.setdefault(node.lineno, []).append(node)

    # Also track which lines belong to which function/class for context
    scope_stack: list[str] = []

    covered = set()
    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#") and i not in nodes_at:
            # Section banner comments — still narrate
            title, explanation = _explain_comment(stripped)
            steps.append(
                _step(
                    module.file,
                    i,
                    raw,
                    title,
                    explanation,
                    visual={"action": "narrate", "nodes": [], "edges": [], "effect": "dim"},
                    kind="comment",
                )
            )
            covered.add(i)
            continue

        ast_nodes = nodes_at.get(i, [])
        # Prefer significant node types at this line
        primary = _pick_primary(ast_nodes)
        title, explanation, visual = _explain_ast_line(
            module,
            i,
            stripped,
            primary,
            ast_nodes,
            line_index,
            name_index,
            by_id,
        )
        steps.append(
            _step(
                module.file,
                i,
                raw,
                title,
                explanation,
                visual=visual,
                kind=_kind_for(primary),
            )
        )
        covered.add(i)

    return steps


_COMMENT_PREFIXES = {
    "javascript": ("//", "/*", "*"),
    "typescript": ("//", "/*", "*"),
    "c": ("//", "/*", "*"),
    "cpp": ("//", "/*", "*"),
    "objective-c": ("//", "/*", "*"),
    "csharp": ("//", "/*", "*"),
    "java": ("//", "/*", "*"),
    "kotlin": ("//", "/*", "*"),
    "swift": ("//", "/*", "*"),
    "go": ("//", "/*", "*"),
    "rust": ("//", "/*", "*"),
    "php": ("//", "#", "/*", "*"),
    "ruby": ("#",),
    "r": ("#",),
    "julia": ("#",),
    "matlab": ("%", "#"),
    "octave": ("%", "#"),
}

_IMPORT_LINE_RE = re.compile(
    r"^\s*(?:#\s*include|import|from\s+\S+\s+import|using|use|require(?:_relative|_once)?|include(?:_once)?|"
    r"library|source|addpath|extern\s+crate|pkg\s+load)\b"
)
_CONTROL_RE = re.compile(
    r"^\s*(?:if|else\s*if|elseif|elif|else|for|parfor|foreach|while|do|switch|case|match|when|until|unless|loop|try|catch|except|finally|rescue|ensure|otherwise)\b"
)
_RETURN_RE = re.compile(r"^\s*return\b")
_CALL_LINE_RE = re.compile(r"^\s*(?:(?:[\w.:]+|\[[^\]]*\])\s*(?:<-|:=|=)\s*)?([A-Za-z_][\w.:!]*)\s*\(")
_ASSIGN_RE = re.compile(r"^\s*(?:[\w:<>\[\]\*&]+\s+)?([A-Za-z_][\w.\[\]]*|\[[^\]]*\])\s*(?:<-|:=|\+=|-=|\*=|/=|=)\s*(?!=)")
_END_RE = re.compile(r"^\s*(?:end\w*|\}|\};|\)\s*;?|endif|endfor|endwhile|endfunction)\s*;?\s*$")


def _steps_for_generic(
    module: ModuleUnit,
    lines: list[str],
    line_index: dict[tuple[str, int], list[str]],
    name_index: dict[tuple[str, str], str],
) -> list[dict[str, Any]]:
    """
    Language-aware narration for non-Python files.

    Uses the parser's extracted units (functions/classes/imports/calls) to
    bind lines to graph nodes, then falls back to textual heuristics.
    """
    lang = module.language
    comment_prefixes = _COMMENT_PREFIXES.get(lang, ("//", "#", "/*", "*", "%"))

    # Line → unit lookups from the parser
    func_by_line: dict[int, FunctionUnit] = {}
    class_by_line: dict[int, ClassUnit] = {}
    for f in module.functions:
        func_by_line[f.line_start] = f
    for c in module.classes:
        class_by_line[c.line_start] = c
        for m in c.methods:
            func_by_line[m.line_start] = m
    import_by_line = {imp.line: imp for imp in module.imports}
    calls_by_line: dict[int, list[str]] = {}
    for f in list(module.functions) + [m for c in module.classes for m in c.methods]:
        for call in f.calls:
            calls_by_line.setdefault(call.line, []).append(call.callee)
    for call in module.top_level_calls:
        calls_by_line.setdefault(call.line, []).append(call.callee)

    # Enclosing function for each line (for "inside X" context)
    def enclosing(line: int) -> FunctionUnit | None:
        best = None
        for f in func_by_line.values():
            if f.line_start <= line <= f.line_end and (best is None or f.line_start > best.line_start):
                best = f
        return best

    steps: list[dict[str, Any]] = []
    in_block_comment = False
    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue

        # Block comments (/* ... */, %{ ... %}, =begin/=end)
        if in_block_comment:
            if "*/" in stripped or stripped.startswith(("%}", "=end")):
                in_block_comment = False
            continue
        if stripped.startswith("/*") and "*/" not in stripped:
            in_block_comment = True
            continue
        if stripped in ("%{", "=begin"):
            in_block_comment = True
            continue

        node_ids = list(line_index.get((module.file, i), []))
        kind = "line"
        visual: dict[str, Any] = {"action": "narrate", "nodes": node_ids, "edges": [], "effect": "focus"}

        if any(stripped.startswith(p) for p in comment_prefixes):
            title, explanation = _explain_comment_generic(stripped, comment_prefixes)
            kind = "comment"
            visual["effect"] = "dim"

        elif i in class_by_line:
            c = class_by_line[i]
            nid = name_index.get((module.file, c.name))
            if nid and nid not in node_ids:
                node_ids.append(nid)
            base_txt = f" It extends {', '.join(c.bases)}." if c.bases else ""
            title = f"Define {_class_word(lang)} `{c.name}`"
            explanation = (
                f"Declares `{c.name}` — a blueprint grouping {len(c.methods)} method(s) and "
                f"{len(c.attributes)} field(s) (lines {c.line_start}–{c.line_end}).{base_txt} "
                "A class landmark appears on the atlas; its methods attach as we continue."
            )
            kind = "definition"
            visual.update({"action": "reveal_nodes", "nodes": node_ids, "effect": "spawn"})

        elif i in func_by_line:
            f = func_by_line[i]
            nid = name_index.get((module.file, f.name))
            if nid and nid not in node_ids:
                node_ids.append(nid)
            callees = sorted({c.callee.split(".")[-1] for c in f.calls})[:6]
            params = ", ".join(f.parameters) if f.parameters else "no parameters"
            title = f"Define {'method' if f.is_method else 'function'} `{f.name}`"
            explanation = (
                f"Starts {_fn_word(lang)} `{f.name}` taking {params} "
                f"(lines {f.line_start}–{f.line_end}). "
                + (f"Inside it calls {', '.join(callees)}. " if callees else "")
                + "Its landmark lights up; call routes to those helpers appear when they are resolved."
            )
            kind = "definition"
            visual.update({"action": "reveal_nodes", "nodes": node_ids, "effect": "spawn"})

        elif i in import_by_line or _IMPORT_LINE_RE.match(stripped):
            imp = import_by_line.get(i)
            target = imp.module if imp else stripped
            title = f"Bring in `{target}`"
            explanation = (
                f"Makes code from `{target}` available in this file — {_import_word(lang)}. "
                "An inked route appears from this module toward that dependency (internal file or external library)."
            )
            kind = "import"
            visual.update({"action": "reveal_nodes", "effect": "spawn"})

        elif _RETURN_RE.match(stripped):
            f = enclosing(i)
            title = "Return a result"
            explanation = (
                f"Ends `{f.name}` and hands a value back to its caller. " if f else "Hands a value back to the caller. "
            ) + "On the map, energy flows outward from the function landmark."
            if f:
                nid = name_index.get((module.file, f.name))
                if nid:
                    node_ids.append(nid)
            kind = "Return"
            visual.update({"action": "pulse", "nodes": node_ids, "effect": "flow"})

        elif _CONTROL_RE.match(stripped):
            word = stripped.split()[0].rstrip("(:")
            title = f"Control flow: `{word}`"
            explanation = _control_explanation(word)
            f = enclosing(i)
            if f:
                nid = name_index.get((module.file, f.name))
                if nid:
                    node_ids.append(nid)
            kind = "control"
            visual.update({"action": "focus", "nodes": node_ids, "effect": "focus"})

        elif i in calls_by_line or _CALL_LINE_RE.match(stripped):
            callees = calls_by_line.get(i) or [_CALL_LINE_RE.match(stripped).group(1)]  # type: ignore[union-attr]
            resolved = []
            for callee in callees:
                nid = name_index.get((module.file, callee.split(".")[-1]))
                if nid:
                    resolved.append(nid)
            for nid in resolved:
                if nid not in node_ids:
                    node_ids.append(nid)
            f = enclosing(i)
            if f:
                fnid = name_index.get((module.file, f.name))
                if fnid and fnid not in node_ids:
                    node_ids.append(fnid)
            main_callee = callees[0]
            assign_m = _ASSIGN_RE.match(stripped)
            if assign_m:
                title = f"`{assign_m.group(1)}` = result of `{main_callee}`"
                explanation = (
                    f"Calls `{main_callee}` and stores what it returns into `{assign_m.group(1)}`. "
                    + ("That callee is defined in this project, so a call route pulses on the atlas. "
                       if resolved else "That callee lives in a library or built-in, so no internal route is drawn. ")
                    + "Later lines can reuse the stored name."
                )
            else:
                title = f"Call `{main_callee}`"
                explanation = (
                    f"Runs `{main_callee}` now — jumping into that routine, then returning here. "
                    + ("It is one of this project's own functions; watch the call route light up."
                       if resolved else "It is a library/built-in call; the effect happens outside the mapped code.")
                )
            kind = "call"
            visual.update({"action": "pulse" if resolved else "narrate", "nodes": node_ids, "effect": "flow"})

        elif _END_RE.match(stripped):
            title = "Close block"
            explanation = "Marks the end of the current block (function, loop, or branch). Control returns to the enclosing scope."
            kind = "end"
            visual["effect"] = "dim"

        elif _ASSIGN_RE.match(stripped):
            m = _ASSIGN_RE.match(stripped)
            name = m.group(1) if m else "value"
            title = f"Store into `{name}`"
            explanation = (
                f"Computes the right-hand side and remembers it as `{name}`. "
                "Later lines can use this name instead of recomputing."
            )
            f = enclosing(i)
            if f:
                nid = name_index.get((module.file, f.name))
                if nid:
                    node_ids.append(nid)
            kind = "Assign"
            visual.update({"nodes": node_ids})

        else:
            title, explanation = _explain_text_line(stripped, lang)
            if node_ids:
                visual.update({"action": "reveal_nodes", "effect": "spawn"})

        steps.append(_step(module.file, i, raw, title, explanation, visual=visual, kind=kind))
    return steps


def _class_word(lang: str) -> str:
    return {
        "c": "struct", "go": "type", "rust": "struct/impl", "matlab": "classdef", "octave": "classdef",
    }.get(lang, "class")


def _fn_word(lang: str) -> str:
    return {
        "c": "a C function", "cpp": "a C++ function", "matlab": "a MATLAB function",
        "octave": "an Octave function", "go": "a Go func", "rust": "a Rust fn", "r": "an R function",
        "julia": "a Julia function", "java": "a Java method", "csharp": "a C# method",
    }.get(lang, "a function")


def _import_word(lang: str) -> str:
    return {
        "c": "the preprocessor pastes that header in before compiling",
        "cpp": "the preprocessor pastes that header in before compiling",
        "matlab": "MATLAB adds it to the search path / namespace",
        "octave": "Octave adds it to the search path / namespace",
        "go": "the Go toolchain links that package",
        "rust": "the crate/module is brought into scope",
        "r": "the R package is attached to the session",
        "julia": "the Julia module is loaded into scope",
    }.get(lang, "like opening a toolbox of ready-made functions")


def _control_explanation(word: str) -> str:
    w = word.lower()
    if w in {"if", "elif", "elseif", "else", "unless", "when", "switch", "case", "match", "otherwise"}:
        return "A decision point: the program checks a condition and takes one branch or another. On the map this is a fork in the road."
    if w in {"for", "parfor", "foreach", "while", "do", "until", "loop"}:
        return "A loop: the indented/braced block repeats. The same landmarks may activate many times — one cycle per iteration."
    if w in {"try", "catch", "except", "finally", "rescue", "ensure"}:
        return "An error safety net: if something fails inside, the handler recovers instead of crashing the program."
    return "Structured control flow that changes the order in which lines execute."


def _explain_comment_generic(text: str, prefixes: tuple[str, ...]) -> tuple[str, str]:
    clean = text
    for p in sorted(prefixes, key=len, reverse=True):
        if clean.startswith(p):
            clean = clean[len(p):]
            break
    clean = clean.strip(" =-*/%#{}")
    if not clean:
        return ("Section marker", "A visual divider — no runtime effect.")
    return (
        f"Note: {clean[:60]}",
        f"This comment says “{clean}”. Comments are ignored by the compiler/interpreter; they guide the reader.",
    )


def _step(
    file: str,
    line: int,
    code: str,
    title: str,
    explanation: str,
    *,
    visual: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    return {
        "id": "",  # filled later
        "file": file,
        "line": line,
        "end_line": line,
        "code": code.rstrip("\n"),
        "title": title,
        "explanation": explanation,
        "kind": kind,
        "visual": visual,
    }


def _pick_primary(nodes: list[ast.AST]) -> ast.AST | None:
    priority = (
        ast.ClassDef,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Import,
        ast.ImportFrom,
        ast.Assign,
        ast.AnnAssign,
        ast.AugAssign,
        ast.Return,
        ast.If,
        ast.For,
        ast.While,
        ast.With,
        ast.Try,
        ast.Raise,
        ast.Assert,
        ast.Expr,
        ast.Call,
    )
    for typ in priority:
        for n in nodes:
            if isinstance(n, typ):
                return n
    return nodes[0] if nodes else None


def _kind_for(node: ast.AST | None) -> str:
    if node is None:
        return "line"
    return type(node).__name__


def _explain_comment(text: str) -> tuple[str, str]:
    clean = text.lstrip("#").strip(" =")
    if not clean:
        return ("Section marker", "A visual divider in the manuscript — no runtime effect.")
    return (
        f"Note: {clean[:60]}",
        f"This comment labels the next section as “{clean}”. Comments are ignored when the program runs; they guide the reader.",
    )


def _explain_ast_line(
    module: ModuleUnit,
    line: int,
    stripped: str,
    primary: ast.AST | None,
    all_nodes: list[ast.AST],
    line_index: dict[tuple[str, int], list[str]],
    name_index: dict[tuple[str, str], str],
    by_id: dict,
) -> tuple[str, str, dict[str, Any]]:
    node_ids = list(line_index.get((module.file, line), []))
    edge_ids: list[str] = []
    action = "narrate"
    effect = "focus"

    if isinstance(primary, (ast.Import, ast.ImportFrom)):
        names = []
        if isinstance(primary, ast.Import):
            names = [a.name for a in primary.names]
        else:
            mod = primary.module or ""
            names = [f"{mod}.{a.name}" if mod else a.name for a in primary.names]
        # Find matching import edges / external nodes
        for n in by_id.values():
            if n.kind == "external" and any(n.name.split(".")[0] in nm or nm.startswith(n.name) for nm in names):
                node_ids.append(n.id)
        for e in []:  # filled via graph scan below — caller may enrich
            pass
        title = f"Import {', '.join(names[:3])}"
        explanation = (
            f"This line loads external library code ({', '.join(names)}). "
            "Think of it as opening a toolbox: after this, the program can call tools from that library. "
            "On the map, an inked route appears toward that dependency."
        )
        action, effect = "reveal_nodes", "spawn"
        return title, explanation, {"action": action, "nodes": node_ids, "edges": edge_ids, "effect": effect}

    if isinstance(primary, ast.ClassDef):
        nid = name_index.get((module.file, primary.name))
        if nid:
            node_ids = [nid]
        bases = [getattr(b, "id", None) or getattr(b, "attr", "?") for b in primary.bases]
        base_txt = f" It inherits behavior from {', '.join(str(b) for b in bases)}." if bases else ""
        title = f"Define class `{primary.name}`"
        explanation = (
            f"Creates a blueprint named `{primary.name}` — a container for related data and methods."
            f"{base_txt} "
            "On the atlas, a new landmark (class node) appears; methods will attach to it as we continue."
        )
        return title, explanation, {"action": "reveal_nodes", "nodes": node_ids, "edges": edge_ids, "effect": "spawn"}

    if isinstance(primary, (ast.FunctionDef, ast.AsyncFunctionDef)):
        nid = name_index.get((module.file, primary.name))
        if nid:
            node_ids = [nid]
        params = [a.arg for a in primary.args.args]
        async_bit = "asynchronous " if isinstance(primary, ast.AsyncFunctionDef) else ""
        title = f"Define {async_bit}function `{primary.name}`"
        explanation = (
            f"Declares a reusable {async_bit}procedure `{primary.name}`"
            + (f" that accepts {', '.join(params)}." if params else ".")
            + " The body below is the recipe; it runs only when something calls this name. "
            "A function landmark lights up on the map."
        )
        return title, explanation, {"action": "reveal_nodes", "nodes": node_ids, "edges": edge_ids, "effect": "spawn"}

    if isinstance(primary, ast.Assign):
        targets = []
        for t in primary.targets:
            if isinstance(t, ast.Name):
                targets.append(t.id)
            elif isinstance(t, ast.Tuple):
                targets.extend(el.id for el in t.elts if isinstance(el, ast.Name))
        names = ", ".join(targets) or "a value"
        # Detect call on RHS
        call_name = None
        if isinstance(primary.value, ast.Call):
            call_name = _call_name(primary.value)
            cal = name_index.get((module.file, (call_name or "").split(".")[-1]))
            if cal:
                node_ids.append(cal)
                action, effect = "pulse", "flow"
        title = f"Store into `{names}`"
        explanation = (
            f"Computes a value and remembers it under the name(s) {names}."
            + (f" The value comes from calling `{call_name}`." if call_name else "")
            + " Later lines can reuse this name instead of recomputing. "
            "Watch the map for a data-flow shimmer on this symbol."
        )
        if node_ids and action == "narrate":
            action, effect = "reveal_nodes", "spawn"
        return title, explanation, {"action": action, "nodes": node_ids, "edges": edge_ids, "effect": effect}

    if isinstance(primary, ast.Return):
        title = "Return a result"
        explanation = (
            "Ends this function and sends a value back to whoever called it. "
            "On the map, energy flows outward from this function landmark."
        )
        if node_ids:
            action, effect = "pulse", "flow"
        return title, explanation, {"action": action or "pulse", "nodes": node_ids, "edges": edge_ids, "effect": effect}

    if isinstance(primary, ast.If):
        title = "Branch: decide which path to take"
        explanation = (
            "Checks a condition. If it is true, the indented block runs; otherwise Python may take an `else`/`elif` path. "
            "This is a fork in the road on the execution map."
        )
        return title, explanation, {"action": "focus", "nodes": node_ids, "edges": edge_ids, "effect": "focus"}

    if isinstance(primary, (ast.For, ast.While)):
        title = "Loop: repeat work"
        explanation = (
            "Repeats the indented block — either for each item in a collection (`for`) or while a condition holds (`while`). "
            "Visually, this is a cycle: the same landmarks may activate many times."
        )
        return title, explanation, {"action": "pulse", "nodes": node_ids, "edges": edge_ids, "effect": "flow"}

    if isinstance(primary, ast.Try):
        title = "Error safety net"
        explanation = (
            "Starts a protected region. If something fails inside, matching `except` blocks can recover instead of crashing."
        )
        return title, explanation, {"action": "focus", "nodes": node_ids, "edges": [], "effect": "focus"}

    if isinstance(primary, ast.Expr) and isinstance(primary.value, ast.Call):
        cname = _call_name(primary.value)
        cal = name_index.get((module.file, (cname or "").split(".")[-1]))
        if cal:
            node_ids.append(cal)
        title = f"Call `{cname}`"
        explanation = (
            f"Runs `{cname}` right now — jumping into that function’s recipe, then returning here. "
            "A call-route flashes on the atlas between the caller and the callee."
        )
        return title, explanation, {"action": "pulse", "nodes": node_ids, "edges": edge_ids, "effect": "flow"}

    if isinstance(primary, ast.Expr) and isinstance(getattr(primary, "value", None), ast.Constant):
        # docstring
        title = "Documentation string"
        explanation = (
            "A human-readable description of the module/class/function. Python stores it as help text; it does not change runtime logic."
        )
        return title, explanation, {"action": "narrate", "nodes": [], "edges": [], "effect": "dim"}

    # Fallback
    title, explanation = _explain_text_line(stripped, "python")
    if node_ids:
        return title, explanation, {"action": "reveal_nodes", "nodes": node_ids, "edges": [], "effect": "spawn"}
    return title, explanation, {"action": "narrate", "nodes": [], "edges": [], "effect": "focus"}


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST = f
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts)) if parts else "call"
    return "call"


def _explain_text_line(stripped: str, language: str) -> tuple[str, str]:
    if stripped.startswith("import ") or stripped.startswith("from ") or stripped.startswith("#include"):
        return ("Import dependency", "Loads another module’s tools into this file’s namespace.")
    if stripped.startswith(("class ", "struct ", "classdef ", "typedef struct")):
        return ("Type definition", "Starts a new data structure / object blueprint.")
    if stripped.startswith(("def ", "async def ", "function ", "func ", "fn ", "sub ")):
        return ("Function definition", "Starts a reusable procedure.")
    if stripped.startswith(("#define", "#ifdef", "#ifndef", "#endif", "#pragma", "#if ", "#else")):
        return ("Preprocessor directive", "Handled before compilation: defines constants/macros or conditionally includes code.")
    if stripped.startswith(("printf", "fprintf", "disp(", "cout", "println", "print(", "puts ", "cat(", "echo ")):
        return ("Output to console/file", "Writes text out — an I/O boundary where the program talks to the outside world.")
    if stripped.startswith(("plot(", "figure", "ggplot", "imshow", "scatter(", "hist(", "subplot")):
        return ("Plot / figure", "Produces a graphic; useful for the Results section of a paper.")
    if stripped.startswith("return "):
        return ("Return", "Sends a value back to the caller.")
    if stripped.startswith("if "):
        return ("Conditional", "Chooses a path based on a true/false check.")
    if stripped.startswith("for ") or stripped.startswith("while "):
        return ("Loop", "Repeats a block of work.")
    if "=" in stripped and not stripped.startswith("==") and "==" not in stripped.split("=")[0]:
        return ("Assignment", "Saves a computed value under a name for later use.")
    if stripped.endswith(":"):
        return ("Block header", "Opens an indented block (suite) that groups related statements.")
    return (
        "Execute statement",
        f"This {language} statement runs in order. Watch the atlas for any landmarks tied to symbols on this line.",
    )


def enrich_walkthrough_edges(walkthrough: dict[str, Any], graph: CodeGraph) -> dict[str, Any]:
    """Attach concrete edge ids for import/call visuals where possible."""
    # Build quick lookups
    import_edges = [e for e in graph.edges if e.kind == "import"]
    call_edges = [e for e in graph.edges if e.kind in {"call", "instantiation"}]
    node_by_id = {n.id: n for n in graph.nodes}

    for step in walkthrough.get("steps", []):
        visual = step.get("visual") or {}
        nodes = list(visual.get("nodes") or [])
        edges: list[str] = list(visual.get("edges") or [])
        if step.get("kind") in {"Import", "ImportFrom"}:
            for e in import_edges:
                if e.source in nodes or e.target in nodes:
                    edges.append(e.id)
                # also if external target name appears in code
                tgt = node_by_id.get(e.target)
                if tgt and tgt.name and tgt.name.split(".")[0] in step.get("code", ""):
                    if e.target not in nodes:
                        nodes.append(e.target)
                    edges.append(e.id)
        if step.get("kind") in {"Expr", "Assign"} and visual.get("effect") == "flow":
            for e in call_edges:
                if e.source in nodes or e.target in nodes:
                    edges.append(e.id)
        # Deduplicate
        visual["nodes"] = list(dict.fromkeys(nodes))
        visual["edges"] = list(dict.fromkeys(edges))
        step["visual"] = visual
    return walkthrough
