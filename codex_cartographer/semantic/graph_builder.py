"""
Build the language-agnostic CodeGraph from parse results.

This is the only module that decides node/edge identity. Parsers feed
ModuleUnits in; the visualization layer consumes the JSON graph out.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Iterable

from codex_cartographer.parsers.base import FunctionUnit, ModuleUnit, ParseResult
from codex_cartographer.semantic.dataflow import data_flow_edges_for_function
from codex_cartographer.semantic.model import (
    EDGE_CALL,
    EDGE_CLUSTER_MEMBER,
    EDGE_CONTAINS,
    EDGE_IMPORT,
    EDGE_INHERITANCE,
    EDGE_INSTANTIATION,
    KIND_CLASS,
    KIND_CLUSTER,
    KIND_EXTERNAL,
    KIND_FUNCTION,
    KIND_MODULE,
    KIND_UNPARSED,
    KIND_VARIABLE,
    CodeGraph,
    GraphEdge,
    GraphNode,
    new_metadata,
)
from codex_cartographer.semantic.tags import (
    apply_node_kind_tags,
    function_tags,
    module_tags,
)


class _IdFactory:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)

    def __call__(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}{self._counters[prefix]}"


def _stable_id(kind: str, qualified: str) -> str:
    """Deterministic IDs so re-runs produce stable graphs."""
    safe = re.sub(r"[^a-zA-Z0-9_.:/@+-]+", "_", qualified)
    return f"{kind}:{safe}"


def build_graph(
    parse_results: Iterable[ParseResult],
    *,
    source_path: str,
    cluster_threshold: int = 150,
) -> CodeGraph:
    """
    Construct the canonical CodeGraph from parsed modules.

    Steps:
      1. Module / class / function / variable nodes + contains edges
      2. Import edges (internal + external stubs)
      3. Inheritance, instantiation, call edges
      4. Light intra-function data-flow edges
      5. Optional folder clustering when node count exceeds threshold
    """
    results = list(parse_results)
    ids = _IdFactory()
    graph = CodeGraph(metadata=new_metadata(source_path, cluster_threshold=cluster_threshold))

    module_nodes: dict[str, GraphNode] = {}  # relative file -> node
    symbol_index: dict[str, str] = {}  # simple name / qname -> node id
    file_index: dict[str, str] = {}  # stem / module path hints -> module node id

    # --- Pass 1: structural nodes -------------------------------------------------
    for result in results:
        module = result.module
        file_tags = module_tags(module)
        is_unparsed = bool(module.parse_error) and not (module.functions or module.classes)

        mod_id = _stable_id("module", module.file)
        mod_node = GraphNode(
            id=mod_id,
            kind=KIND_UNPARSED if is_unparsed else KIND_MODULE,
            name=PurePosixPath(module.file).name,
            qualified_name=module.file,
            file=module.file,
            language=module.language,
            line_start=1,
            line_end=module.raw_content.count("\n") + 1 if module.raw_content else None,
            snippet=_module_snippet(module),
            tags=list(file_tags),
            metadata={
                "parse_error": module.parse_error,
                "docstring": module.docstring,
            },
        )
        apply_node_kind_tags(mod_node)
        graph.nodes.append(mod_node)
        module_nodes[module.file] = mod_node
        file_index[module.file] = mod_id
        file_index[module.file.replace("/", ".").removesuffix(".py").removesuffix(".ts").removesuffix(".js")] = mod_id
        stem = PurePosixPath(module.file).stem
        file_index.setdefault(stem, mod_id)

        for cls in module.classes:
            cls_id = _stable_id("class", cls.qualified_name)
            cls_node = GraphNode(
                id=cls_id,
                kind=KIND_CLASS,
                name=cls.name,
                qualified_name=cls.qualified_name,
                file=module.file,
                language=module.language,
                line_start=cls.line_start,
                line_end=cls.line_end,
                snippet=cls.snippet,
                tags=[t for t in file_tags if t != "unparsed"] or ["core_logic"],
                parent_id=mod_id,
            )
            apply_node_kind_tags(cls_node)
            graph.nodes.append(cls_node)
            _register_symbol(symbol_index, cls.name, cls.qualified_name, cls_id)
            graph.edges.append(
                GraphEdge(
                    id=ids("e"),
                    source=mod_id,
                    target=cls_id,
                    kind=EDGE_CONTAINS,
                    label="contains class",
                )
            )

            for method in cls.methods:
                _add_function_node(
                    graph,
                    ids,
                    module,
                    method,
                    parent_id=cls_id,
                    file_tags=file_tags,
                    symbol_index=symbol_index,
                )

            for attr in cls.attributes:
                var_id = _stable_id("var", f"{cls.qualified_name}.{attr.name}")
                graph.nodes.append(
                    GraphNode(
                        id=var_id,
                        kind=KIND_VARIABLE,
                        name=attr.name,
                        qualified_name=f"{cls.qualified_name}.{attr.name}",
                        file=module.file,
                        language=module.language,
                        line_start=attr.line,
                        line_end=attr.line,
                        tags=["utility"],
                        parent_id=cls_id,
                    )
                )
                graph.edges.append(
                    GraphEdge(
                        id=ids("e"),
                        source=cls_id,
                        target=var_id,
                        kind=EDGE_CONTAINS,
                        label="attribute",
                    )
                )

        for func in module.functions:
            _add_function_node(
                graph,
                ids,
                module,
                func,
                parent_id=mod_id,
                file_tags=file_tags,
                symbol_index=symbol_index,
            )

        for var in module.variables:
            # Skip dunder noise except meaningful constants.
            if var.name.startswith("__") and var.name.endswith("__"):
                continue
            var_id = _stable_id("var", f"{module.file}::{var.name}")
            graph.nodes.append(
                GraphNode(
                    id=var_id,
                    kind=KIND_VARIABLE,
                    name=var.name,
                    qualified_name=f"{module.file}::{var.name}",
                    file=module.file,
                    language=module.language,
                    line_start=var.line,
                    line_end=var.line,
                    tags=["utility"],
                    parent_id=mod_id,
                    metadata={"assigned_from": var.assigned_from},
                )
            )
            graph.edges.append(
                GraphEdge(
                    id=ids("e"),
                    source=mod_id,
                    target=var_id,
                    kind=EDGE_CONTAINS,
                    label="variable",
                )
            )

    # --- Pass 2: imports ----------------------------------------------------------
    external_nodes: dict[str, str] = {}
    for result in results:
        module = result.module
        mod_id = module_nodes[module.file].id
        for imp in module.imports:
            target_id = _resolve_import(imp.module, file_index, module_nodes)
            if target_id is None:
                ext_key = imp.module or (imp.names[0] if imp.names else "unknown")
                if ext_key not in external_nodes:
                    ext_id = _stable_id("external", ext_key)
                    graph.nodes.append(
                        GraphNode(
                            id=ext_id,
                            kind=KIND_EXTERNAL,
                            name=ext_key,
                            qualified_name=ext_key,
                            tags=["external_dependency"],
                        )
                    )
                    external_nodes[ext_key] = ext_id
                target_id = external_nodes[ext_key]
            graph.edges.append(
                GraphEdge(
                    id=ids("e"),
                    source=mod_id,
                    target=target_id,
                    kind=EDGE_IMPORT,
                    label=imp.module or ",".join(imp.names),
                    metadata={"line": imp.line, "names": imp.names},
                )
            )

    # --- Pass 3: inheritance, calls, instantiation --------------------------------
    for result in results:
        module = result.module
        for cls in module.classes:
            cls_id = symbol_index.get(cls.qualified_name)
            if not cls_id:
                continue
            for base in cls.bases:
                base_id = _resolve_callee(base, symbol_index, current_file=module.file)
                if base_id is None:
                    # External base class stub
                    if base not in external_nodes:
                        ext_id = _stable_id("external", f"class:{base}")
                        graph.nodes.append(
                            GraphNode(
                                id=ext_id,
                                kind=KIND_EXTERNAL,
                                name=base,
                                qualified_name=base,
                                tags=["external_dependency"],
                            )
                        )
                        external_nodes[base] = ext_id
                    base_id = external_nodes[base]
                graph.edges.append(
                    GraphEdge(
                        id=ids("e"),
                        source=cls_id,
                        target=base_id,
                        kind=EDGE_INHERITANCE,
                        label=f"extends {base}",
                    )
                )

        all_funcs = list(module.functions)
        for cls in module.classes:
            all_funcs.extend(cls.methods)

        for func in all_funcs:
            func_id = symbol_index.get(func.qualified_name)
            if not func_id:
                continue
            for call in func.calls:
                callee_id = _resolve_callee(call.callee, symbol_index, current_file=module.file)
                if callee_id and callee_id != func_id:
                    graph.edges.append(
                        GraphEdge(
                            id=ids("e"),
                            source=func_id,
                            target=callee_id,
                            kind=EDGE_CALL,
                            label=call.callee,
                            metadata={"line": call.line},
                        )
                    )
            # Instantiations attributed to the function's enclosing module.
            for inst in module.instantiations:
                if inst.line < func.line_start or inst.line > func.line_end:
                    continue
                target = _resolve_callee(inst.callee, symbol_index, current_file=module.file)
                if target:
                    graph.edges.append(
                        GraphEdge(
                            id=ids("e"),
                            source=func_id,
                            target=target,
                            kind=EDGE_INSTANTIATION,
                            label=f"new {inst.callee}",
                            metadata={"line": inst.line},
                        )
                    )

            # Light data-flow
            graph.edges.extend(
                data_flow_edges_for_function(func, func_node_id=func_id, id_factory=ids)
            )

        # Script-level calls: module node → callee (MATLAB scripts, R, Julia, __main__ blocks …)
        mod_id = module_nodes[module.file].id
        for call in module.top_level_calls:
            callee_id = _resolve_callee(call.callee, symbol_index, current_file=module.file)
            if callee_id and callee_id != mod_id:
                is_ctor = callee_id.startswith("class:")
                graph.edges.append(
                    GraphEdge(
                        id=ids("e"),
                        source=mod_id,
                        target=callee_id,
                        kind=EDGE_INSTANTIATION if is_ctor else EDGE_CALL,
                        label=(f"new {call.callee}" if is_ctor else call.callee),
                        metadata={"line": call.line, "script_level": True},
                    )
                )

    # Deduplicate near-identical call/instantiation edges.
    graph.edges = _dedupe_edges(graph.edges)

    # --- Pass 4: clustering -------------------------------------------------------
    if len(graph.nodes) > cluster_threshold:
        _apply_clustering(graph, ids)

    graph.metadata["node_count"] = len(graph.nodes)
    graph.metadata["edge_count"] = len(graph.edges)
    graph.metadata["languages"] = sorted(
        {n.language for n in graph.nodes if n.language}
    )
    graph.metadata["files_parsed"] = len(results)
    return graph


def _add_function_node(
    graph: CodeGraph,
    ids: _IdFactory,
    module: ModuleUnit,
    func: FunctionUnit,
    *,
    parent_id: str,
    file_tags: list[str],
    symbol_index: dict[str, str],
) -> GraphNode:
    func_id = _stable_id("fn", func.qualified_name)
    tags = function_tags(module, func.name, file_tags)
    node = GraphNode(
        id=func_id,
        kind=KIND_FUNCTION,
        name=func.name,
        qualified_name=func.qualified_name,
        file=module.file,
        language=module.language,
        line_start=func.line_start,
        line_end=func.line_end,
        snippet=func.snippet,
        tags=tags,
        parent_id=parent_id,
        metadata={
            "parameters": func.parameters,
            "is_async": func.is_async,
            "is_method": func.is_method,
            "decorators": func.decorators,
        },
    )
    apply_node_kind_tags(node)
    graph.nodes.append(node)
    _register_symbol(symbol_index, func.name, func.qualified_name, func_id)
    graph.edges.append(
        GraphEdge(
            id=ids("e"),
            source=parent_id,
            target=func_id,
            kind=EDGE_CONTAINS,
            label="contains function",
        )
    )
    return node


def _module_snippet(module: ModuleUnit, max_lines: int = 25) -> str:
    if module.raw_content:
        lines = module.raw_content.splitlines()[:max_lines]
        return "\n".join(lines)
    return ""


def _resolve_import(
    module_name: str,
    file_index: dict[str, str],
    module_nodes: dict[str, GraphNode],
) -> str | None:
    if not module_name:
        return None
    # Path-like imports (#include "../c/signal.h", require './store', source("utils/x.R"))
    path_like = module_name.replace("\\", "/")
    while path_like.startswith(("./", "../")):
        path_like = path_like.split("/", 1)[1] if "/" in path_like else ""
    if path_like:
        for path, node in module_nodes.items():
            if path == path_like or path.endswith("/" + path_like):
                return node.id
            # extension-less relative import (JS/TS): './store' → store.js / store.ts
            stem_path = path.rsplit(".", 1)[0]
            if stem_path == path_like or stem_path.endswith("/" + path_like):
                return node.id
    # Direct hits
    candidates = [
        module_name,
        module_name.replace(".", "/") + ".py",
        module_name.replace(".", "/") + ".ts",
        module_name.replace(".", "/") + ".js",
        module_name.lstrip("./"),
    ]
    # relative JS: ./store -> store.js etc. handled via stem
    for c in candidates:
        if c in file_index:
            return file_index[c]
        if c in module_nodes:
            return module_nodes[c].id
    # Match by suffix path
    norm = module_name.replace(".", "/").lstrip("./")
    for path, node in module_nodes.items():
        stem_path = path.rsplit(".", 1)[0]
        if stem_path.endswith(norm) or path.startswith(norm):
            return node.id
    return None


def _resolve_callee(
    callee: str,
    symbol_index: dict[str, str],
    *,
    current_file: str | None = None,
) -> str | None:
    """
    Resolve a call target with file-aware preference.

    Order: exact qualified name → same-file symbol → globally *unique* simple
    name. Ambiguous names shared by several files (``main``, ``update`` …)
    are not linked, so we never draw a false cross-language route.
    """
    if not callee:
        return None
    if callee in symbol_index and "::" in callee:
        return symbol_index[callee]
    simple = callee.split(".")[-1].split("::")[-1].rstrip("!")
    candidates = symbol_index.get("__candidates__", {}).get(simple, [])  # type: ignore[union-attr]
    if current_file:
        same_file = [cid for cid in candidates if cid.split(":", 1)[1].startswith(current_file + "::")]
        if len(same_file) == 1:
            return same_file[0]
        if len(same_file) > 1:
            # Prefer a top-level function over a method of the same name.
            top = [cid for cid in same_file if cid.count("::") == 1]
            return top[0] if len(top) == 1 else same_file[0]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return None  # ambiguous across files → skip rather than guess
    return symbol_index.get(callee) or symbol_index.get(simple)


def _register_symbol(symbol_index: dict, name: str, qualified_name: str, node_id: str) -> None:
    symbol_index[qualified_name] = node_id
    symbol_index.setdefault(name, node_id)
    cands = symbol_index.setdefault("__candidates__", {})
    cands.setdefault(name, [])
    if node_id not in cands[name]:
        cands[name].append(node_id)


def _dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    seen: set[tuple] = set()
    out: list[GraphEdge] = []
    for e in edges:
        key = (e.source, e.target, e.kind, e.label)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _apply_clustering(graph: CodeGraph, ids: _IdFactory) -> None:
    """
    Collapse nodes into folder clusters when the graph is large.

    Cluster nodes are added; members get ``cluster_id``. The visualizer
    hides clustered members until the cluster is expanded.
    """
    folders: dict[str, list[GraphNode]] = defaultdict(list)
    for node in graph.nodes:
        if node.kind in {KIND_EXTERNAL, KIND_CLUSTER}:
            continue
        if not node.file:
            continue
        folder = str(PurePosixPath(node.file).parent)
        if folder == ".":
            folder = "(root)"
        folders[folder].append(node)

    for folder, members in folders.items():
        # Only cluster folders that actually reduce clutter.
        if len(members) < 8:
            continue
        cluster_id = _stable_id("cluster", folder)
        cluster = GraphNode(
            id=cluster_id,
            kind=KIND_CLUSTER,
            name=folder,
            qualified_name=f"cluster:{folder}",
            tags=["utility"],
            metadata={"member_count": len(members), "folder": folder, "collapsed": True},
        )
        graph.nodes.append(cluster)
        for member in members:
            member.cluster_id = cluster_id
            graph.edges.append(
                GraphEdge(
                    id=ids("e"),
                    source=cluster_id,
                    target=member.id,
                    kind=EDGE_CLUSTER_MEMBER,
                    label="member",
                )
            )


# Public re-exports for the package
__all__ = ["build_graph"]
