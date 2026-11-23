"""
JavaScript / TypeScript / JSX / TSX parser via tree-sitter.

Kept behind the LanguageParser interface so Babel (or another engine)
could replace tree-sitter later without touching the semantic layer.
"""

from __future__ import annotations

from typing import Any

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

# Lazy-loaded language objects so import still works if grammars are missing.
_JS_LANGUAGE = None
_TS_LANGUAGE = None
_TSX_LANGUAGE = None
_PARSER = None


def _ensure_runtime() -> Any:
    global _JS_LANGUAGE, _TS_LANGUAGE, _TSX_LANGUAGE, _PARSER
    if _PARSER is not None:
        return _PARSER
    import tree_sitter_javascript as tsjs
    import tree_sitter_typescript as tsts
    from tree_sitter import Language, Parser

    _JS_LANGUAGE = Language(tsjs.language())
    _TS_LANGUAGE = Language(tsts.language_typescript())
    _TSX_LANGUAGE = Language(tsts.language_tsx())
    _PARSER = Parser()
    return _PARSER


def _pick_language(relative_path: str, language: str):
    _ensure_runtime()
    lower = relative_path.lower()
    if lower.endswith(".tsx"):
        return _TSX_LANGUAGE
    if lower.endswith(".ts"):
        return _TS_LANGUAGE
    if language == "typescript":
        return _TS_LANGUAGE
    return _JS_LANGUAGE


def _node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _snippet_from_node(source_lines: list[str], node, max_lines: int = 40) -> str:
    start = node.start_point[0] + 1
    end = node.end_point[0] + 1
    end = min(end, len(source_lines), start + max_lines - 1)
    return "\n".join(source_lines[start - 1 : end])


def _child_by_field(node, field: str):
    return node.child_by_field_name(field)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _identifier_name(source: bytes, node) -> str:
    if node is None:
        return ""
    t = node.type
    if t in ("identifier", "property_identifier", "type_identifier"):
        return _node_text(source, node)
    if t == "member_expression":
        obj = _child_by_field(node, "object")
        prop = _child_by_field(node, "property")
        left = _identifier_name(source, obj)
        right = _identifier_name(source, prop)
        return f"{left}.{right}" if left and right else left or right
    if t == "subscript_expression":
        return _identifier_name(source, _child_by_field(node, "object"))
    if t == "new_expression":
        return _identifier_name(source, _child_by_field(node, "constructor"))
    # Fallback: first identifier descendant.
    for child in _walk(node):
        if child.type in ("identifier", "property_identifier", "type_identifier"):
            return _node_text(source, child)
    return ""


class JavaScriptTypeScriptParser(LanguageParser):
    """Parse JS/TS/JSX/TSX into ModuleUnit using tree-sitter."""

    language = "javascript"
    extensions = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx")
    also_handles = ("typescript",)

    def parse(self, content: str, relative_path: str) -> ParseResult:
        lang_label = (
            "typescript"
            if relative_path.lower().endswith((".ts", ".tsx"))
            else "javascript"
        )
        module = ModuleUnit(
            file=relative_path,
            language=lang_label,
            raw_content=content,
        )
        lines = content.splitlines()
        try:
            parser = _ensure_runtime()
            language = _pick_language(relative_path, lang_label)
            parser.language = language
            source = content.encode("utf-8")
            tree = parser.parse(source)
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            module.parse_error = f"tree-sitter error: {exc}"
            return ParseResult(module=module, success=False)

        root = tree.root_node
        if root.has_error:
            # Still extract what we can; mark as partial success.
            module.parse_error = "Parse tree contains errors; results may be incomplete."

        try:
            self._extract(module, source, lines, root)
        except Exception as exc:  # noqa: BLE001
            module.parse_error = f"Extraction error: {exc}"
            return ParseResult(module=module, success=False)

        module.has_main_guard = _looks_like_entry(module, content)
        return ParseResult(module=module, success=module.parse_error is None or bool(module.functions or module.classes))

    def _extract(
        self,
        module: ModuleUnit,
        source: bytes,
        lines: list[str],
        root,
    ) -> None:
        for node in root.children:
            self._visit_statement(module, source, lines, node, parent_class=None)

    def _visit_statement(
        self,
        module: ModuleUnit,
        source: bytes,
        lines: list[str],
        node,
        parent_class: ClassUnit | None,
    ) -> None:
        t = node.type

        if t in ("import_statement", "lexical_declaration", "export_statement"):
            if t == "import_statement":
                self._handle_import(module, source, node)
            elif t == "export_statement":
                # Recurse into exported declaration.
                for child in node.children:
                    if child.type not in ("export", "default", "type", ";", "string"):
                        self._visit_statement(module, source, lines, child, parent_class)
            elif t == "lexical_declaration":
                self._handle_lexical(module, source, lines, node, parent_class)
            return

        if t in ("function_declaration", "generator_function_declaration"):
            fn = self._build_function(module, source, lines, node, parent_class)
            if parent_class:
                parent_class.methods.append(fn)
            else:
                module.functions.append(fn)
            return

        if t in ("class_declaration", "abstract_class_declaration"):
            cls = self._build_class(module, source, lines, node)
            module.classes.append(cls)
            return

        if t == "expression_statement":
            for child in node.children:
                if child.type == "call_expression":
                    call = self._build_call(source, child)
                    if call:
                        # Top-level call — keep on module via a synthetic note in instantiations
                        # only if it looks like construction.
                        if call.callee[:1].isupper() or call.callee.startswith("new "):
                            module.instantiations.append(call)
                if child.type == "assignment_expression":
                    left = _child_by_field(child, "left")
                    right = _child_by_field(child, "right")
                    name = _identifier_name(source, left)
                    if name and parent_class is None:
                        module.variables.append(
                            VariableUnit(
                                name=name.split(".")[-1],
                                line=child.start_point[0] + 1,
                                assigned_from=_identifier_name(source, right) or None,
                            )
                        )

    def _handle_import(self, module: ModuleUnit, source: bytes, node) -> None:
        source_node = _child_by_field(node, "source")
        mod_name = _node_text(source, source_node).strip("'\"") if source_node else ""
        names: list[str] = []
        for child in _walk(node):
            if child.type in ("identifier", "import_specifier"):
                if child.type == "identifier":
                    text = _node_text(source, child)
                    if text not in names and text != "from":
                        names.append(text)
                else:
                    name_node = _child_by_field(child, "name")
                    if name_node:
                        names.append(_node_text(source, name_node))
        module.imports.append(
            ImportRef(
                module=mod_name,
                names=names or [mod_name],
                line=node.start_point[0] + 1,
                is_relative=mod_name.startswith("."),
            )
        )

    def _handle_lexical(
        self,
        module: ModuleUnit,
        source: bytes,
        lines: list[str],
        node,
        parent_class: ClassUnit | None,
    ) -> None:
        for child in node.children:
            if child.type != "variable_declarator":
                continue
            name_node = _child_by_field(child, "name")
            value_node = _child_by_field(child, "value")
            name = _identifier_name(source, name_node)
            if not name:
                continue
            if value_node and value_node.type in (
                "arrow_function",
                "function_expression",
                "generator_function",
            ):
                fn = self._build_function(
                    module,
                    source,
                    lines,
                    value_node,
                    parent_class,
                    name_override=name,
                    line_node=child,
                )
                if parent_class:
                    parent_class.methods.append(fn)
                else:
                    module.functions.append(fn)
            elif parent_class is None:
                module.variables.append(
                    VariableUnit(
                        name=name,
                        line=child.start_point[0] + 1,
                        assigned_from=_identifier_name(source, value_node) or None,
                    )
                )

    def _build_class(
        self,
        module: ModuleUnit,
        source: bytes,
        lines: list[str],
        node,
    ) -> ClassUnit:
        name_node = _child_by_field(node, "name")
        name = _identifier_name(source, name_node) or "AnonymousClass"
        qname = f"{module.file}::{name}"
        bases: list[str] = []
        heritage = None
        for child in node.children:
            if child.type in ("class_heritage", "extends_clause"):
                heritage = child
                break
        if heritage:
            for child in _walk(heritage):
                if child.type in ("identifier", "member_expression", "type_identifier"):
                    b = _identifier_name(source, child)
                    if b and b not in bases and b != "extends":
                        bases.append(b)
                        break

        unit = ClassUnit(
            name=name,
            qualified_name=qname,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            snippet=_snippet_from_node(lines, node),
            bases=bases,
        )

        body = _child_by_field(node, "body")
        if body:
            for child in body.children:
                if child.type in ("method_definition", "field_definition", "public_field_definition"):
                    if child.type == "method_definition":
                        fn = self._build_method(module, source, lines, child, unit)
                        unit.methods.append(fn)
                    else:
                        n = _child_by_field(child, "property") or _child_by_field(child, "name")
                        attr = _identifier_name(source, n)
                        if attr:
                            unit.attributes.append(
                                VariableUnit(name=attr, line=child.start_point[0] + 1)
                            )
        return unit

    def _build_method(
        self,
        module: ModuleUnit,
        source: bytes,
        lines: list[str],
        node,
        parent: ClassUnit,
    ) -> FunctionUnit:
        name_node = _child_by_field(node, "name")
        name = _identifier_name(source, name_node) or "method"
        return self._build_function(
            module,
            source,
            lines,
            node,
            parent,
            name_override=name,
            line_node=node,
            force_method=True,
        )

    def _build_function(
        self,
        module: ModuleUnit,
        source: bytes,
        lines: list[str],
        node,
        parent_class: ClassUnit | None,
        name_override: str | None = None,
        line_node=None,
        force_method: bool = False,
    ) -> FunctionUnit:
        anchor = line_node or node
        name_node = _child_by_field(node, "name")
        name = name_override or _identifier_name(source, name_node) or "anonymous"
        parent_q = parent_class.qualified_name if parent_class else module.file
        qname = f"{parent_q}::{name}"

        params: list[str] = []
        params_node = _child_by_field(node, "parameters")
        if params_node:
            for child in params_node.children:
                if child.type in ("identifier", "required_parameter", "optional_parameter"):
                    if child.type == "identifier":
                        params.append(_node_text(source, child))
                    else:
                        pattern = _child_by_field(child, "pattern")
                        n = _identifier_name(source, pattern) if pattern else _identifier_name(source, child)
                        if n:
                            params.append(n)

        unit = FunctionUnit(
            name=name,
            qualified_name=qname,
            line_start=anchor.start_point[0] + 1,
            line_end=anchor.end_point[0] + 1,
            snippet=_snippet_from_node(lines, anchor),
            parameters=params,
            is_method=force_method or parent_class is not None,
            is_async="async" in {c.type for c in node.children},
        )

        body = _child_by_field(node, "body")
        search_root = body or node
        for child in _walk(search_root):
            if child.type == "return_statement":
                # First meaningful child after 'return'
                for sub in child.children:
                    if sub.type not in ("return", ";"):
                        n = _identifier_name(source, sub)
                        if n:
                            unit.returns.append(n)
                        break
            elif child.type == "lexical_declaration":
                for decl in child.children:
                    if decl.type != "variable_declarator":
                        continue
                    n = _identifier_name(source, _child_by_field(decl, "name"))
                    v = _identifier_name(source, _child_by_field(decl, "value"))
                    if n:
                        unit.assignments.append(
                            VariableUnit(
                                name=n,
                                line=decl.start_point[0] + 1,
                                assigned_from=v or None,
                            )
                        )
            elif child.type == "call_expression":
                call = self._build_call(source, child)
                if call:
                    unit.calls.append(call)
            elif child.type == "new_expression":
                ctor = _identifier_name(source, _child_by_field(child, "constructor"))
                if ctor:
                    call = CallRef(
                        callee=ctor,
                        line=child.start_point[0] + 1,
                    )
                    unit.calls.append(call)
                    module.instantiations.append(call)

        return unit

    def _build_call(self, source: bytes, node) -> CallRef | None:
        func = _child_by_field(node, "function")
        callee = _identifier_name(source, func)
        if not callee:
            return None
        args: list[str] = []
        args_node = _child_by_field(node, "arguments")
        if args_node:
            for child in args_node.children:
                if child.type in ("(", ")", ","):
                    continue
                n = _identifier_name(source, child)
                if n:
                    args.append(n)
        return CallRef(callee=callee, line=node.start_point[0] + 1, argument_names=args)


def _looks_like_entry(module: ModuleUnit, content: str) -> bool:
    """Heuristic entry detection for JS/TS (require.main / main())."""
    if "require.main === module" in content or "require.main==module" in content:
        return True
    if "import.meta.url" in content and "process.argv" in content:
        return True
    names = {f.name for f in module.functions}
    if "main" in names and ("main()" in content or "main();" in content):
        return True
    return False
