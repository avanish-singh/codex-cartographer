"""Python parser using the standard-library ``ast`` module."""

from __future__ import annotations

import ast
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


def _snippet(source_lines: list[str], start: int, end: int, max_lines: int = 40) -> str:
    """Extract a bounded source snippet (1-indexed lines)."""
    if start < 1:
        start = 1
    end = min(end, len(source_lines), start + max_lines - 1)
    return "\n".join(source_lines[start - 1 : end])


def _name_of(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_of(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        return _name_of(node.value)
    if isinstance(node, ast.Call):
        return _name_of(node.func)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return repr(node.value)
    return node.__class__.__name__


class _PythonExtractor(ast.NodeVisitor):
    """Walk a module AST and fill a ModuleUnit."""

    def __init__(self, module: ModuleUnit, source_lines: list[str]) -> None:
        self.module = module
        self.source_lines = source_lines
        self._class_stack: list[ClassUnit] = []

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self.module.imports.append(
                ImportRef(
                    module=alias.name,
                    names=[alias.name],
                    alias=alias.asname,
                    line=node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        mod = node.module or ""
        names = [a.name for a in node.names]
        self.module.imports.append(
            ImportRef(
                module=mod,
                names=names,
                line=node.lineno,
                is_relative=bool(node.level),
            )
        )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        parent_q = (
            self._class_stack[-1].qualified_name if self._class_stack else self.module.file
        )
        qname = f"{parent_q}::{node.name}"
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        unit = ClassUnit(
            name=node.name,
            qualified_name=qname,
            line_start=node.lineno,
            line_end=end,
            snippet=_snippet(self.source_lines, node.lineno, end),
            bases=[_name_of(b) for b in node.bases],
        )
        self._class_stack.append(unit)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(child)
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        unit.attributes.append(
                            VariableUnit(
                                name=target.id,
                                line=child.lineno,
                                assigned_from=_name_of(child.value) or None,
                            )
                        )
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                unit.attributes.append(
                    VariableUnit(
                        name=child.target.id,
                        line=child.lineno,
                        annotation=_name_of(child.annotation) or None,
                        assigned_from=_name_of(child.value) if child.value else None,
                    )
                )
        self._class_stack.pop()
        if self._class_stack:
            # Nested class — attach to outer class as attribute-like for now.
            pass
        self.module.classes.append(unit)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._handle_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._handle_function(node, is_async=True)

    def _handle_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        is_async: bool,
    ) -> None:
        is_method = bool(self._class_stack)
        if is_method:
            parent_q = self._class_stack[-1].qualified_name
        else:
            parent_q = self.module.file
        qname = f"{parent_q}::{node.name}"
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        params = [a.arg for a in node.args.args]
        unit = FunctionUnit(
            name=node.name,
            qualified_name=qname,
            line_start=node.lineno,
            line_end=end,
            snippet=_snippet(self.source_lines, node.lineno, end),
            parameters=params,
            is_method=is_method,
            is_async=is_async,
            decorators=[_name_of(d) for d in node.decorator_list],
        )
        # Light data-flow: returns, assignments, calls inside this function only.
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                name = _name_of(child.value)
                if name:
                    unit.returns.append(name)
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        unit.assignments.append(
                            VariableUnit(
                                name=target.id,
                                line=child.lineno,
                                assigned_from=_name_of(child.value) or None,
                            )
                        )
            elif isinstance(child, ast.Call):
                callee = _name_of(child.func)
                if not callee:
                    continue
                arg_names = []
                for arg in child.args:
                    n = _name_of(arg)
                    if n:
                        arg_names.append(n)
                call = CallRef(callee=callee, line=child.lineno, argument_names=arg_names)
                unit.calls.append(call)
                # Heuristic: Capitalized callee → instantiation.
                base = callee.split(".")[-1]
                if base and base[0].isupper():
                    self.module.instantiations.append(call)

        if is_method:
            self._class_stack[-1].methods.append(unit)
        else:
            self.module.functions.append(unit)

    def visit_Assign(self, node: ast.Assign) -> Any:
        if self._class_stack:
            return
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.module.variables.append(
                    VariableUnit(
                        name=target.id,
                        line=node.lineno,
                        assigned_from=_name_of(node.value) or None,
                    )
                )
        # Detect if __name__ == "__main__" style is nearby via walk at module level.
        self.generic_visit(node)


class PythonParser(LanguageParser):
    """Parse Python source into ModuleUnit via ``ast``."""

    language = "python"
    extensions = (".py",)

    def parse(self, content: str, relative_path: str) -> ParseResult:
        lines = content.splitlines()
        module = ModuleUnit(
            file=relative_path,
            language=self.language,
            raw_content=content,
        )
        try:
            tree = ast.parse(content, filename=relative_path)
        except SyntaxError as exc:
            module.parse_error = f"SyntaxError: {exc.msg} (line {exc.lineno})"
            return ParseResult(module=module, success=False)

        module.docstring = ast.get_docstring(tree)
        module.has_main_guard = _has_main_guard(tree)

        extractor = _PythonExtractor(module, lines)
        extractor.visit(tree)
        module.top_level_calls = _top_level_calls(tree)
        return ParseResult(module=module, success=True)


def _top_level_calls(tree: ast.AST) -> list[CallRef]:
    """Calls made at module scope (including inside ``if __name__ == '__main__':``)."""
    calls: list[CallRef] = []
    if not isinstance(tree, ast.Module):
        return calls
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                callee = _name_of(node.func)
                if callee:
                    calls.append(CallRef(callee=callee, line=node.lineno))
    return calls


def _has_main_guard(tree: ast.AST) -> bool:
    """Detect ``if __name__ == '__main__':``."""
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if isinstance(test, ast.Compare):
            left = test.left
            if isinstance(left, ast.Name) and left.id == "__name__":
                for comp in test.comparators:
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        return True
    return False
