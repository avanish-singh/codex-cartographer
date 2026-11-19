"""
Research-paper oriented semantic summary of a codebase.

Especially tuned for ML training pipelines (model, loss, data, tuning,
evaluation) so authors can draft Methods / Experimental Setup sections
from the atlas JSON.
"""

from __future__ import annotations

import re
from typing import Any

from codex_cartographer.parsers.base import ModuleUnit, ParseResult
from codex_cartographer.semantic.model import CodeGraph, GraphNode

# Role tags (also attached onto graph nodes)
ROLE_DATASET = "ml_dataset"
ROLE_PREPROCESS = "ml_preprocessing"
ROLE_ARCHITECTURE = "ml_architecture"
ROLE_LOSS = "ml_loss"
ROLE_OPTIMIZER = "ml_optimizer"
ROLE_TRAINING = "ml_training"
ROLE_EVAL = "ml_evaluation"
ROLE_TUNING = "ml_hyperparameter_tuning"
ROLE_CALLBACK = "ml_callback"
ROLE_METRICS = "ml_metrics"
ROLE_CHECKPOINT = "ml_checkpointing"

ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (ROLE_LOSS, re.compile(r"(loss|criterion|objective_fn|exp_loss|sobolev)", re.I)),
    (ROLE_ARCHITECTURE, re.compile(r"(model|network|layer|make_model|SobolevModel|Dense|Sequential)", re.I)),
    (ROLE_TRAINING, re.compile(r"(train_step|fit|train\b|epoch|warmup|EMAWeights)", re.I)),
    (ROLE_EVAL, re.compile(r"(test_step|evaluate|predict|scatter_plot|metric)", re.I)),
    (ROLE_TUNING, re.compile(r"(optuna|trial|objective|hyperparam|N_TRIALS)", re.I)),
    (ROLE_CALLBACK, re.compile(r"(callback|CosineWithWarmup|EarlyStopping|ReduceLR|Pruning)", re.I)),
    (ROLE_PREPROCESS, re.compile(r"(engineer_feature|scaler|RobustScaler|preprocess|sample_weight|synthetic)", re.I)),
    (ROLE_DATASET, re.compile(r"(csv|dataset|dataframe|load_data|read_csv|CSV_PATH|train_test_split)", re.I)),
    (ROLE_CHECKPOINT, re.compile(r"(save|checkpoint|ARTIFACT|joblib|savefig)", re.I)),
    (ROLE_OPTIMIZER, re.compile(r"(optimizer|Adam|SGD|learning_rate|base_lr)", re.I)),
    (ROLE_METRICS, re.compile(r"(mae|mse|rmse|r2|accuracy|metrics)", re.I)),
]


def attach_ml_role_tags(graph: CodeGraph) -> None:
    """Annotate nodes with ML/research role tags when names match."""
    for node in graph.nodes:
        blob = f"{node.name} {node.qualified_name} {node.snippet[:200]}"
        for role, pattern in ROLE_PATTERNS:
            if pattern.search(blob) and role not in node.tags:
                node.tags.append(role)


def build_paper_semantics(
    parse_results: list[ParseResult],
    graph: CodeGraph,
) -> dict[str, Any]:
    """
    Produce a Methods-oriented semantic brief for research writing.

    Stored on ``graph.paper_semantics`` and shown at the end of the walkthrough.
    """
    attach_ml_role_tags(graph)

    by_role: dict[str, list[dict[str, str]]] = {r: [] for r, _ in ROLE_PATTERNS}
    for node in graph.nodes:
        if node.kind not in {"function", "class", "module", "variable"}:
            continue
        for role in node.tags:
            if role in by_role:
                by_role[role].append(
                    {
                        "name": node.name,
                        "kind": node.kind,
                        "file": node.file or "",
                        "qualified_name": node.qualified_name,
                        "line": str(node.line_start or ""),
                    }
                )

    files = [
        {
            "path": r.module.file,
            "language": r.module.language,
            "classes": [c.name for c in r.module.classes],
            "functions": [f.name for f in r.module.functions],
            "imports": sorted({imp.module for imp in r.module.imports if imp.module}),
        }
        for r in parse_results
    ]

    cross_lang = sorted({r.module.language for r in parse_results})
    import_deps = _cross_file_dependencies(graph)

    methods_markdown = _methods_markdown(by_role, files, import_deps, graph)
    training_pipeline = _training_pipeline(by_role, parse_results)

    return {
        "version": 1,
        "purpose": "research_paper_methods_aid",
        "languages": cross_lang,
        "file_count": len(files),
        "files": files,
        "roles": {k: v for k, v in by_role.items() if v},
        "cross_file_dependencies": import_deps,
        "training_pipeline": training_pipeline,
        "methods_markdown": methods_markdown,
        "how_multifile_works": (
            "When you pass a folder, Codex Cartographer walks every supported "
            "source file (Python, JS/TS via AST/tree-sitter; C, C++, C#, Java, Kotlin, "
            "Swift, Go, Rust, PHP, Ruby, R, Julia and MATLAB/Octave via heuristics), "
            "builds one shared graph, links imports/includes and cross-file calls, and "
            "walks chapters file-by-file. Dependencies between modules appear as "
            "import/call edges so a MATLAB script, a C kernel and a Python trainer can "
            "sit in the same atlas."
        ),
    }


def _cross_file_dependencies(graph: CodeGraph) -> list[dict[str, str]]:
    nodes = {n.id: n for n in graph.nodes}
    deps = []
    for e in graph.edges:
        if e.kind != "import":
            continue
        src, tgt = nodes.get(e.source), nodes.get(e.target)
        if not src or not tgt:
            continue
        deps.append(
            {
                "from": src.file or src.name,
                "to": tgt.file or tgt.name,
                "kind": "external" if tgt.kind == "external" else "internal",
                "label": e.label or "",
            }
        )
    return deps[:80]


def _training_pipeline(
    by_role: dict[str, list[dict[str, str]]],
    parse_results: list[ParseResult],
) -> list[dict[str, str]]:
    """Ordered story useful for Experimental Setup paragraphs."""
    stages = [
        (ROLE_DATASET, "Data source & loading"),
        (ROLE_PREPROCESS, "Feature engineering & preprocessing"),
        (ROLE_ARCHITECTURE, "Model architecture"),
        (ROLE_LOSS, "Loss / physics-informed objective"),
        (ROLE_OPTIMIZER, "Optimizer & learning-rate schedule"),
        (ROLE_CALLBACK, "Training callbacks"),
        (ROLE_TUNING, "Hyperparameter search"),
        (ROLE_TRAINING, "Training loop"),
        (ROLE_EVAL, "Evaluation & figures"),
        (ROLE_CHECKPOINT, "Artifacts & checkpoints"),
    ]
    out = []
    for role, title in stages:
        items = by_role.get(role) or []
        if not items:
            continue
        names = ", ".join(sorted({i["name"] for i in items})[:8])
        out.append(
            {
                "stage": title,
                "role": role,
                "symbols": names,
                "paper_hint": _paper_hint(role, names),
            }
        )
    if not out:
        # Fallback generic pipeline from top-level functions
        funcs = []
        for r in parse_results:
            funcs.extend(f.name for f in r.module.functions)
            funcs.extend(c.name for c in r.module.classes)
        if funcs:
            out.append(
                {
                    "stage": "Code symbols",
                    "role": "core_logic",
                    "symbols": ", ".join(funcs[:12]),
                    "paper_hint": "Describe each symbol’s responsibility in Methods.",
                }
            )
    return out


def _paper_hint(role: str, names: str) -> str:
    hints = {
        ROLE_DATASET: f"In Methods, state the dataset path/schema and splits involving: {names}.",
        ROLE_PREPROCESS: f"Describe feature construction / scaling steps implemented by: {names}.",
        ROLE_ARCHITECTURE: f"Specify the network family and key blocks from: {names}.",
        ROLE_LOSS: f"Write the loss equation and cite the implementation symbols: {names}.",
        ROLE_OPTIMIZER: f"Report optimizer, learning rate, and schedule tied to: {names}.",
        ROLE_CALLBACK: f"Mention training stabilizers/callbacks: {names}.",
        ROLE_TUNING: f"Document search space and trial count from: {names}.",
        ROLE_TRAINING: f"Explain the train step / epoch protocol using: {names}.",
        ROLE_EVAL: f"Report metrics and qualitative plots produced by: {names}.",
        ROLE_CHECKPOINT: f"Note saved artifacts / reproducibility outputs from: {names}.",
        ROLE_METRICS: f"List quantitative metrics computed via: {names}.",
    }
    return hints.get(role, f"Relate symbols {names} to your Methods narrative.")


def _methods_markdown(
    by_role: dict[str, list[dict[str, str]]],
    files: list[dict[str, Any]],
    deps: list[dict[str, str]],
    graph: CodeGraph,
) -> str:
    lines = [
        "## Methods (auto-draft from codebase semantics)",
        "",
        "### Software & modules",
        f"The implementation spans **{len(files)}** source file(s) "
        f"({', '.join(sorted({f['language'] for f in files}))}).",
    ]
    for f in files:
        lines.append(
            f"- `{f['path']}` ({f['language']}): "
            f"classes={', '.join(f['classes']) or '—'}; "
            f"functions={', '.join(f['functions'][:10]) or '—'}"
        )

    lines += ["", "### Training system semantics"]
    order = [
        ROLE_DATASET,
        ROLE_PREPROCESS,
        ROLE_ARCHITECTURE,
        ROLE_LOSS,
        ROLE_OPTIMIZER,
        ROLE_CALLBACK,
        ROLE_TUNING,
        ROLE_TRAINING,
        ROLE_EVAL,
        ROLE_CHECKPOINT,
    ]
    titles = {
        ROLE_DATASET: "Dataset",
        ROLE_PREPROCESS: "Preprocessing",
        ROLE_ARCHITECTURE: "Model architecture",
        ROLE_LOSS: "Loss function",
        ROLE_OPTIMIZER: "Optimization",
        ROLE_CALLBACK: "Callbacks",
        ROLE_TUNING: "Hyperparameter tuning",
        ROLE_TRAINING: "Training procedure",
        ROLE_EVAL: "Evaluation",
        ROLE_CHECKPOINT: "Artifacts",
    }
    for role in order:
        items = by_role.get(role) or []
        if not items:
            continue
        names = ", ".join(f"`{i['name']}`" for i in items[:10])
        lines.append(f"**{titles[role]}.** Implemented via {names}.")

    if deps:
        lines += ["", "### Module dependencies"]
        for d in deps[:15]:
            lines.append(f"- `{d['from']}` → `{d['to']}` ({d['kind']})")

    # Highlight Sobolev / physics-informed if present
    sobolev = [n for n in graph.nodes if re.search(r"sobolev|exp_loss", n.name, re.I)]
    if sobolev:
        lines += [
            "",
            "### Physics-informed / Sobolev notes",
            "Detected symbols suggestive of gradient-augmented / Sobolev training: "
            + ", ".join(f"`{n.name}`" for n in sobolev[:8])
            + ". Use these when writing the loss and train_step paragraphs.",
        ]

    lines.append("")
    return "\n".join(lines)
