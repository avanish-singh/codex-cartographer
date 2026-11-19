"""
Canonical JSON graph schema — the contract between parsers, semantics, and viz.

Every layer reads/writes this format. Swap a layer freely as long as the
JSON shape stays stable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


# Node kinds
KIND_MODULE = "module"
KIND_CLASS = "class"
KIND_FUNCTION = "function"
KIND_VARIABLE = "variable"
KIND_CLUSTER = "cluster"
KIND_UNPARSED = "unparsed"
KIND_EXTERNAL = "external"

# Edge kinds
EDGE_CONTAINS = "contains"
EDGE_IMPORT = "import"
EDGE_CALL = "call"
EDGE_INHERITANCE = "inheritance"
EDGE_INSTANTIATION = "instantiation"
EDGE_DATA_FLOW = "data_flow"
EDGE_CLUSTER_MEMBER = "cluster_member"

# Semantic tags
TAG_ENTRY = "entry_point"
TAG_CORE = "core_logic"
TAG_UTILITY = "utility"
TAG_IO = "io_boundary"
TAG_EXTERNAL = "external_dependency"
TAG_TEST = "test"
TAG_UNPARSED = "unparsed"


@dataclass
class GraphNode:
    id: str
    kind: str
    name: str
    qualified_name: str
    file: str | None = None
    language: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    snippet: str = ""
    tags: list[str] = field(default_factory=list)
    explanation: str = ""
    parent_id: str | None = None
    cluster_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    kind: str
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodeGraph:
    """Serializable semantic model — single source of truth for the map."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    walkthrough: dict[str, Any] = field(default_factory=dict)
    paper_semantics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "walkthrough": self.walkthrough,
            "paper_semantics": self.paper_semantics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodeGraph:
        nodes = [GraphNode(**n) for n in data.get("nodes", [])]
        edges = [GraphEdge(**e) for e in data.get("edges", [])]
        return cls(
            nodes=nodes,
            edges=edges,
            metadata=dict(data.get("metadata", {})),
            walkthrough=dict(data.get("walkthrough", {})),
            paper_semantics=dict(data.get("paper_semantics", {})),
        )


def new_metadata(source_path: str, **extra: Any) -> dict[str, Any]:
    return {
        "tool": "codex-cartographer",
        "version": "0.1.0",
        "source_path": source_path,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cluster_threshold": 150,
        **extra,
    }
