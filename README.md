# Codex Cartographer

Interactive atlas of how a codebase works — line by line, in 2D and 3D.

Point it at a file or folder. It parses the sources, builds a semantic dependency graph, and opens a self-contained HTML map in the browser. The left panel walks through the code with plain-English explanations; the right panel shows a live map of modules, functions, calls, and imports.

**Live demo:** [https://codex-cartographer.onrender.com](https://codex-cartographer.onrender.com)  
Upload a project zip and/or a research paper PDF, or try the built-in sample.

For LLM-guided paper breakdown (section explanations + methodology flowchart), set on the host:

```bash
export OPENAI_API_KEY=sk-...
# optional:
export OPENAI_MODEL=gpt-4o-mini
export OPENAI_BASE_URL=https://api.openai.com/v1
```

Without a key, the paper session still splits headings and shows a basic method flow.

---

## Features

- Line-by-line walkthrough synced to a 2D/3D dependency map
- Multi-language projects in one atlas (Python, JS/TS, C/C++, MATLAB/Octave, Java, Go, Rust, R, Julia, and more)
- Map modes: focus dependents, show all, or grow as you walk
- Inspector for any node or edge (depends on / used by / source excerpt)
- Research-paper summary for ML / experiment codebases
- CLI for local use, plus a hosted upload demo

---

## Requirements

- Python 3.10+
- A modern browser (Chrome, Firefox, Edge, or Safari)
- Network once for the 3D library CDN (2D mode works offline)

---

## Install

```bash
git clone https://github.com/avanish-singh/codex-cartographer.git
cd codex-cartographer
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .
```

Optional web demo dependencies:

```bash
pip install -e ".[web]"
```

---

## Usage

```bash
# list supported languages
codex-cartographer --list-languages

# map a sample
codex-cartographer samples/todo_cli
codex-cartographer samples/mixed_lang -o output/mixed_atlas.html

# map any local file or folder
codex-cartographer /path/to/project
codex-cartographer /path/to/file.py -o atlas.html

# useful flags
codex-cartographer /path/to/project --no-open
codex-cartographer /path/to/project --json-only
codex-cartographer /path/to/big_repo --max-steps 800
```

Default outputs:

| File | Description |
|------|-------------|
| `output/codex_map.html` | Interactive atlas |
| `output/codex_map.graph.json` | Semantic graph (same model as the HTML) |

Open the HTML in a real browser (IDE previews usually cannot run WebGL).

### Hosted / local web UI

```bash
uvicorn webapp.server:app --host 0.0.0.0 --port 7860
```

Then open `http://127.0.0.1:7860`. The same app is deployed at the live demo URL above (`Dockerfile` / `render.yaml` included).

---

## Atlas controls

| Control | Behaviour |
|---------|-----------|
| Play / Next / Prev | Walk the source; Space and arrow keys also work |
| Next def (`D`) | Jump to the next function or class |
| Map mode | **Focus deps** (default), **All**, or **Grow** |
| Labels | Smart / All / Off |
| Click node or edge | Open inspector (depends on, used by, excerpt) |
| Right-click node | Jump walkthrough to its definition |
| Legend | Filter landmarks by semantic tag |
| Paper summary | Methods-oriented outline of detected ML roles |

---

## Supported languages

| Language | Extensions | Parser |
|----------|------------|--------|
| Python | `.py` | `ast` |
| JavaScript / TypeScript | `.js .mjs .cjs .jsx .ts .tsx` | tree-sitter |
| C | `.c .h` | heuristics |
| C++ / CUDA | `.cpp .cc .cxx .hpp .hh .hxx .ipp .inl .cu .cuh` | heuristics |
| C# | `.cs` | heuristics |
| Java | `.java` | heuristics |
| Kotlin | `.kt .kts` | heuristics |
| Swift | `.swift` | heuristics |
| Go | `.go` | heuristics |
| Rust | `.rs` | heuristics |
| PHP | `.php` | heuristics |
| Ruby | `.rb` | heuristics |
| R | `.r .R .Rmd` | heuristics |
| Julia | `.jl` | heuristics |
| MATLAB / Octave | `.m .mlx` | heuristics |

Heuristic backends recover imports/includes, definitions, and calls without a full type checker. Name collisions across files (for example several `main` functions) are not cross-linked.

---

## Architecture

```
path → ingestion → parsers → semantic graph (JSON) → explanations → walkthrough → HTML atlas
```

```
codex_cartographer/
  cli.py                 # command-line entry
  pipeline.py            # shared mapping API (CLI + web)
  ingestion/             # .gitignore-aware file walk
  parsers/               # Python, JS/TS, and generic language parsers
  semantic/              # graph model, tags, data-flow, paper summary
  explanations/          # structure-based node explanations
  walkthrough/           # line-by-line narration script
  viz/                   # HTML / CSS / JS atlas renderer
webapp/                  # FastAPI upload demo
samples/                 # todo_cli and mixed_lang examples
tests/
```

Layers talk only through the JSON graph, so parsers, explanations, and rendering stay independent.

---

## Research-paper summary

For ML-style code, symbols are tagged by role (architecture, loss, training, dataset, evaluation, and related). The **Paper summary** view drafts a Methods-style outline from that structure. It is a starting point for writing, not a finished paper.

---

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

---

## Limitations

- Heuristic languages use name-based resolution (no full types / macros / templates).
- Data-flow edges are light and stay inside a single function.
- Explanations come from code structure, not a language model.
- Very large repos: use `--max-steps`, `--cluster-threshold`, or map a subfolder.

---

## License

MIT

**Author:** Avanish Singh
