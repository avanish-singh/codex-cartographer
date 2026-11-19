"""Smoke tests for the semantic graph pipeline."""

from pathlib import Path

from codex_cartographer.explanations import attach_explanations
from codex_cartographer.ingestion import collect_source_files
from codex_cartographer.parsers import parse_source_file
from codex_cartographer.semantic import build_graph
from codex_cartographer.semantic.paper_semantics import build_paper_semantics
from codex_cartographer.viz import render_html
from codex_cartographer.walkthrough import build_walkthrough, enrich_walkthrough_edges

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "todo_cli"
MIXED = ROOT / "samples" / "mixed_lang"


def _run(path: Path, **kwargs):
    sources = collect_source_files(path)
    results = [parse_source_file(s) for s in sources]
    graph = build_graph(results, source_path=str(path), cluster_threshold=150)
    attach_explanations(graph)
    graph.walkthrough = enrich_walkthrough_edges(build_walkthrough(results, graph, **kwargs), graph)
    graph.paper_semantics = build_paper_semantics(results, graph)
    return sources, results, graph


def test_sample_pipeline(tmp_path: Path) -> None:
    sources, _results, graph = _run(SAMPLE)
    assert len(sources) >= 5
    assert graph.metadata["node_count"] > 0
    assert any(n.kind == "function" for n in graph.nodes)
    assert any(n.kind == "module" for n in graph.nodes)
    assert any(e.kind == "import" for e in graph.edges)
    assert len(graph.walkthrough.get("steps", [])) > 10
    assert "methods_markdown" in graph.paper_semantics
    # `if __name__ == "__main__": main()` yields a script-level call edge
    assert any(e.metadata.get("script_level") for e in graph.edges)
    html = render_html(graph, tmp_path / "map.html")
    assert html.exists()
    text = html.read_text(encoding="utf-8")
    assert "GRAPH_DATA" in text
    assert "walkthrough" in text
    assert "btn-play" in text
    assert "data-map-mode" in text
    assert "paper_semantics" in text
    assert "inspector" in text
    assert "3d-force-graph" in text and "three-spritetext" in text


def test_mixed_language_project() -> None:
    sources, results, graph = _run(MIXED)
    langs = {s.language for s in sources}
    assert {"c", "cpp", "java", "go", "rust", "matlab", "r", "julia"} <= langs
    assert all(r.success for r in results)

    by_id = {n.id: n for n in graph.nodes}
    names = {(n.file, n.name) for n in graph.nodes if n.kind in {"function", "class"}}
    assert ("c/signal.c", "signal_smooth") in names
    assert ("cpp/trainer.cpp", "LinearModel") in names
    assert ("go/main.go", "centroid") in names
    assert ("rust/lib.rs", "Vocabulary") in names
    assert ("matlab/utils/compute_rmse.m", "compute_rmse") in names
    assert ("r/analysis.R", "bootstrap_mean") in names
    assert ("julia/solver.jl", "solve") in names

    # #include resolves to the header inside the project
    internal_imports = {
        (by_id[e.source].file, by_id[e.target].file)
        for e in graph.edges
        if e.kind == "import" and by_id[e.target].kind != "external"
    }
    assert ("c/signal.c", "c/signal.h") in internal_imports
    assert ("cpp/trainer.cpp", "c/signal.h") in internal_imports

    # MATLAB script → function-in-another-file call routes
    cross_file_calls = {
        (by_id[e.source].file, by_id[e.target].name)
        for e in graph.edges
        if e.kind == "call" and by_id[e.source].file != by_id[e.target].file
    }
    assert ("matlab/run_experiment.m", "load_dataset") in cross_file_calls
    assert ("matlab/run_experiment.m", "compute_rmse") in cross_file_calls

    # Same-named `main` in several files must not be cross-linked
    for e in graph.edges:
        if e.kind == "call" and by_id[e.target].name == "main":
            assert by_id[e.source].file == by_id[e.target].file

    # C++ inheritance
    assert any(
        e.kind == "inheritance" and by_id[e.source].name == "LinearModel" and by_id[e.target].name == "Model"
        for e in graph.edges
    )

    # Multi-file walkthrough has one chapter step per file
    steps = graph.walkthrough["steps"]
    assert sum(1 for s in steps if s["kind"] == "chapter") == len(sources)
    assert any(s["kind"] == "definition" and "signal_create" in s["title"] for s in steps)


def test_walkthrough_condenses_big_projects() -> None:
    _sources, _results, graph = _run(MIXED, max_steps=60)
    wt = graph.walkthrough
    assert wt["condensed"] is True
    assert len(wt["steps"]) <= 60
    # definitions and chapters survive condensing
    assert any(s["kind"] == "chapter" for s in wt["steps"])
    assert any(s["kind"] == "definition" for s in wt["steps"])
