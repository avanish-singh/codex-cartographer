/*!
 * Codex Cartographer — guided, explanatory 2D/3D atlas
 *
 * Left: code + meaning.  Right: a live map that labels what the current line
 * touches, pins a callout to the active landmark, and lets you inspect any
 * node/edge (what it is, what it depends on, who uses it).
 *
 * Reads only window.GRAPH_DATA (nodes, edges, walkthrough, paper_semantics).
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- helpers
  const $ = (id) => document.getElementById(id);
  function bootError(msg) {
    const el = $("boot-error");
    el.hidden = false;
    el.textContent = msg;
  }
  function setStatus(msg) {
    const el = $("map-status");
    if (el) el.textContent = msg;
  }
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function trunc(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }
  function idOf(x) {
    return typeof x === "object" && x !== null ? x.id : x;
  }

  if (!window.GRAPH_DATA) {
    bootError("Missing GRAPH_DATA. Re-run codex-cartographer.");
    return;
  }

  // ---------------------------------------------------------------- palette
  const TAG_COLORS = {
    entry_point: "#8B3A2A",
    core_logic: "#5C4033",
    utility: "#7A6A4F",
    io_boundary: "#6B4F2A",
    external_dependency: "#4A5A4A",
    test: "#6B5B3A",
    unparsed: "#8B4513",
    ml_architecture: "#7a3030",
    ml_loss: "#8B3A2A",
    ml_training: "#6B4F2A",
    ml_hyperparameter_tuning: "#5a3a5a",
    ml_dataset: "#3f5a4a",
    ml_preprocessing: "#4f5a3a",
    ml_evaluation: "#5a4a3a",
  };
  const TAG_LABELS = {
    entry_point: "Entry point",
    core_logic: "Core logic",
    utility: "Utility / helper",
    io_boundary: "I/O boundary",
    external_dependency: "External dependency",
    test: "Test",
    unparsed: "Unparsed file",
    ml_architecture: "ML: architecture",
    ml_loss: "ML: loss",
    ml_training: "ML: training",
    ml_hyperparameter_tuning: "ML: tuning",
    ml_dataset: "ML: dataset",
    ml_preprocessing: "ML: preprocessing",
    ml_evaluation: "ML: evaluation",
    ml_optimizer: "ML: optimizer",
    ml_callback: "ML: callback",
    ml_metrics: "ML: metrics",
    ml_checkpointing: "ML: artifacts",
  };
  const LINK_COLORS = {
    contains: "#8a7048",
    import: "#5a5a3a",
    inheritance: "#b08d3e",
    call: "#8B3A2A",
    instantiation: "#a0522d",
    data_flow: "#6b5b3a",
    cluster_member: "#9a8560",
  };
  const LINK_WORDS = {
    contains: "contains",
    import: "imports",
    inheritance: "inherits from",
    instantiation: "creates an instance of",
    call: "calls",
    data_flow: "passes data to",
    cluster_member: "groups",
  };
  const FOCUS = "#c45c3a";
  const SHADED = "rgba(120,100,70,0.16)";

  // ---------------------------------------------------------------- data
  const allNodes = window.GRAPH_DATA.nodes || [];
  const allEdges = window.GRAPH_DATA.edges || [];
  const walkthrough = window.GRAPH_DATA.walkthrough || { steps: [], source_files: {}, chapters: [] };
  const paper = window.GRAPH_DATA.paper_semantics || {};
  const meta = window.GRAPH_DATA.metadata || {};
  const steps = walkthrough.steps || [];
  const sourceFiles = walkthrough.source_files || {};
  const nodeById = Object.fromEntries(allNodes.map((n) => [n.id, n]));
  const edgeById = Object.fromEntries(allEdges.map((e) => [e.id, e]));

  const STRUCTURAL = new Set(["contains", "import", "call", "inheritance", "instantiation"]);
  const outEdges = new Map();
  const inEdges = new Map();
  allEdges.forEach((e) => {
    if (e.source === e.target) return;
    if (!outEdges.has(e.source)) outEdges.set(e.source, []);
    if (!inEdges.has(e.target)) inEdges.set(e.target, []);
    outEdges.get(e.source).push(e);
    inEdges.get(e.target).push(e);
  });
  const adj = new Map();
  allEdges.forEach((e) => {
    if (!STRUCTURAL.has(e.kind) || e.source === e.target) return;
    if (!adj.has(e.source)) adj.set(e.source, new Set());
    if (!adj.has(e.target)) adj.set(e.target, new Set());
    adj.get(e.source).add(e.target);
    adj.get(e.target).add(e.source);
  });
  const moduleByFile = {};
  allNodes.forEach((n) => {
    if ((n.kind === "module" || n.kind === "unparsed") && n.file) moduleByFile[n.file] = n;
  });

  const state = {
    index: -1,
    playing: false,
    speed: 1,
    view: "3d",
    mapMode: "focus", // all | focus | grow
    labels: "smart", // smart | all | off
    follow: true,
    revealedNodes: new Set(),
    revealedEdges: new Set(),
    focusNodes: new Set(),
    focusEdges: new Set(),
    neighborhood: new Set(),
    inspected: null, // {type:'node'|'edge', id}
    legendTag: null,
    timer: null,
    dataKey: "",
  };

  // Stable per-view copies so positions persist across steps (no re-layout jitter).
  const nodes3d = allNodes.map((n) => ({ ...n }));
  const links3d = allEdges.map((e) => ({ ...e }));
  const nodes2d = allNodes.map((n) => ({ ...n }));
  const links2d = allEdges.map((e) => ({ ...e }));
  const n3dById = Object.fromEntries(nodes3d.map((n) => [n.id, n]));
  const n2dById = Object.fromEntries(nodes2d.map((n) => [n.id, n]));

  // ---------------------------------------------------------------- relations text
  function relationSummary(nodeId, limit) {
    limit = limit || 5;
    const node = nodeById[nodeId];
    if (!node) return { lines: [], text: "" };
    const lines = [];
    const groups = (edges, dir) => {
      const byKind = {};
      (edges || []).forEach((e) => {
        if (e.kind === "data_flow" || e.kind === "cluster_member") return;
        const other = nodeById[dir === "out" ? e.target : e.source];
        if (!other) return;
        (byKind[e.kind] = byKind[e.kind] || []).push(other);
      });
      return byKind;
    };
    const outs = groups(outEdges.get(nodeId), "out");
    const ins = groups(inEdges.get(nodeId), "in");
    const nameList = (arr) => {
      const uniq = [...new Map(arr.map((n) => [n.id, n])).values()];
      const shown = uniq.slice(0, limit).map((n) => n.name);
      return shown.join(", ") + (uniq.length > limit ? ` (+${uniq.length - limit} more)` : "");
    };
    if (outs.call) lines.push({ label: "calls", text: nameList(outs.call), ids: outs.call.map((n) => n.id) });
    if (outs.instantiation) lines.push({ label: "creates", text: nameList(outs.instantiation), ids: outs.instantiation.map((n) => n.id) });
    if (outs.inheritance) lines.push({ label: "inherits", text: nameList(outs.inheritance), ids: outs.inheritance.map((n) => n.id) });
    if (outs.import) lines.push({ label: "imports", text: nameList(outs.import), ids: outs.import.map((n) => n.id) });
    if (outs.contains) lines.push({ label: "contains", text: nameList(outs.contains), ids: outs.contains.map((n) => n.id) });
    if (ins.call) lines.push({ label: "called by", text: nameList(ins.call), ids: ins.call.map((n) => n.id) });
    if (ins.instantiation) lines.push({ label: "created by", text: nameList(ins.instantiation), ids: ins.instantiation.map((n) => n.id) });
    if (ins.inheritance) lines.push({ label: "extended by", text: nameList(ins.inheritance), ids: ins.inheritance.map((n) => n.id) });
    if (ins.import) lines.push({ label: "imported by", text: nameList(ins.import), ids: ins.import.map((n) => n.id) });
    if (ins.contains) lines.push({ label: "defined in", text: nameList(ins.contains), ids: ins.contains.map((n) => n.id) });
    const flows = (outEdges.get(nodeId) || []).concat(allEdges.filter((e) => e.source === nodeId && e.target === nodeId)).filter((e) => e.kind === "data_flow");
    if (flows.length) {
      lines.push({ label: "data flow", text: flows.slice(0, 4).map((e) => e.label).join(" · ") + (flows.length > 4 ? ` (+${flows.length - 4})` : ""), ids: [] });
    }
    const text = lines.map((l) => `${l.label} ${l.text}`).join("; ");
    return { lines, text };
  }

  function relationsHtml(nodeId, limit) {
    const rel = relationSummary(nodeId, limit);
    if (!rel.lines.length) return `<div class="rel-row muted">No resolved routes for this landmark.</div>`;
    return rel.lines
      .map((l) => {
        const links = l.ids.length
          ? [...new Set(l.ids)]
              .slice(0, limit || 5)
              .map((id) => `<span class="insp-link" data-inspect="${escapeHtml(id)}">${escapeHtml(nodeById[id].name)}</span>`)
              .join(", ") + (new Set(l.ids).size > (limit || 5) ? ` (+${new Set(l.ids).size - (limit || 5)} more)` : "")
          : escapeHtml(l.text);
        return `<div class="rel-row"><span class="rel-label">${escapeHtml(l.label)}</span>${links}</div>`;
      })
      .join("");
  }

  function bindInspectLinks(container) {
    container.querySelectorAll("[data-inspect]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        inspectNode(el.getAttribute("data-inspect"), true);
      });
    });
  }

  // ---------------------------------------------------------------- code panel
  const codeScroll = $("code-scroll");
  let activeFile =
    (walkthrough.chapters && walkthrough.chapters[0] && walkthrough.chapters[0].file) ||
    Object.keys(sourceFiles)[0] ||
    "";

  function renderFileTabs() {
    const tabs = $("file-tabs");
    const files = Object.keys(sourceFiles);
    if (files.length <= 1) {
      tabs.innerHTML = files.length ? `<button type="button" class="file-tab active">${escapeHtml(files[0])}</button>` : "";
      return;
    }
    if (files.length > 14) {
      // Many files: a searchable dropdown instead of hundreds of tabs.
      tabs.innerHTML =
        `<label class="toggle">File (${files.length}) ` +
        `<select id="file-select" class="file-select">${files
          .map((f) => `<option value="${escapeHtml(f)}"${f === activeFile ? " selected" : ""}>${escapeHtml(f)}</option>`)
          .join("")}</select></label>` +
        `<input id="file-filter" class="file-filter" type="search" placeholder="filter files…" />`;
      const sel = $("file-select");
      sel.addEventListener("change", () => {
        const idx = steps.findIndex((s) => s.file === sel.value);
        if (idx >= 0) goTo(idx, true);
        else renderCode(sel.value);
      });
      $("file-filter").addEventListener("input", (e) => {
        const q = e.target.value.toLowerCase();
        sel.innerHTML = files
          .filter((f) => !q || f.toLowerCase().includes(q))
          .map((f) => `<option value="${escapeHtml(f)}"${f === activeFile ? " selected" : ""}>${escapeHtml(f)}</option>`)
          .join("");
      });
      return;
    }
    tabs.innerHTML = files
      .map((f) => {
        const mod = moduleByFile[f];
        const lang = mod && mod.language ? ` <span class="insp-kind">${escapeHtml(mod.language)}</span>` : "";
        return `<button type="button" class="file-tab${f === activeFile ? " active" : ""}" data-file="${escapeHtml(f)}">${escapeHtml(f)}${lang}</button>`;
      })
      .join("");
    tabs.querySelectorAll(".file-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const file = btn.getAttribute("data-file");
        const idx = steps.findIndex((s) => s.file === file);
        if (idx >= 0) goTo(idx, true);
        else renderCode(file);
      });
    });
  }

  function renderCode(file) {
    activeFile = file || activeFile;
    const lines = sourceFiles[activeFile] || [];
    const narrated = new Set(steps.filter((s) => s.file === activeFile).map((s) => s.line));
    codeScroll.innerHTML = lines
      .map((text, i) => {
        const ln = i + 1;
        const cls = narrated.has(ln) ? "code-line" : "code-line skipped";
        return `<div class="${cls}" data-line="${ln}" id="cline-${ln}"><span class="ln">${ln}</span><span class="lt">${escapeHtml(text) || " "}</span></div>`;
      })
      .join("");
    codeScroll.querySelectorAll(".code-line").forEach((el) => {
      el.addEventListener("click", () => {
        const line = Number(el.getAttribute("data-line"));
        let idx = steps.findIndex((s) => s.file === activeFile && s.line === line);
        if (idx < 0) {
          // nearest narrated line at or before this one
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].file === activeFile && steps[i].line <= line) { idx = i; break; }
          }
        }
        if (idx >= 0) goTo(idx, true);
      });
    });
    document.querySelectorAll(".file-tab").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-file") === activeFile);
    });
    const sel = $("file-select");
    if (sel && sel.value !== activeFile) sel.value = activeFile;
  }

  function highlightCodeLine(file, line) {
    if (file && file !== activeFile) renderCode(file);
    codeScroll.querySelectorAll(".code-line.active").forEach((el) => el.classList.remove("active"));
    const el = $("cline-" + line);
    if (el) {
      el.classList.add("active", "visited");
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }

  // ---------------------------------------------------------------- neighborhood
  function expandNeighborhood(seedIds, hops) {
    const out = new Set(seedIds);
    let frontier = [...seedIds];
    for (let h = 0; h < hops; h++) {
      const next = [];
      frontier.forEach((id) => {
        const nbs = adj.get(id);
        if (!nbs) return;
        nbs.forEach((nb) => {
          if (!out.has(nb)) {
            out.add(nb);
            next.push(nb);
          }
        });
      });
      frontier = next;
    }
    [...out].forEach((id) => {
      const n = nodeById[id];
      if (n && n.parent_id) out.add(n.parent_id);
      if (n && n.file && moduleByFile[n.file]) out.add(moduleByFile[n.file].id);
    });
    return out;
  }

  function updateNeighborhood(step) {
    const seeds = (step.visual && step.visual.nodes) || [];
    state.focusNodes = new Set(seeds);
    state.focusEdges = new Set((step.visual && step.visual.edges) || []);
    state.neighborhood = expandNeighborhood(seeds, 1);
    // Edges among focus ∪ 1-hop → highlighted routes
    allEdges.forEach((e) => {
      if (!STRUCTURAL.has(e.kind)) return;
      if (state.focusNodes.has(e.source) || state.focusNodes.has(e.target)) state.focusEdges.add(e.id);
    });
    if (!state.neighborhood.size && step.file && moduleByFile[step.file]) {
      const mod = moduleByFile[step.file];
      state.neighborhood.add(mod.id);
      allNodes.forEach((n) => {
        if (n.file === step.file && (n.kind === "class" || n.kind === "function")) state.neighborhood.add(n.id);
      });
    }
  }

  // ---------------------------------------------------------------- step card
  function showStep(step, index) {
    $("step-kind").textContent = `${step.kind || "line"} · ${step.file.split("/").pop()} · line ${step.line}`;
    $("step-title").textContent = step.title || "Step";
    $("step-explain").textContent = step.explanation || "";
    $("step-code").textContent = step.code || "";
    $("step-counter").textContent = `Step ${index + 1} / ${steps.length}`;
    $("progress-bar").style.width = (steps.length ? ((index + 1) / steps.length) * 100 : 0) + "%";
    $("breadcrumb").textContent = `${step.file} · L${step.line} · ${step.title}`;
    highlightCodeLine(step.file, step.line);

    const focusIds = [...state.focusNodes].filter((id) => nodeById[id]).sort((a, b) => rank(nodeById[a]) - rank(nodeById[b]));
    const primary = focusIds.length ? nodeById[focusIds[0]] : null;
    const rel = $("step-relations");
    if (primary) {
      rel.innerHTML =
        `<div class="rel-row"><span class="rel-label">on the map</span>` +
        focusIds
          .map((id) => `<span class="insp-link" data-inspect="${escapeHtml(id)}">${escapeHtml(nodeById[id].name)}</span><span class="insp-kind">${escapeHtml(nodeById[id].kind)}</span>`)
          .join(", ") +
        `</div>` +
        relationsHtml(primary.id, 4);
      bindInspectLinks(rel);
    } else {
      rel.innerHTML = `<div class="rel-row muted">This line does not define or call a mapped symbol — the enclosing file stays highlighted.</div>`;
    }

    $("visual-action").textContent =
      state.mapMode === "focus" ? "Dependency focus" : state.mapMode === "all" ? "Full atlas + highlight" : "Map grows";
    if (primary) {
      const r = relationSummary(primary.id, 3);
      $("visual-detail").textContent = `${primary.kind} ${primary.name}` + (r.text ? ` — ${r.text}.` : " — no resolved routes yet.");
    } else {
      $("visual-detail").textContent = `Inside ${step.file}: unrelated landmarks are shaded so you can see which module this line belongs to.`;
    }
    updateCallout();
  }

  function rank(n) {
    return { function: 0, class: 1, module: 2, variable: 3, external: 4 }[n.kind] ?? 5;
  }

  // ---------------------------------------------------------------- visibility / styling
  function rebuildCumulativeUpTo(index) {
    state.revealedNodes = new Set();
    state.revealedEdges = new Set();
    for (let i = 0; i <= index; i++) {
      const v = steps[i].visual || {};
      (v.nodes || []).forEach((id) => {
        state.revealedNodes.add(id);
        const n = nodeById[id];
        if (n && n.parent_id) state.revealedNodes.add(n.parent_id);
        if (n && n.file && moduleByFile[n.file]) state.revealedNodes.add(moduleByFile[n.file].id);
      });
      (v.edges || []).forEach((id) => state.revealedEdges.add(id));
    }
    allEdges.forEach((e) => {
      if (state.revealedNodes.has(e.source) && state.revealedNodes.has(e.target) && STRUCTURAL.has(e.kind)) {
        state.revealedEdges.add(e.id);
      }
    });
  }

  const BIG_PROJECT = allNodes.filter((n) => n.kind !== "variable" && n.kind !== "cluster").length > 600;

  function visibleIds() {
    let nodes;
    if (state.mapMode === "grow") {
      nodes = allNodes.filter((n) => state.revealedNodes.has(n.id));
      if (!nodes.length) nodes = allNodes.filter((n) => n.kind === "module").slice(0, 1);
    } else if (BIG_PROJECT) {
      // Big project: skeleton (modules + classes) + everything relevant to the current line.
      const step = steps[state.index] || {};
      const keep = new Set();
      allNodes.forEach((n) => {
        if (n.kind === "module" || n.kind === "unparsed" || n.kind === "class") keep.add(n.id);
        else if (n.kind === "function" && n.file && n.file === step.file) keep.add(n.id);
      });
      state.neighborhood.forEach((id) => keep.add(id));
      state.focusNodes.forEach((id) => keep.add(id));
      if (state.inspected && state.inspected.type === "node") {
        keep.add(state.inspected.id);
        (adj.get(state.inspected.id) || []).forEach((id) => keep.add(id));
      }
      nodes = allNodes.filter((n) => keep.has(n.id) && n.kind !== "cluster" && n.kind !== "variable");
    } else {
      nodes = allNodes.filter((n) => n.kind !== "cluster");
      if (nodes.length > 180) nodes = nodes.filter((n) => n.kind !== "variable");
    }
    const ids = new Set(nodes.map((n) => n.id));
    const links = allEdges.filter((e) => {
      if (!ids.has(e.source) || !ids.has(e.target) || e.source === e.target || e.kind === "data_flow") return false;
      if (state.mapMode === "grow") return state.revealedEdges.has(e.id);
      return true;
    });
    return { ids, linkIds: new Set(links.map((l) => l.id)) };
  }

  function isHighlighted(id) {
    if (state.legendTag) {
      const n = nodeById[id];
      return !!(n && n.tags && n.tags.includes(state.legendTag));
    }
    if (state.inspected && state.inspected.type === "node") {
      return id === state.inspected.id || (adj.get(state.inspected.id) || new Set()).has(id);
    }
    return state.focusNodes.has(id) || state.neighborhood.has(id);
  }
  function isPrimary(id) {
    if (state.inspected && state.inspected.type === "node") return id === state.inspected.id;
    return state.focusNodes.has(id);
  }
  function isLinkHighlighted(l) {
    const s = idOf(l.source), t = idOf(l.target);
    if (state.inspected && state.inspected.type === "edge") return l.id === state.inspected.id;
    if (state.inspected && state.inspected.type === "node") return s === state.inspected.id || t === state.inspected.id;
    if (state.legendTag) return isHighlighted(s) && isHighlighted(t);
    return state.focusEdges.has(l.id) || (state.neighborhood.has(s) && state.neighborhood.has(t) && (state.focusNodes.has(s) || state.focusNodes.has(t)));
  }
  function baseColor(n) {
    return TAG_COLORS[(n.tags && n.tags[0]) || "core_logic"] || "#5C4033";
  }
  function nodeColor(n) {
    if (isPrimary(n.id)) return FOCUS;
    if (isHighlighted(n.id)) return baseColor(n);
    if (state.mapMode === "grow") return baseColor(n);
    return SHADED;
  }
  function nodeOpacity(n) {
    if (isPrimary(n.id) || isHighlighted(n.id)) return 0.96;
    if (state.mapMode === "focus") return 0.15;
    if (state.mapMode === "all") return 0.3;
    return 0.9;
  }
  function nodeVal(n) {
    if (isPrimary(n.id)) return 7;
    if (isHighlighted(n.id)) return 4.5;
    if (n.kind === "module") return 4;
    if (n.kind === "class") return 3.2;
    if (n.kind === "function") return 2.2;
    return 1.4;
  }
  function linkColor(l) {
    if (isLinkHighlighted(l)) return FOCUS;
    if (state.mapMode === "grow") return LINK_COLORS[l.kind] || "#6b4f2a";
    return state.mapMode === "focus" ? "rgba(107,79,42,0.10)" : "rgba(107,79,42,0.22)";
  }
  function linkWidth(l) {
    return isLinkHighlighted(l) ? 2.6 : 0.55;
  }
  function wantLabel(n) {
    if (state.labels === "off") return false;
    if (state.labels === "all") return true;
    return isPrimary(n.id) || isHighlighted(n.id) || n.kind === "module" || n.kind === "class";
  }

  // ---------------------------------------------------------------- tooltips (HTML)
  function nodeTooltip(n) {
    const src = nodeById[n.id] || n;
    const rel = relationSummary(src.id, 3).text;
    const tags = (src.tags || []).slice(0, 4).map((t) => TAG_LABELS[t] || t).join(" · ");
    return (
      `<div class="tt-title">${escapeHtml(src.name)}</div>` +
      `<div class="tt-meta">${escapeHtml(src.kind)}${src.file ? " · " + escapeHtml(src.file) : ""}${src.line_start ? " · L" + src.line_start : ""}${tags ? " · " + escapeHtml(tags) : ""}</div>` +
      `<div class="tt-body">${escapeHtml(trunc(src.explanation || "", 220))}${rel ? "<br><em>" + escapeHtml(trunc(rel, 160)) + "</em>" : ""}</div>` +
      `<div class="tt-meta">click: inspect · right-click: jump to its line</div>`
    );
  }
  function linkTooltip(l) {
    const s = nodeById[idOf(l.source)], t = nodeById[idOf(l.target)];
    const expl = (l.metadata && l.metadata.explanation) || l.kind;
    return (
      `<div class="tt-title">${escapeHtml(s ? s.name : "?")} → ${escapeHtml(t ? t.name : "?")}</div>` +
      `<div class="tt-meta">${escapeHtml(l.kind)}${l.metadata && l.metadata.line ? " · line " + l.metadata.line : ""}</div>` +
      `<div class="tt-body">${escapeHtml(s ? s.name : "?")} ${escapeHtml(LINK_WORDS[l.kind] || l.kind)} ${escapeHtml(t ? t.name : "?")}. ${escapeHtml(expl)}</div>`
    );
  }

  // ---------------------------------------------------------------- 3D
  let Graph3D = null;
  const map3d = $("map3d");
  const sprites = new Map();
  const haveSprite = typeof SpriteText !== "undefined";

  function measureStage() {
    const wrap = $("map-wrap");
    let w = wrap.clientWidth, h = wrap.clientHeight;
    if (w < 40 || h < 40) {
      w = Math.max(320, window.innerWidth - 420);
      h = Math.max(280, window.innerHeight - 220);
    }
    return { w, h };
  }

  function makeSprite(n) {
    const s = new SpriteText(trunc(n.name, 26), 2.5, baseColor(n));
    s.fontFace = "Palatino, 'Palatino Linotype', 'Book Antiqua', serif";
    s.fontWeight = "600";
    s.backgroundColor = "rgba(243,230,200,0.85)";
    s.padding = 0.6;
    s.borderRadius = 1;
    s.strokeWidth = 0;
    s.material.depthWrite = false;
    s.position.y = Math.cbrt(nodeVal(n)) * 4 + 3.5;
    return s;
  }

  function styleSprite(n) {
    const s = sprites.get(n.id);
    if (!s) return;
    const show = wantLabel(n);
    s.visible = show;
    if (!show) return;
    const primary = isPrimary(n.id);
    s.color = primary ? "#f3e6c8" : isHighlighted(n.id) ? baseColor(n) : "rgba(74,50,32,0.55)";
    s.backgroundColor = primary ? FOCUS : "rgba(243,230,200,0.85)";
    s.textHeight = primary ? 3.4 : isHighlighted(n.id) ? 2.5 : 1.9;
    s.position.y = Math.cbrt(nodeVal(n)) * 4 + 3;
  }

  function init3D() {
    if (typeof ForceGraph3D === "undefined") {
      setStatus("3D library did not load — switch to 2D");
      bootError("The 3D library (CDN) failed to load. Check internet access or use the 2D view.");
      return;
    }
    const { w, h } = measureStage();
    try {
      Graph3D = ForceGraph3D()(map3d)
        .width(w)
        .height(h)
        .backgroundColor("#e8d4a8")
        .showNavInfo(false)
        .nodeId("id")
        .nodeRelSize(4)
        .nodeLabel(nodeTooltip)
        .nodeVal(nodeVal)
        .nodeColor(nodeColor)
        .nodeOpacity(0.92)
        .linkLabel(linkTooltip)
        .linkColor(linkColor)
        .linkWidth(linkWidth)
        .linkOpacity(0.75)
        .linkDirectionalParticles((l) => (isLinkHighlighted(l) ? 3 : 0))
        .linkDirectionalParticleWidth(1.8)
        .linkDirectionalParticleSpeed(0.006)
        .linkDirectionalArrowLength(2.2)
        .linkDirectionalArrowRelPos(1)
        .onNodeClick((node) => {
          if (!node) return;
          inspectNode(node.id, true);
        })
        .onNodeRightClick((node) => {
          if (!node) return;
          jumpToNode(node.id);
        })
        .onLinkClick((link) => {
          if (link) inspectEdge(link.id);
        })
        .onBackgroundClick(() => clearInspect())
        .onEngineTick(() => updateCallout());

      if (haveSprite) {
        Graph3D.nodeThreeObjectExtend(true).nodeThreeObject((n) => {
          let s = sprites.get(n.id);
          if (!s) {
            s = makeSprite(n);
            sprites.set(n.id, s);
          }
          styleSprite(n);
          return s;
        });
      }
      try {
        const scene = Graph3D.scene();
        if (window.THREE) scene.fog = new THREE.FogExp2(0xe8d4a8, 0.0022);
      } catch (_) {}

      const canvas = map3d.querySelector("canvas");
      if (canvas) {
        canvas.style.width = "100%";
        canvas.style.height = "100%";
        canvas.style.display = "block";
      }
      setStatus("3D ready" + (haveSprite ? "" : " (labels unavailable)"));
    } catch (err) {
      setStatus("3D error");
      bootError("3D init failed: " + err.message);
    }
  }

  function size3D() {
    if (!Graph3D) return;
    const { w, h } = measureStage();
    Graph3D.width(w).height(h);
  }

  function dataKey() {
    const v = visibleIds();
    // Cheap fingerprint: sizes + a few ids, enough to detect set changes without hashing everything.
    const sample = [...v.ids].filter((_, i) => i % 97 === 0).join(",");
    return `${state.mapMode}|${v.ids.size}|${v.linkIds.size}|${sample}`;
  }

  function refresh3D(resetCam) {
    if (!Graph3D) return;
    size3D();
    const key = dataKey();
    if (key !== state.dataKey || resetCam === "force") {
      const v = visibleIds();
      Graph3D.graphData({
        nodes: nodes3d.filter((n) => v.ids.has(n.id)),
        links: links3d.filter((l) => v.linkIds.has(l.id)),
      });
      state.dataKey = key;
    }
    Graph3D.nodeColor(nodeColor)
      .nodeVal(nodeVal)
      .linkColor(linkColor)
      .linkWidth(linkWidth)
      .linkDirectionalParticles((l) => (isLinkHighlighted(l) ? 3 : 0));
    if (haveSprite) nodes3d.forEach(styleSprite);

    if (resetCam === true || resetCam === "force") {
      Graph3D.cameraPosition({ x: 0, y: 60, z: 340 }, { x: 0, y: 0, z: 0 }, 500);
    } else if (state.follow) {
      flyToFocus();
    }
    const v = visibleIds();
    setStatus(`3D · ${v.ids.size}${BIG_PROJECT ? " of " + allNodes.length : ""} landmarks · ${v.linkIds.size} routes · ${state.mapMode}${BIG_PROJECT ? " · big project: skeleton + current neighbourhood" : ""}`);
  }

  function primaryFocusId() {
    if (state.inspected && state.inspected.type === "node") return state.inspected.id;
    const focus = [...state.focusNodes].filter((id) => nodeById[id]).sort((a, b) => rank(nodeById[a]) - rank(nodeById[b]));
    return focus[0] || [...state.neighborhood][0] || null;
  }

  function flyToFocus() {
    if (!Graph3D) return;
    const id = primaryFocusId();
    const node = id && n3dById[id];
    if (!node || node.x == null) return;
    const cam = Graph3D.cameraPosition();
    const dx = cam.x - node.x, dy = cam.y - node.y, dz = cam.z - node.z;
    const len = Math.hypot(dx, dy, dz) || 1;
    // Frame the whole 1-hop neighbourhood: farther when more landmarks are lit.
    const dist = 150 + Math.min(120, state.neighborhood.size * 6);
    Graph3D.cameraPosition(
      { x: node.x + (dx / len) * dist, y: node.y + (dy / len) * dist + 20, z: node.z + (dz / len) * dist },
      { x: node.x, y: node.y, z: node.z },
      650
    );
  }

  // ---------------------------------------------------------------- callout pinned to active node
  function updateCallout() {
    const el = $("callout");
    const id = primaryFocusId();
    if (!id || !nodeById[id]) {
      el.classList.add("is-hidden");
      return;
    }
    let pos = null;
    if (state.view === "3d" && Graph3D) {
      const n = n3dById[id];
      if (n && n.x != null) {
        try {
          pos = Graph3D.graph2ScreenCoords(n.x, n.y, n.z);
        } catch (_) { pos = null; }
      }
    } else {
      const n = n2dById[id];
      if (n && n.x != null && zoom2dTransform) {
        pos = { x: zoom2dTransform.applyX(n.x), y: zoom2dTransform.applyY(n.y) };
      }
    }
    const wrap = $("map-wrap");
    if (!pos || pos.x < -50 || pos.y < -50 || pos.x > wrap.clientWidth + 50 || pos.y > wrap.clientHeight + 50) {
      el.classList.add("is-hidden");
      return;
    }
    const node = nodeById[id];
    const step = steps[state.index];
    $("callout-title").textContent = `${node.name}`;
    let body;
    if (state.inspected && state.inspected.type === "node") {
      body = `${node.kind}${node.file ? " in " + node.file.split("/").pop() : ""}. ${trunc(relationSummary(id, 3).text || node.explanation || "", 140)}`;
    } else if (step) {
      const why = relationSummary(id, 2).text;
      body = `${step.title}${why ? " — " + trunc(why, 120) : ""}`;
    } else {
      body = node.kind;
    }
    $("callout-body").textContent = body;
    el.style.left = pos.x + "px";
    el.style.top = pos.y + "px";
    el.classList.remove("is-hidden");
  }

  // ---------------------------------------------------------------- 2D (D3)
  const svg2d = d3.select("#map2d");
  const g2d = svg2d.append("g").attr("class", "viewport");
  const gLinks = g2d.append("g").attr("class", "links");
  const gNodes = g2d.append("g").attr("class", "nodes");
  let sim2d = null;
  let zoom2dTransform = d3.zoomIdentity;
  let link2dSel = null, node2dSel = null;
  let data2dKey = "";
  const zoom2d = d3.zoom().scaleExtent([0.15, 5]).on("zoom", (ev) => {
    zoom2dTransform = ev.transform;
    g2d.attr("transform", ev.transform);
    updateCallout();
  });
  svg2d.call(zoom2d).on("click", () => clearInspect());

  function refresh2D(resetCam) {
    const { w, h } = measureStage();
    svg2d.attr("width", w).attr("height", h);
    const v = visibleIds();
    const key = dataKey();
    const nodes = nodes2d.filter((n) => v.ids.has(n.id));
    const links = links2d.filter((l) => v.linkIds.has(l.id));

    if (key !== data2dKey || !sim2d) {
      data2dKey = key;
      if (sim2d) sim2d.stop();
      sim2d = d3
        .forceSimulation(nodes)
        .force("link", d3.forceLink(links).id((d) => d.id).distance(70).strength(0.4))
        .force("charge", d3.forceManyBody().strength(-170))
        .force("center", d3.forceCenter(w / 2, h / 2))
        .force("collide", d3.forceCollide(16))
        .alpha(0.9);

      link2dSel = gLinks
        .selectAll("line")
        .data(links, (d) => d.id)
        .join("line")
        .on("click", (ev, d) => { ev.stopPropagation(); inspectEdge(d.id); })
        .on("mouseenter", (ev, d) => showTip(ev, linkTooltip(d)))
        .on("mousemove", moveTip)
        .on("mouseleave", hideTip);

      node2dSel = gNodes
        .selectAll("g")
        .data(nodes, (d) => d.id)
        .join((enter) => {
          const g = enter.append("g");
          g.append("circle");
          g.append("text").attr("dy", 16);
          return g;
        })
        .call(
          d3.drag()
            .on("start", (ev, d) => { if (!ev.active) sim2d.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
            .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
            .on("end", (ev, d) => { if (!ev.active) sim2d.alphaTarget(0); d.fx = null; d.fy = null; })
        )
        .on("click", (ev, d) => { ev.stopPropagation(); inspectNode(d.id, true); })
        .on("contextmenu", (ev, d) => { ev.preventDefault(); jumpToNode(d.id); })
        .on("mouseenter", (ev, d) => showTip(ev, nodeTooltip(d)))
        .on("mousemove", moveTip)
        .on("mouseleave", hideTip);

      sim2d.on("tick", () => {
        link2dSel
          .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
        node2dSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
        updateCallout();
      });
      sim2d.on("end", centerOn2D);
    }

    link2dSel
      .attr("class", (d) => "link2d" + (isLinkHighlighted(d) ? " active" : " shaded"))
      .attr("stroke", (d) => linkColor(d))
      .attr("stroke-width", (d) => (isLinkHighlighted(d) ? 2.4 : 1));
    node2dSel.attr("class", (d) => "node2d" + (isHighlighted(d.id) ? " active" : " shaded"));
    node2dSel.select("circle")
      .attr("r", (d) => (isPrimary(d.id) ? 13 : isHighlighted(d.id) ? 9 : 6))
      .attr("fill", (d) => nodeColor(d))
      .attr("opacity", (d) => nodeOpacity(d));
    node2dSel.select("text")
      .attr("class", (d) => (wantLabel(d) ? "" : "lbl-hidden"))
      .text((d) => trunc(d.name, 18))
      .attr("opacity", (d) => (isHighlighted(d.id) ? 1 : 0.35));

    if (resetCam) {
      svg2d.transition().duration(400).call(zoom2d.transform, d3.zoomIdentity);
      // Layout is still settling right after a data change: centre once it calms down.
      clearTimeout(center2dTimer);
      center2dTimer = setTimeout(centerOn2D, 900);
    } else if (state.follow) centerOn2D();
    setStatus(`2D · ${nodes.length}${BIG_PROJECT ? " of " + allNodes.length : ""} landmarks · ${links.length} routes · ${state.mapMode}`);
  }

  let center2dTimer = null;
  function centerOn2D() {
    if (state.view !== "2d" || !state.follow) return;
    const { w, h } = measureStage();
    const id = primaryFocusId();
    const n = id && n2dById[id];
    if (!n || n.x == null) return;
    const k = Math.max(zoom2dTransform.k, 1.15);
    const t = d3.zoomIdentity.translate(w / 2 - n.x * k, h / 2 - n.y * k).scale(k);
    svg2d.transition().duration(500).call(zoom2d.transform, t);
  }

  // simple tooltip for 2D
  const tip = $("tooltip");
  function showTip(ev, html) { tip.innerHTML = html; tip.style.display = "block"; moveTip(ev); }
  function moveTip(ev) { tip.style.left = ev.clientX + 14 + "px"; tip.style.top = ev.clientY + 14 + "px"; }
  function hideTip() { tip.style.display = "none"; }

  function refreshGraphs(resetCam) {
    if (state.view === "3d") refresh3D(resetCam);
    else refresh2D(resetCam);
    updateCallout();
  }

  function setView(view) {
    state.view = view;
    $("map3d").classList.toggle("is-hidden", view !== "3d");
    $("map2d").classList.toggle("is-hidden", view !== "2d");
    document.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("active", b.getAttribute("data-view") === view));
    $("hint").textContent = view === "3d"
      ? "Drag = orbit · Scroll = zoom · Click node = inspect · Right-click node = jump to its line · Click edge = explain route"
      : "Drag background = pan · Scroll = zoom · Drag node = move · Click node = inspect · Right-click = jump to line";
    requestAnimationFrame(() => {
      if (view === "3d") {
        if (!Graph3D) init3D();
        state.dataKey = "";
        refresh3D("force");
      } else refresh2D(true);
    });
  }

  function setMapMode(mode) {
    state.mapMode = mode;
    document.querySelectorAll("[data-map-mode]").forEach((b) => b.classList.toggle("active", b.getAttribute("data-map-mode") === mode));
    if (state.index >= 0) goTo(state.index, true);
    else refreshGraphs(true);
  }

  // ---------------------------------------------------------------- inspector
  function inspectNode(id, fly) {
    const node = nodeById[id];
    if (!node) return;
    state.inspected = { type: "node", id };
    state.legendTag = null;
    renderLegend();
    $("inspector").classList.remove("is-collapsed");
    $("inspector-title").textContent = `${node.kind}: ${node.name}`;
    const tags = (node.tags || []).map((t) => `<span class="tag" title="${escapeHtml(t)}">${escapeHtml(TAG_LABELS[t] || t)}</span>`).join("");
    const rel = relationSummary(id, 8);
    const dependsOn = rel.lines.filter((l) => ["calls", "creates", "inherits", "imports", "contains"].includes(l.label));
    const usedBy = rel.lines.filter((l) => ["called by", "created by", "extended by", "imported by", "defined in"].includes(l.label));
    const listHtml = (lines) =>
      lines.length
        ? `<ul>${lines
            .map((l) => `<li><span class="rel-label">${escapeHtml(l.label)}</span>${[...new Set(l.ids)]
              .slice(0, 8)
              .map((nid) => `<span class="insp-link" data-inspect="${escapeHtml(nid)}">${escapeHtml(nodeById[nid].name)}</span><span class="insp-kind">${escapeHtml(nodeById[nid].kind)}</span>`)
              .join(", ")}${new Set(l.ids).size > 8 ? ` (+${new Set(l.ids).size - 8})` : ""}</li>`)
            .join("")}</ul>`
        : `<p class="muted">none resolved</p>`;
    const flows = allEdges.filter((e) => e.kind === "data_flow" && e.source === id);
    const flowsHtml = flows.length
      ? `<h5>Local data flow</h5><ul>${flows.slice(0, 8).map((e) => `<li>${escapeHtml(e.label)}</li>`).join("")}</ul>`
      : "";
    const stepIdx = stepIndexForNode(id);
    $("inspector-body").innerHTML =
      `<p class="insp-meta">${escapeHtml(node.file || "(external)")}${node.line_start ? ` · lines ${node.line_start}–${node.line_end || node.line_start}` : ""}${node.language ? " · " + escapeHtml(node.language) : ""}${stepIdx >= 0 ? ` · walkthrough step ${stepIdx + 1}` : ""}</p>` +
      `<div>${tags}</div>` +
      `<p class="insp-explain">${escapeHtml(node.explanation || "")}</p>` +
      `<div class="insp-cols"><div><h5>Depends on</h5>${listHtml(dependsOn)}</div><div><h5>Used by</h5>${listHtml(usedBy)}</div></div>` +
      flowsHtml +
      (node.snippet ? `<h5 style="margin:0.4rem 0 0;font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:var(--rust)">Source excerpt</h5><pre class="insp-snippet">${escapeHtml(node.snippet)}</pre>` : "");
    bindInspectLinks($("inspector-body"));
    $("btn-inspect-goto").disabled = stepIdx < 0;
    refreshGraphs(false);
    if (fly && state.view === "3d") flyToFocus();
    updateCallout();
  }

  function inspectEdge(id) {
    const e = edgeById[id] || links3d.find((l) => l.id === id);
    if (!e) return;
    const s = nodeById[idOf(e.source)], t = nodeById[idOf(e.target)];
    state.inspected = { type: "edge", id };
    $("inspector").classList.remove("is-collapsed");
    $("inspector-title").textContent = `route: ${s ? s.name : "?"} → ${t ? t.name : "?"}`;
    const expl = (e.metadata && e.metadata.explanation) || e.kind;
    $("inspector-body").innerHTML =
      `<p class="insp-meta">${escapeHtml(e.kind)}${e.metadata && e.metadata.line ? " · line " + e.metadata.line : ""}${e.metadata && e.metadata.script_level ? " · script-level" : ""}</p>` +
      `<p class="insp-explain"><span class="insp-link" data-inspect="${escapeHtml(idOf(e.source))}">${escapeHtml(s ? s.name : "?")}</span> <strong>${escapeHtml(LINK_WORDS[e.kind] || e.kind)}</strong> <span class="insp-link" data-inspect="${escapeHtml(idOf(e.target))}">${escapeHtml(t ? t.name : "?")}</span>. ${escapeHtml(expl)}</p>` +
      (s && t && s.file && t.file && s.file !== t.file ? `<p class="insp-meta">Cross-file route: ${escapeHtml(s.file)} → ${escapeHtml(t.file)}</p>` : "");
    bindInspectLinks($("inspector-body"));
    $("btn-inspect-goto").disabled = true;
    refreshGraphs(false);
    updateCallout();
  }

  function clearInspect() {
    if (!state.inspected && !state.legendTag) return;
    state.inspected = null;
    state.legendTag = null;
    renderLegend();
    refreshGraphs(false);
    updateCallout();
  }

  function stepIndexForNode(id) {
    const n = nodeById[id];
    let idx = steps.findIndex((s) => s.kind !== "chapter" && s.visual && (s.visual.nodes || [])[0] === id);
    if (idx < 0) idx = steps.findIndex((s) => s.kind !== "chapter" && s.visual && (s.visual.nodes || []).includes(id));
    if (idx < 0 && n && n.file && n.line_start) idx = steps.findIndex((s) => s.file === n.file && s.line === n.line_start);
    if (idx < 0 && n && n.file) idx = steps.findIndex((s) => s.file === n.file);
    return idx;
  }

  function jumpToNode(id) {
    const idx = stepIndexForNode(id);
    if (idx >= 0) {
      state.inspected = null;
      goTo(idx, true);
    }
  }

  // ---------------------------------------------------------------- legend
  function renderLegend() {
    const tagCounts = {};
    allNodes.forEach((n) => (n.tags || []).forEach((t) => (tagCounts[t] = (tagCounts[t] || 0) + 1)));
    $("legend-tags").innerHTML = Object.keys(tagCounts)
      .sort((a, b) => tagCounts[b] - tagCounts[a])
      .map((t) => `<div class="legend-row${state.legendTag === t ? " active" : ""}" data-tag="${escapeHtml(t)}"><span class="legend-swatch" style="background:${TAG_COLORS[t] || "#5C4033"}"></span>${escapeHtml(TAG_LABELS[t] || t)}<span class="legend-count">${tagCounts[t]}</span></div>`)
      .join("");
    const edgeCounts = {};
    allEdges.forEach((e) => (edgeCounts[e.kind] = (edgeCounts[e.kind] || 0) + 1));
    $("legend-edges").innerHTML = Object.keys(edgeCounts)
      .map((k) => `<div class="legend-row"><span class="legend-line" style="border-color:${LINK_COLORS[k] || "#6b4f2a"}"></span>${escapeHtml(k)} <span class="insp-kind">(${escapeHtml(LINK_WORDS[k] || "")})</span><span class="legend-count">${edgeCounts[k]}</span></div>`)
      .join("");
    $("legend-tags").querySelectorAll("[data-tag]").forEach((row) => {
      row.addEventListener("click", () => {
        const t = row.getAttribute("data-tag");
        state.legendTag = state.legendTag === t ? null : t;
        state.inspected = null;
        renderLegend();
        refreshGraphs(false);
        $("visual-action").textContent = state.legendTag ? "Tag highlight" : "Dependency focus";
        $("visual-detail").textContent = state.legendTag ? `Every landmark tagged “${TAG_LABELS[t] || t}” is lit; others are shaded.` : "";
      });
    });
  }

  // ---------------------------------------------------------------- transport
  function goTo(index, pause) {
    if (!steps.length) return;
    index = Math.max(0, Math.min(steps.length - 1, index));
    state.index = index;
    if (pause) pausePlayback();
    state.inspected = null;
    state.legendTag = null;
    rebuildCumulativeUpTo(index);
    const step = steps[index];
    updateNeighborhood(step);
    showStep(step, index);
    refreshGraphs(false);
    if (index === steps.length - 1) {
      $("visual-action").textContent = "Journey complete";
      $("visual-detail").textContent = "Open “Paper summary” for a Methods-ready description of the training pipeline, or click any landmark to inspect it.";
    }
  }
  function next() { if (state.index >= steps.length - 1) { pausePlayback(); return; } goTo(state.index + 1, false); }
  function prev() { goTo(Math.max(0, state.index - 1), true); }
  function nextDefinition() {
    for (let i = state.index + 1; i < steps.length; i++) {
      if (["ClassDef", "FunctionDef", "AsyncFunctionDef", "definition", "chapter"].includes(steps[i].kind)) { goTo(i, true); return; }
    }
  }
  function playIntervalMs() {
    const step = steps[state.index];
    let base = 1500 / state.speed;
    if (step && ["ClassDef", "FunctionDef", "AsyncFunctionDef", "Import", "ImportFrom", "definition", "chapter"].includes(step.kind)) base *= 1.35;
    return base;
  }
  function tickPlay() {
    next();
    if (state.playing && state.index < steps.length - 1) state.timer = setTimeout(tickPlay, playIntervalMs());
    else pausePlayback();
  }
  function startPlayback() {
    state.playing = true;
    $("btn-play").textContent = "⏸ Pause";
    $("btn-play").classList.add("playing");
    if (state.index < 0) goTo(0, false);
    clearTimeout(state.timer);
    state.timer = setTimeout(tickPlay, playIntervalMs());
  }
  function pausePlayback() {
    state.playing = false;
    clearTimeout(state.timer);
    state.timer = null;
    $("btn-play").textContent = "▶ Play";
    $("btn-play").classList.remove("playing");
  }
  function togglePlay() { state.playing ? pausePlayback() : startPlayback(); }

  // ---------------------------------------------------------------- paper summary
  function openPaper() {
    $("paper-lead").textContent = paper.how_multifile_works || "Folder maps merge every supported language into one dependency atlas.";
    const pipeline = (paper.training_pipeline || []).map((s) => `• ${s.stage}: ${s.symbols}\n  → ${s.paper_hint}`).join("\n\n");
    const files = (paper.files || []).map((f) => `- ${f.path} (${f.language}) classes: ${f.classes.join(", ") || "—"}; functions: ${f.functions.slice(0, 12).join(", ") || "—"}`).join("\n");
    $("paper-body").textContent =
      (paper.methods_markdown || "(No paper semantics yet — re-run cartographer.)") +
      (pipeline ? "\n\n### Training pipeline checklist\n\n" + pipeline : "") +
      (files ? "\n\n### Files scanned\n" + files : "");
    $("paper-modal").hidden = false;
  }

  // ---------------------------------------------------------------- wiring
  $("btn-play").addEventListener("click", togglePlay);
  $("btn-next").addEventListener("click", () => { pausePlayback(); next(); });
  $("btn-prev").addEventListener("click", prev);
  $("btn-restart").addEventListener("click", () => { pausePlayback(); goTo(0, true); refreshGraphs(true); });
  $("btn-skip-def").addEventListener("click", nextDefinition);
  $("btn-paper").addEventListener("click", openPaper);
  $("btn-paper-close").addEventListener("click", () => { $("paper-modal").hidden = true; });
  $("btn-legend").addEventListener("click", () => $("legend").classList.toggle("is-hidden"));
  $("chk-follow").addEventListener("change", (e) => { state.follow = e.target.checked; });
  $("btn-inspect-toggle").addEventListener("click", () => {
    const insp = $("inspector");
    insp.classList.toggle("is-collapsed");
    $("btn-inspect-toggle").textContent = insp.classList.contains("is-collapsed") ? "▴" : "▾";
    requestAnimationFrame(() => refreshGraphs(false));
  });
  $("btn-inspect-goto").addEventListener("click", () => { if (state.inspected && state.inspected.type === "node") jumpToNode(state.inspected.id); });
  $("btn-inspect-focus").addEventListener("click", () => {
    if (!state.inspected || state.inspected.type !== "node") return;
    const id = state.inspected.id;
    state.focusNodes = new Set([id]);
    state.neighborhood = expandNeighborhood([id], 1);
    state.focusEdges = new Set(allEdges.filter((e) => STRUCTURAL.has(e.kind) && (e.source === id || e.target === id)).map((e) => e.id));
    state.inspected = null;
    refreshGraphs(false);
    $("visual-action").textContent = "Dependency focus";
    $("visual-detail").textContent = `${nodeById[id].kind} ${nodeById[id].name} — ${relationSummary(id, 4).text || "no resolved routes"}.`;
    updateCallout();
  });

  document.querySelectorAll("[data-view]").forEach((btn) => btn.addEventListener("click", () => setView(btn.getAttribute("data-view"))));
  document.querySelectorAll("[data-map-mode]").forEach((btn) => btn.addEventListener("click", () => setMapMode(btn.getAttribute("data-map-mode"))));
  document.querySelectorAll("[data-labels]").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.labels = btn.getAttribute("data-labels");
      document.querySelectorAll("[data-labels]").forEach((b) => b.classList.toggle("active", b === btn));
      refreshGraphs(false);
    })
  );
  document.querySelectorAll("[data-speed]").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.speed = Number(btn.getAttribute("data-speed")) || 1;
      document.querySelectorAll("[data-speed]").forEach((b) => b.classList.remove("active-speed"));
      btn.classList.add("active-speed");
      if (state.playing) { clearTimeout(state.timer); state.timer = setTimeout(tickPlay, playIntervalMs()); }
    })
  );

  window.addEventListener("resize", () => refreshGraphs(false));
  window.addEventListener("keydown", (e) => {
    if (e.target && ["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    else if (e.code === "ArrowRight") { pausePlayback(); next(); }
    else if (e.code === "ArrowLeft") prev();
    else if (e.code === "Escape") clearInspect();
    else if (e.key === "d" || e.key === "D") nextDefinition();
  });

  // continuous callout tracking while the camera moves (3D orbit has no engine tick)
  (function loop() { if (state.view === "3d") updateCallout(); requestAnimationFrame(loop); })();

  // ---------------------------------------------------------------- boot
  $("map-title").textContent = "Codex Cartographer — " + (meta.source_path || "walkthrough").split("/").slice(-2).join("/");
  const langs = (meta.languages || []).join(", ");
  $("map-subtitle").textContent =
    `${meta.files_parsed || Object.keys(sourceFiles).length} file(s) · ${langs || "—"} · ${allNodes.length} landmarks · ${allEdges.length} routes` +
    (walkthrough.condensed ? ` · walkthrough condensed to ${steps.length} key steps` : "");

  if (!steps.length) {
    bootError("No walkthrough steps were generated for this path.");
    return;
  }

  renderFileTabs();
  renderCode(activeFile);
  renderLegend();
  document.querySelectorAll("[data-map-mode]").forEach((b) => b.classList.toggle("active", b.getAttribute("data-map-mode") === state.mapMode));

  // Wait two frames so the CSS grid gives #map-wrap a real size (fixes blank 3D canvas).
  requestAnimationFrame(() => requestAnimationFrame(() => {
    init3D();
    setView("3d");
    goTo(0, true);
    setTimeout(() => refresh3D(true), 400);
  }));
})();
