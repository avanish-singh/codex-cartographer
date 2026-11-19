"""
Codex Cartographer CLI.

Usage:
  codex-cartographer path/to/code
  codex-cartographer path/to/file.py -o output/map.html
  python -m codex_cartographer samples/todo_cli
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codex_cartographer import __version__
from codex_cartographer.explanations import attach_explanations
from codex_cartographer.ingestion import collect_source_files
from codex_cartographer.parsers import parse_source_file
from codex_cartographer.semantic import build_graph
from codex_cartographer.semantic.paper_semantics import build_paper_semantics
from codex_cartographer.viz import open_in_browser, render_html
from codex_cartographer.walkthrough import build_walkthrough, enrich_walkthrough_edges


def _prompt_path() -> str:
    try:
        return input("Enter a file or folder path to map: ").strip()
    except EOFError:
        return ""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codex-cartographer",
        description="Map how a codebase actually works — antique atlas edition.",
    )
    p.add_argument(
        "path",
        nargs="?",
        help="File or folder to analyze (prompts if omitted)",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output HTML path (default: output/codex_map.html)",
    )
    p.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the browser after rendering",
    )
    p.add_argument(
        "--cluster-threshold",
        type=int,
        default=150,
        help="Cluster by folder when node count exceeds this (default: 150)",
    )
    p.add_argument(
        "--json-only",
        action="store_true",
        help="Write only the graph JSON (skip HTML)",
    )
    p.add_argument(
        "--max-steps",
        type=int,
        default=1500,
        help="Condense the walkthrough to at most N steps for big projects (0 = no limit)",
    )
    p.add_argument(
        "--list-languages",
        action="store_true",
        help="Print supported languages / extensions and exit",
    )
    p.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return p


def print_languages() -> None:
    from codex_cartographer.ingestion.walker import SUPPORTED_EXTENSIONS
    from codex_cartographer.parsers.registry import supported_languages

    by_lang: dict[str, list[str]] = {}
    for ext, lang in SUPPORTED_EXTENSIONS.items():
        by_lang.setdefault(lang, []).append(ext)
    backends = supported_languages()
    print(f"{'language':<14}{'backend':<28}extensions")
    for lang in sorted(by_lang):
        backend = backends.get(lang, "GenericRegexParser")
        print(f"{lang:<14}{backend:<28}{', '.join(sorted(by_lang[lang]))}")


def run(
    path: str,
    *,
    output: str | None,
    no_open: bool,
    cluster_threshold: int,
    json_only: bool,
    max_steps: int = 1500,
) -> int:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        print(f"error: path not found: {root}", file=sys.stderr)
        return 1

    print(f"Ingesting {root} …")
    sources = collect_source_files(root)
    if not sources:
        print(
            "error: no supported source files found. Run `codex-cartographer --list-languages` "
            "to see the extensions that are mapped.",
            file=sys.stderr,
        )
        return 1
    by_lang: dict[str, int] = {}
    for s in sources:
        by_lang[s.language] = by_lang.get(s.language, 0) + 1
    print(f"  found {len(sources)} source file(s): " + ", ".join(f"{k}={v}" for k, v in sorted(by_lang.items())))

    print("Parsing …")
    results = []
    failures = 0
    for src in sources:
        result = parse_source_file(src)
        results.append(result)
        if not result.success:
            failures += 1
            err = result.module.parse_error or "unknown"
            print(f"  ! {src.relative_path}: {err}")
    print(f"  parsed {len(results) - failures}/{len(results)} cleanly")

    print("Building semantic model …")
    graph = build_graph(
        results,
        source_path=str(root),
        cluster_threshold=cluster_threshold,
    )
    print("Generating explanations …")
    attach_explanations(graph)
    print("Building line-by-line walkthrough …")
    walkthrough = enrich_walkthrough_edges(
        build_walkthrough(results, graph, max_steps=max_steps), graph
    )
    graph.walkthrough = walkthrough
    if walkthrough.get("condensed"):
        print(f"  large project: walkthrough condensed to {len(walkthrough['steps'])} key steps (use --max-steps 0 for all)")
    print("Building research-paper semantic summary …")
    graph.paper_semantics = build_paper_semantics(results, graph)
    roles = list((graph.paper_semantics.get("roles") or {}).keys())
    print(
        f"  graph: {graph.metadata.get('node_count')} nodes, "
        f"{graph.metadata.get('edge_count')} edges, "
        f"{len(walkthrough.get('steps', []))} walkthrough steps"
    )
    if roles:
        print(f"  paper roles detected: {', '.join(roles[:8])}")

    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    if output:
        out_path = Path(output)
    else:
        out_path = out_dir / "codex_map.html"

    if json_only:
        json_path = out_path if out_path.suffix == ".json" else out_path.with_suffix(".graph.json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")
        print(f"Wrote {json_path.resolve()}")
        return 0

    print("Rendering atlas …")
    html_path = render_html(graph, out_path)
    print(f"Wrote {html_path.resolve()}")
    print(f"Wrote {html_path.with_name(html_path.stem + '.graph.json').resolve()}")

    if not no_open:
        print("Opening browser …")
        open_in_browser(html_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_languages:
        print_languages()
        return 0
    path = args.path or _prompt_path()
    if not path:
        print("error: no path provided", file=sys.stderr)
        return 1
    return run(
        path,
        output=args.output,
        no_open=args.no_open,
        cluster_threshold=args.cluster_threshold,
        json_only=args.json_only,
        max_steps=args.max_steps,
    )


if __name__ == "__main__":
    raise SystemExit(main())
