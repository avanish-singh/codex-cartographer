"""
Codex Cartographer CLI.

Usage:
  codex-cartographer path/to/code
  codex-cartographer path/to/file.py -o output/map.html
  python -m codex_cartographer samples/todo_cli
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codex_cartographer import __version__
from codex_cartographer.pipeline import MappingError, map_project
from codex_cartographer.viz import open_in_browser


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

    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    if output:
        out_path = Path(output)
    else:
        out_path = out_dir / "codex_map.html"

    html_target = out_path if out_path.suffix != ".json" else out_path.with_suffix(".html")
    print(f"Ingesting {root} …")
    try:
        summary = map_project(
            root,
            output_html=html_target,
            cluster_threshold=cluster_threshold,
            max_steps=max_steps,
        )
    except MappingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    langs = ", ".join(f"{k}={v}" for k, v in sorted(summary["languages"].items()))
    print(f"  found {summary['files']} source file(s): {langs}")
    if summary.get("condensed"):
        print(
            f"  large project: walkthrough condensed to {summary['steps']} key steps "
            "(use --max-steps 0 for all)"
        )
    print(
        f"  graph: {summary['nodes']} nodes, {summary['edges']} edges, "
        f"{summary['steps']} walkthrough steps"
    )
    if summary.get("roles"):
        print(f"  paper roles detected: {', '.join(summary['roles'][:8])}")

    if json_only:
        json_path = out_path if out_path.suffix == ".json" else Path(summary["json_path"])
        if json_path != Path(summary["json_path"]):
            json_path.write_text(
                Path(summary["json_path"]).read_text(encoding="utf-8"), encoding="utf-8"
            )
        print(f"Wrote {json_path.resolve()}")
        return 0

    print(f"Wrote {Path(summary['html_path']).resolve()}")
    print(f"Wrote {Path(summary['json_path']).resolve()}")
    if not no_open:
        print("Opening browser …")
        open_in_browser(summary["html_path"])
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
