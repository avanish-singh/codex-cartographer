"""
Programmatic mapping API used by the CLI and the public web app.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codex_cartographer.explanations import attach_explanations
from codex_cartographer.ingestion import collect_source_files
from codex_cartographer.parsers import parse_source_file
from codex_cartographer.semantic import build_graph
from codex_cartographer.semantic.model import CodeGraph
from codex_cartographer.semantic.paper_semantics import build_paper_semantics
from codex_cartographer.viz import render_html
from codex_cartographer.walkthrough import build_walkthrough, enrich_walkthrough_edges


class MappingError(ValueError):
    """Raised when a path cannot be mapped into an atlas."""


def map_project(
    path: str | Path,
    *,
    output_html: str | Path,
    cluster_threshold: int = 150,
    max_steps: int = 800,
    paper_note: str | None = None,
) -> dict[str, Any]:
    """
    Map *path* (file or folder) to a self-contained HTML atlas.

    Returns summary metadata including the written HTML / JSON paths.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise MappingError(f"Path not found: {root}")

    sources = collect_source_files(root)
    if not sources:
        raise MappingError(
            "No supported source files found. Upload Python, JS/TS, C/C++, "
            "MATLAB/Octave, Java, Go, Rust, R, Julia, and related languages."
        )

    by_lang: dict[str, int] = {}
    for src in sources:
        by_lang[src.language] = by_lang.get(src.language, 0) + 1

    results = [parse_source_file(src) for src in sources]
    graph: CodeGraph = build_graph(
        results,
        source_path=str(root),
        cluster_threshold=cluster_threshold,
    )
    attach_explanations(graph)
    walkthrough = enrich_walkthrough_edges(
        build_walkthrough(results, graph, max_steps=max_steps), graph
    )
    graph.walkthrough = walkthrough
    graph.paper_semantics = build_paper_semantics(results, graph)
    if paper_note:
        graph.paper_semantics = dict(graph.paper_semantics or {})
        graph.paper_semantics["uploaded_paper_note"] = paper_note
        methods = graph.paper_semantics.get("methods_markdown") or ""
        graph.paper_semantics["methods_markdown"] = (
            methods
            + "\n\n### Uploaded paper\n\n"
            + paper_note
        )

    out_path = Path(output_html)
    html_path = render_html(graph, out_path)
    json_path = html_path.with_name(html_path.stem + ".graph.json")

    return {
        "html_path": html_path,
        "json_path": json_path,
        "files": len(sources),
        "languages": by_lang,
        "nodes": graph.metadata.get("node_count"),
        "edges": graph.metadata.get("edge_count"),
        "steps": len(walkthrough.get("steps", [])),
        "roles": list((graph.paper_semantics.get("roles") or {}).keys()),
        "condensed": bool(walkthrough.get("condensed")),
    }


def write_graph_json(graph_path: Path, payload: dict[str, Any]) -> None:
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
