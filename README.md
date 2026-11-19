# Codex Cartographer

**An interactive map atlas of how a codebase actually works — line by line, in 2D and 3D.**

Point Codex Cartographer at a **file or a folder**. It walks the tree, parses every supported language, builds one language-agnostic semantic graph, and opens a self-contained HTML atlas in your browser. The left side narrates the code one line at a time; the right side is a live 3D (or 2D) map that labels what that line touches, shades everything unrelated, and lets you click any landmark to see what it is, what it depends on, and who uses it.

---

## 1. Install on any computer (macOS / Linux / Windows)

You need **Python 3.10 or newer** and a normal web browser (Chrome, Edge, Firefox, Safari). Internet is needed **once** when the atlas opens (it loads the 3D library from a CDN).

### Step 1 — copy the project

Either clone/download this repository, or copy the `visual_code` folder to the new machine (USB, zip, Git — anything). Below, `<PROJECT>` is wherever it lands, e.g.

- macOS: `/Users/you/Desktop/visual_code`
- Linux: `/home/you/visual_code`
- Windows: `C:\Users\you\Desktop\visual_code`

### Step 2 — create a virtual environment and install

**macOS / Linux (Terminal):**

```bash
cd <PROJECT>
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

**Windows (PowerShell):**

```powershell
cd <PROJECT>
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

> If PowerShell refuses to activate: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry.  
> If `python3` is missing on Linux: `sudo apt install python3 python3-venv python3-pip` (Debian/Ubuntu).

### Step 3 — check it works

```bash
codex-cartographer --list-languages     # shows every language / extension that will be mapped
codex-cartographer samples/mixed_lang    # opens a C + C++ + MATLAB + Java + Go + Rust + R + Julia atlas
```

Every new terminal session: activate the environment first (`source .venv/bin/activate` or `.\.venv\Scripts\Activate.ps1`). Alternatively run without activating: `<PROJECT>/.venv/bin/codex-cartographer …` (or `.venv\Scripts\codex-cartographer.exe` on Windows).

---

## 2. Map any file or folder on your machine

```bash
# a single file (any supported language)
codex-cartographer /Users/you/research/train_model.py
codex-cartographer C:\work\solver\run_experiment.m

# a whole project folder (all files, all languages, cross-file dependencies)
codex-cartographer /Users/you/research/my_project
codex-cartographer ~/code/firmware            # C/C++ tree
codex-cartographer "D:\Lab\matlab toolbox"    # quote paths with spaces

# choose where the atlas is written
codex-cartographer ~/code/my_project -o ~/Desktop/my_project_atlas.html

# just build, don't auto-open the browser
codex-cartographer ~/code/my_project --no-open

# only the JSON semantic model
codex-cartographer ~/code/my_project --json-only

# very large project: cap the narrated steps (default 1500; 0 = narrate every line)
codex-cartographer ~/code/big_repo --max-steps 800

# no argument → it asks you for a path
codex-cartographer
```

Outputs (default `output/codex_map.html` + `output/codex_map.graph.json`, or your `-o` path + sibling `.graph.json`). Double-click the HTML any time later — it is self-contained.

> Open the HTML in a **real browser**. IDE text previews cannot run WebGL, so the 3D scene will look blank there. If your browser blocks the CDN, switch to **2D** — it needs nothing external.

---

## 3. What you see (and how the 3D side explains things)

| Region | What it does |
|--------|--------------|
| **File tabs** | One tab per file, with its language. Click to jump to that chapter. |
| **Left · card** | Current line, its plain-English meaning, and *why it is connected*: “calls …”, “called by …”, “inherits …”, “defined in …”. Every name is clickable → inspector. |
| **Left · code** | Full source; the narrated line is highlighted; click any line to jump there. |
| **Right · 3D map** | The landmark(s) for the current line glow rust-red and grow; their routes light up with moving particles; every unrelated node is shaded. **Labels** float above highlighted nodes, modules and classes. A **callout** is pinned to the active landmark and says what is happening. The **camera flies** to frame the neighbourhood (uncheck *Camera follows* to orbit freely). |
| **Hover** node / edge | Tooltip: kind, file:line, tags, explanation, dependencies (“imports …”, “called by …”). |
| **Click** node / edge | **Inspector** panel: explanation, *Depends on* / *Used by* lists (clickable), local data flow, source excerpt. Buttons: *Go to line* (jump the walkthrough there) and *Focus deps here*. |
| **Right-click** node | Jump the walkthrough to the line that defines it. |
| **Legend** | Colours per tag and per route type with counts. Click a tag to light every landmark carrying it (e.g. all `ML: training` functions). |
| **Map mode** | **Focus deps** (default: dependents highlighted, rest shaded), **All** (whole graph visible with highlight), **Grow** (landmarks appear as lines are visited). |
| **Labels** | Smart / All / Off. |
| **Speed / Play / Next def** | Space = play/pause, ←/→ = step, `D` = next definition, Esc = clear inspection. |
| **Paper summary** | Methods-ready description of the training pipeline (see §5). |

Node positions are stable between steps — the map does not re-shuffle every line, so you can follow a route with your eyes.

---

## 4. Languages, multi-file projects and mixed languages

`codex-cartographer --list-languages` prints the live table. Currently:

| Language | Extensions | Backend |
|----------|------------|---------|
| Python | `.py` | stdlib `ast` (precise) |
| JavaScript / TypeScript | `.js .mjs .cjs .jsx .ts .tsx` | tree-sitter (precise) |
| C | `.c .h` | regex heuristics |
| C++ / CUDA | `.cpp .cc .cxx .hpp .hh .hxx .ipp .inl .cu .cuh` | regex heuristics |
| C# | `.cs` | regex heuristics |
| Java | `.java` | regex heuristics |
| Kotlin | `.kt .kts` | regex heuristics |
| Swift | `.swift` | regex heuristics |
| Go | `.go` | regex heuristics |
| Rust | `.rs` | regex heuristics |
| PHP | `.php` | regex heuristics |
| Ruby | `.rb` | regex heuristics |
| R | `.r .R .Rmd` | regex heuristics |
| Julia | `.jl` | regex heuristics |
| MATLAB / Octave | `.m .mlx` (Objective-C `.m` auto-detected) | regex heuristics |

**What “heuristics” means.** For these languages the parser recognises `#include`/`import`/`using`/`library()`/`addpath`, function and class/struct/`classdef` definitions with their line ranges, calls inside bodies, script-level calls, returns and assignments. It does not type-check, so overloaded names or macros can produce a missed or extra route — but every file still becomes a module node, every definition a landmark, and every resolvable call a route.

**Multi-file behaviour.**
- One shared graph for the whole folder. `#include "../c/signal.h"` from C++ links to the C header; a MATLAB script calling `compute_rmse(...)` links to `utils/compute_rmse.m`; Python `from pkg.mod import X` links to `pkg/mod.py`.
- Call resolution prefers **same-file** symbols, then a **globally unique** name. A name defined in several files (e.g. `main` in three languages) is **not** cross-linked, so you never get a false route between unrelated files.
- The walkthrough opens each file with a **chapter step** (“depends on … / used by …”), then narrates it. **Focus deps** shades everything outside the current dependency neighbourhood, so you always know *which module has which dependence*.
- Above `--cluster-threshold` (150) nodes, folders collapse into clusters; above ~1500 narrated lines the walkthrough is **condensed** to definitions, imports, calls and returns (see `--max-steps`).

`samples/mixed_lang/` is a ready-made polyglot project (C ↔ C++ header sharing, MATLAB script ↔ helper functions in sub-folders, Java, Go, Rust, R, Julia). Try:

```bash
codex-cartographer samples/mixed_lang -o output/mixed_atlas.html
```

---

## 5. Research-paper semantics

For ML/research code the graph is additionally tagged with roles (`ml_dataset`, `ml_preprocessing`, `ml_architecture`, `ml_loss`, `ml_optimizer`, `ml_training`, `ml_hyperparameter_tuning`, `ml_evaluation`, `ml_metrics`, `ml_checkpointing`, …) detected from symbol names and library usage. **Paper summary** opens a Methods-section draft (markdown) listing the model components, loss, optimiser, training loop, evaluation and the cross-file dependency chain — copy it straight into your writing and edit. It works across languages (a MATLAB `fit_linear_model` and a C++ `mse_loss` are both picked up).

---

## 6. Pipeline & architecture

```
path → ingestion → parsers → semantic graph (JSON) → explanations → walkthrough → HTML atlas
```

```
visual_code/
├── codex_cartographer/
│   ├── cli.py                    # CLI entry (--list-languages, --max-steps, -o, --no-open, --json-only)
│   ├── ingestion/walker.py       # .gitignore-aware walk, binary/huge-file skip
│   ├── parsers/
│   │   ├── base.py               # ModuleUnit IR + LanguageParser ABC
│   │   ├── registry.py           # language → parser dispatch
│   │   ├── python_parser.py      # ast
│   │   ├── js_ts_parser.py       # tree-sitter
│   │   └── generic_parser.py     # regex specs: C/C++/C#/Java/Kotlin/Swift/Go/Rust/PHP/Ruby/R/Julia/MATLAB
│   ├── semantic/
│   │   ├── model.py              # CodeGraph / node / edge schema (single source of truth)
│   │   ├── tags.py               # heuristic tags (entry, I/O, test, utility …)
│   │   ├── dataflow.py           # light intra-function flow
│   │   ├── graph_builder.py      # IR → JSON graph, file-aware call resolution, clustering
│   │   └── paper_semantics.py    # ML role tags + Methods draft
│   ├── explanations/generator.py # structure-based text (LLM-ready seam)
│   ├── walkthrough/builder.py    # line-by-line steps, language-aware, condensing for big repos
│   └── viz/
│       ├── renderer.py           # write HTML + sibling .graph.json
│       ├── template.html · styles.css · app.js   # 3D (3d-force-graph + sprite labels) & 2D (D3)
├── samples/todo_cli/             # Python + JS/TS demo
├── samples/mixed_lang/           # C, C++, MATLAB/Octave, Java, Go, Rust, R, Julia demo
├── tests/
└── output/
```

**Contract:** parsers → graph JSON ←→ viz / explanations. Swap any layer as long as the JSON shape holds.

### Adding another language

- Regex-level support: add a `LanguageSpec` to `LANGUAGE_SPECS` in `parsers/generic_parser.py` (import / function / class patterns, comment prefixes, block style). Extensions register automatically.
- Precise support: implement `LanguageParser` (see `base.py`) and add it to `_PARSERS` in `parsers/registry.py`. `semantic/` and `viz/` need no changes.

### Optional LLM explanations later

Implement `ExplanationBackend.explain_node(...)` and pass it to `attach_explanations(graph, backend=...)`.

---

## 7. Tests

```bash
pip install -e ".[dev]"
pytest -q
```

Covers the Python/JS sample, the mixed-language sample (cross-file `#include`, MATLAB script → helper calls, C++ inheritance, no false `main` links) and walkthrough condensing.

---

## 8. Known limitations

- Heuristic languages are name-based: no type resolution, macros/templates/overloads may miss or add a route.
- Data flow is intentionally light and intra-function only.
- Explanations are structural templates, not LLM prose.
- The 3D scene needs a real browser and a one-time CDN load; 2D works fully offline.
- Extremely large monorepos: use `--max-steps`, `--cluster-threshold`, or point at a sub-folder.

---

## License

MIT — use it, fork it, chart boldly.
