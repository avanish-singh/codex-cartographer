"""
Light intra-function data-flow edges.

v1 scope (confirmed): params → returns → assignments *within* a function only.
No cross-function taint tracking.
"""

from __future__ import annotations

from codex_cartographer.parsers.base import FunctionUnit
from codex_cartographer.semantic.model import EDGE_DATA_FLOW, GraphEdge


def data_flow_edges_for_function(
    func: FunctionUnit,
    *,
    func_node_id: str,
    id_factory,
) -> list[GraphEdge]:
    """
    Emit data_flow edges that annotate relationships local to *func*.

    Because variables are not always separate graph nodes, we encode light
    data-flow as self-describing edges on the function node with metadata
    describing the flow. The visualizer can show these in the data-flow layer.
    """
    edges: list[GraphEdge] = []
    params = set(func.parameters)

    for assign in func.assignments:
        if not assign.assigned_from:
            continue
        # param → local assignment
        src_name = assign.assigned_from.split(".")[0]
        if src_name in params or any(src_name == a.name for a in func.assignments):
            edges.append(
                GraphEdge(
                    id=id_factory("e"),
                    source=func_node_id,
                    target=func_node_id,
                    kind=EDGE_DATA_FLOW,
                    label=f"{assign.assigned_from} → {assign.name}",
                    metadata={
                        "flow": "assignment",
                        "from": assign.assigned_from,
                        "to": assign.name,
                        "line": assign.line,
                        "function": func.qualified_name,
                    },
                )
            )

    for ret in func.returns:
        base = ret.split(".")[0].split("(")[0]
        related = base in params or any(base == a.name for a in func.assignments)
        if related or base in params:
            edges.append(
                GraphEdge(
                    id=id_factory("e"),
                    source=func_node_id,
                    target=func_node_id,
                    kind=EDGE_DATA_FLOW,
                    label=f"return {ret}",
                    metadata={
                        "flow": "return",
                        "from": ret,
                        "to": "return",
                        "function": func.qualified_name,
                    },
                )
            )

    # Param used as call argument — still intra-function.
    for call in func.calls:
        for arg in call.argument_names:
            base = arg.split(".")[0]
            if base in params:
                edges.append(
                    GraphEdge(
                        id=id_factory("e"),
                        source=func_node_id,
                        target=func_node_id,
                        kind=EDGE_DATA_FLOW,
                        label=f"{base} → {call.callee}()",
                        metadata={
                            "flow": "arg",
                            "from": base,
                            "to": call.callee,
                            "line": call.line,
                            "function": func.qualified_name,
                        },
                    )
                )

    return edges
