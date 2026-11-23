"""
Visualization renderer — writes a self-contained HTML atlas from a CodeGraph.

Depends only on the JSON graph contract; never imports parsers.
"""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path

from codex_cartographer.semantic.model import CodeGraph

_VIZ_DIR = Path(__file__).resolve().parent


def render_html(graph: CodeGraph, output_html: str | Path) -> Path:
    """
    Embed *graph* into the antique-map template and write a standalone HTML file.

    Also writes a sibling ``*.graph.json`` next to the HTML for inspection /
    alternate frontends.
    """
    output_html = Path(output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)

    template = (_VIZ_DIR / "template.html").read_text(encoding="utf-8")
    styles = (_VIZ_DIR / "styles.css").read_text(encoding="utf-8")
    app_js = (_VIZ_DIR / "app.js").read_text(encoding="utf-8")

    graph_dict = graph.to_dict()
    graph_json = json.dumps(graph_dict, ensure_ascii=False)

    html = (
        template.replace("__STYLES__", styles)
        .replace("__GRAPH_JSON__", graph_json)
        .replace("__APP_JS__", app_js)
    )
    output_html.write_text(html, encoding="utf-8")

    json_path = output_html.with_suffix(".graph.json")
    if output_html.suffix.lower() != ".html":
        json_path = Path(str(output_html) + ".graph.json")
    else:
        json_path = output_html.with_name(output_html.stem + ".graph.json")
    json_path.write_text(
        json.dumps(graph_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_html


def open_in_browser(html_path: Path) -> None:
    """Open the generated atlas in the default browser."""
    webbrowser.open(html_path.resolve().as_uri())
