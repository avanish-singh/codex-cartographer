"""
Structure-based explanation generator.

Isolated from parsers and the graph builder so an optional LLM-assisted
mode can be plugged in later without touching those layers.
"""

from __future__ import annotations

from typing import Protocol

from codex_cartographer.semantic.model import (
    EDGE_CALL,
    EDGE_CONTAINS,
    EDGE_DATA_FLOW,
    EDGE_IMPORT,
    EDGE_INHERITANCE,
    EDGE_INSTANTIATION,
    CodeGraph,
    GraphEdge,
    GraphNode,
)


class ExplanationBackend(Protocol):
    """Swap this for an LLM backend later."""

    def explain_node(self, node: GraphNode, edges: list[GraphEdge], graph: CodeGraph) -> str: ...


class StructuralExplanationBackend:
    """Plain-English explanations derived only from graph structure."""

    def explain_node(self, node: GraphNode, edges: list[GraphEdge], graph: CodeGraph) -> str:
        kind = node.kind
        tags = ", ".join(node.tags) if node.tags else "untagged"
        file_bit = f" in `{node.file}`" if node.file else ""

        incoming = [e for e in edges if e.target == node.id and e.source != node.id]
        outgoing = [e for e in edges if e.source == node.id and e.target != node.id]

        if kind == "module":
            contains = [e for e in outgoing if e.kind == EDGE_CONTAINS]
            imports = [e for e in outgoing if e.kind == EDGE_IMPORT]
            parts = [
                f"Module `{node.name}`{file_bit}.",
                f"Tagged as {tags}.",
                f"It contains {len(contains)} nested symbol(s)",
            ]
            if imports:
                parts.append(f"and imports {len(imports)} dependency(ies)")
            parts.append(".")
            if node.metadata.get("parse_error"):
                parts.append(f" Parse note: {node.metadata['parse_error']}")
            return " ".join(parts)

        if kind == "class":
            bases = [e for e in outgoing if e.kind == EDGE_INHERITANCE]
            methods = [e for e in outgoing if e.kind == EDGE_CONTAINS]
            base_names = _target_names(bases, graph)
            msg = (
                f"Class `{node.name}`{file_bit}, tagged as {tags}. "
                f"It declares {len(methods)} method(s)/member(s)."
            )
            if base_names:
                msg += f" Inherits from: {', '.join(base_names)}."
            return msg

        if kind == "function":
            calls = [e for e in outgoing if e.kind == EDGE_CALL]
            called_by = [e for e in incoming if e.kind == EDGE_CALL]
            flows = [
                e
                for e in edges
                if e.kind == EDGE_DATA_FLOW and (e.source == node.id or e.target == node.id)
            ]
            params = node.metadata.get("parameters") or []
            msg = (
                f"{'Async function' if node.metadata.get('is_async') else 'Function'} "
                f"`{node.name}`{file_bit}, tagged as {tags}."
            )
            if params:
                msg += f" Parameters: {', '.join(params)}."
            msg += f" It calls {len(calls)} symbol(s) and is called by {len(called_by)} site(s)."
            if flows:
                msg += f" Local data-flow notes: {len(flows)}."
            if "entry_point" in node.tags:
                msg += " This looks like an entry point into the program."
            return msg

        if kind == "variable":
            return (
                f"Variable `{node.name}`{file_bit}, tagged as {tags}. "
                "Tracked because it sits at module or class scope."
            )

        if kind == "external":
            used = [e for e in incoming if e.kind == EDGE_IMPORT]
            return (
                f"External dependency `{node.name}`. "
                f"Referenced by {len(used)} import edge(s). Not part of the mapped source tree."
            )

        if kind == "unparsed":
            err = node.metadata.get("parse_error") or "unknown parse failure"
            return (
                f"File `{node.name}` could not be fully parsed ({err}). "
                "Shown as an unparsed node so the map stays complete."
            )

        if kind == "cluster":
            members = node.metadata.get("member_count", "?")
            return (
                f"Cluster `{node.name}` groups {members} nodes under one folder/module "
                "to keep large maps readable. Click to expand."
            )

        return f"`{node.name}` ({kind}), tagged as {tags}."


def explain_edge(edge: GraphEdge) -> str:
    """Short relationship blurb for hover/click."""
    labels = {
        EDGE_IMPORT: "Import relationship",
        EDGE_CALL: "Function/method call",
        EDGE_INHERITANCE: "Class inheritance",
        EDGE_INSTANTIATION: "Object instantiation",
        EDGE_DATA_FLOW: "Intra-function data flow",
        EDGE_CONTAINS: "Structural containment",
    }
    base = labels.get(edge.kind, edge.kind)
    if edge.label:
        return f"{base}: {edge.label}"
    return base


def attach_explanations(
    graph: CodeGraph,
    backend: ExplanationBackend | None = None,
) -> CodeGraph:
    """Fill ``node.explanation`` for every node using *backend*."""
    backend = backend or StructuralExplanationBackend()
    for node in graph.nodes:
        related = [
            e
            for e in graph.edges
            if e.source == node.id or e.target == node.id
        ]
        node.explanation = backend.explain_node(node, related, graph)
    # Stash edge explanations in metadata for the viz layer.
    for edge in graph.edges:
        edge.metadata.setdefault("explanation", explain_edge(edge))
    return graph


def _target_names(edges: list[GraphEdge], graph: CodeGraph) -> list[str]:
    by_id = {n.id: n for n in graph.nodes}
    names = []
    for e in edges:
        n = by_id.get(e.target)
        names.append(n.name if n else e.target)
    return names
