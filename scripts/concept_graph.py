"""Generic concept-graph toolkit — a CLI that inspects, visualizes, shares,
and composes *any* domain-specific concept graph, without that graph's
module needing to import or know about this one.

A "domain module" is any importable Python module (or ``.py`` file) that
exposes::

    build() -> networkx.DiGraph

whose nodes carry at least:
    kind        : "primitive" | "concept" | "application"
    tier        : int (0 = primitive floor; higher = more composed)
    defines     : str (one-line definition)
    composed_of : list[str] (direct prerequisites; empty for primitives)

and whose edges u → v mean "u is a prerequisite of v".  ``linalg_graph.py``
(cookbook/71_linalg_concept_book) and ``geometry_graph.py``
(cookbook/73_intro_geometry) are worked examples — each is fully
self-contained (by design: see cookbook/70's readme on why domain libraries
duplicate their graph algorithms rather than share an implementation that
two domains' notions of e.g. "ancestors" could silently diverge from). This
module is the deliberate exception: a *reporting and sharing* layer that
every domain module gets "mixed in" for free, purely by exposing build() —
no import, no coupling, no per-domain CLI to write or maintain.

CLI usage
---------
    python concept_graph.py --domain linalg_graph stats
    python concept_graph.py --domain linalg_graph show spectral_theorem
    python concept_graph.py --domain linalg_graph visualize --format mermaid
    python concept_graph.py --domain linalg_graph export domain.json -t pca
    python concept_graph.py --domain linalg_graph import domain.json
    python concept_graph.py compose -d linalg_graph -d geometry_graph hybrid.json
    python concept_graph.py --domain hybrid.json stats

``--domain`` accepts an importable module name (resolved on ``sys.path`` /
the current directory), a path to a ``.py`` file, or a path to a ``.json``
graph previously written by ``export``/``compose`` — so any concept graph,
wherever it lives and however it was produced, flows through the same CLI.

Authoring a concept graph that spans multiple fields by hand is exactly the
kind of task no single publisher takes on; ``compose`` is the framework's
first mechanical step toward making that tractable — see its docstring.
"""

from __future__ import annotations

import heapq
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Iterable

import click
import networkx as nx

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Generic graph algorithms — pure functions of (graph [, params]); no
# knowledge of any particular domain's concepts.
# ---------------------------------------------------------------------------

def acyclic(graph: nx.DiGraph) -> bool:
    """Return True if the graph has no cycles (valid composition hierarchy)."""
    return nx.is_directed_acyclic_graph(graph)


def reducible(graph: nx.DiGraph, primitives: Iterable[str], strict: bool = False) -> bool:
    """Return True if every concept/application reduces transitively to primitives.

    Default (lenient): a node is reducible iff every "leaf" (in-degree 0
    node) in its ancestor closure is *declared* — a primitive, or a concept
    given its own entry (defines/tier) even without further decomposition.
    Only a leaf with no declaration anywhere (a dangling/misspelled
    reference, never given its own entry) still fails.

    `strict=True` reverts to the tighter rule: every leaf must be in
    *primitives* by name. Used by `stats --strict` to surface which
    concepts are quietly relying on the lenient rule. See
    spl/graph_lib.py:reducible for the full rationale (twin of this
    function).
    """
    prim_set = set(primitives)
    for node in graph.nodes():
        if graph.nodes[node].get("kind") == "primitive":
            continue
        anc = nx.ancestors(graph, node)
        sources = {n for n in anc if graph.in_degree(n) == 0}
        if strict:
            if not sources.issubset(prim_set):
                return False
        else:
            undeclared = {n for n in sources if graph.nodes[n].get("kind") is None}
            if undeclared:
                return False
    return True


def minimal(graph: nx.DiGraph, primitives: Iterable[str]) -> bool:
    """Return True if every supplied name is a node declared `kind="primitive"`.

    A minimal basis uses only the graph's own irreducible radicals — no
    concept is claimed to be primitive if the graph composes it from others.
    """
    declared = {n for n, d in graph.nodes(data=True) if d.get("kind") == "primitive"}
    return set(primitives).issubset(declared)


def in_graph(graph: nx.DiGraph, target: str) -> bool:
    """Return True if target names a node in the graph."""
    return target in graph.nodes()


def ancestors(graph: nx.DiGraph, target: str) -> set[str]:
    """Return the composed-of closure — all nodes that transitively feed target."""
    return nx.ancestors(graph, target)


def restrict(graph: nx.DiGraph, needed: Iterable[str]) -> nx.DiGraph:
    """Return the subgraph induced by the given node set.

    Only nodes in *needed* are kept; edges between them are preserved.
    """
    return graph.subgraph(set(needed)).copy()


def applications_of(graph: nx.DiGraph, target: str) -> list[str]:
    """Return application nodes that directly depend on target."""
    return [
        n for n in graph.successors(target)
        if graph.nodes[n].get("kind") == "application"
    ]


def gap(graph: nx.DiGraph, target: str, learner_state: Iterable[str]) -> set[str]:
    """Concepts needed to reach target that the learner has not yet mastered.

    Returns ancestors(graph, target) minus learner_state.
    """
    return ancestors(graph, target).difference(set(learner_state))


def learning_path(graph: nx.DiGraph, target: str, learner_state: Iterable[str],
                  weight: float = 1.0) -> list[str]:
    """Productivity-ordered list of concepts a learner still needs for target.

    Equivalent to productivity_order(restrict(graph, gap(graph, target, learner_state))).
    Handles the empty-gap case (all prerequisites already mastered) gracefully.
    """
    needed = gap(graph, target, learner_state)
    if not needed:
        return []
    return productivity_order(restrict(graph, needed), weight=weight)


def productivity_order(graph: nx.DiGraph, weight: float = 1.0) -> list[str]:
    """Return nodes in order: topological, tie-broken by payoff-weighted reach.

    reach(c) = (# concepts c is ancestor of) + weight * (# applications c is ancestor of)

    A node with high reach "unlocks" many downstream concepts and
    applications when learned — it should be taught as early as topology
    allows.

    Implementation: modified Kahn's algorithm with a max-heap priority queue.
    Primitives (in-degree 0) are always first; within each topological tier,
    nodes with higher reach are preferred.  Passes the topological ordering
    invariant: if u→v in graph, u appears before v in the returned list.
    """
    reach: dict[str, float] = {}
    for node in graph.nodes():
        desc = nx.descendants(graph, node)
        n_concepts = sum(1 for d in desc if graph.nodes[d].get("kind") == "concept")
        n_apps = sum(1 for d in desc if graph.nodes[d].get("kind") == "application")
        reach[node] = n_concepts + weight * n_apps

    in_deg: dict[str, int] = dict(graph.in_degree())
    heap: list[tuple[float, str]] = []
    for n, d in in_deg.items():
        if d == 0:
            heapq.heappush(heap, (-reach[n], n))  # stable: break ties by name

    result: list[str] = []
    while heap:
        _, node = heapq.heappop(heap)
        result.append(node)
        for succ in graph.successors(node):
            in_deg[succ] -= 1
            if in_deg[succ] == 0:
                heapq.heappush(heap, (-reach[succ], succ))

    return result


# ---------------------------------------------------------------------------
# Visualization renderers — text formats that need no plotting dependencies
# ---------------------------------------------------------------------------

_KIND_STYLE = {
    "primitive": "fill:#fffde7,stroke:#795548,color:#4e342e",   # 🌱 seed — warm yellow/brown
    "concept":   "fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20",   # 🍃 leaf — green
    "application":"fill:#fce4ec,stroke:#c62828,color:#b71c1c",  # 🌸 flower — light red
}
_KIND_FILL = {"primitive": "#fffde7", "concept": "#e8f5e9", "application": "#fce4ec"}


def _to_mermaid(graph: nx.DiGraph) -> str:
    """Render as a Mermaid flowchart (renders inline on GitHub/most markdown viewers)."""
    lines = ["graph TD"]
    for kind, style in _KIND_STYLE.items():
        lines.append(f"    classDef {kind} {style}")
    for node, attrs in graph.nodes(data=True):
        label = node.replace("_", " ")
        lines.append(f'    {node}["{label}"]:::{attrs.get("kind", "concept")}')
    for u, v in graph.edges():
        lines.append(f"    {u} --> {v}")
    return "\n".join(lines)


def _to_dot(graph: nx.DiGraph) -> str:
    """Render as Graphviz DOT (render with: dot -Tpng -o graph.png graph.dot)."""
    lines = ["digraph concepts {", "    rankdir=LR;", "    node [shape=box, style=filled];"]
    for node, attrs in graph.nodes(data=True):
        fill = _KIND_FILL.get(attrs.get("kind", "concept"), "#ffffff")
        lines.append(f'    "{node}" [fillcolor="{fill}"];')
    for u, v in graph.edges():
        lines.append(f'    "{u}" -> "{v}";')
    lines.append("}")
    return "\n".join(lines)


def _to_ascii(graph: nx.DiGraph) -> str:
    """Render as a plain-text outline grouped by tier — readable in any terminal."""
    by_tier: dict[int, list[str]] = {}
    for node, attrs in graph.nodes(data=True):
        by_tier.setdefault(attrs.get("tier", 0), []).append(node)

    lines = []
    for tier in sorted(by_tier):
        lines.append(f"Tier {tier}")
        for node in sorted(by_tier[tier]):
            attrs = graph.nodes[node]
            prereqs = attrs.get("composed_of") or []
            arrow = f"  ← {', '.join(prereqs)}" if prereqs else ""
            lines.append(f"  [{attrs.get('kind', '?'):11}] {node}{arrow}")
            if attrs.get("defines"):
                lines.append(f"               {attrs['defines']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _to_html(graph: nx.DiGraph, domain_name: str = "") -> str:
    """Render a 4-panel interactive learning environment (self-contained, vis.js CDN).

    Layout (CSS grid):
      Left sidebar  │  Concept graph (vis.js, BFS levels)  │  Notes sidebar
                    ├──────────────────────────────────────│
                    │  Explanation panel                    │

    BFS longest-path levels replace YAML tier values so application nodes
    always land at the bottom (they often have tier=0 in YAML).
    Notes are auto-saved to localStorage per node.
    """
    nodes_data = []
    for node, attrs in graph.nodes(data=True):
        kind = attrs.get("kind", "concept")
        tier = attrs.get("tier", 0)
        color_map = {
            "primitive":   {"background": "#fffde7", "border": "#795548"},  # 🌱 seed
            "concept":     {"background": "#e8f5e9", "border": "#2e7d32"},  # 🍃 leaf
            "application": {"background": "#fce4ec", "border": "#c62828"},  # 🌸 flower
        }
        color = color_map.get(kind, color_map["concept"])
        prereqs = attrs.get("composed_of") or attrs.get("needs") or []
        labels = attrs.get("labels") or {}
        nodes_data.append({
            "id":      node,
            # English display label; `labels` carries every language so the
            # host app can relabel in place (graph.html stays language-invariant).
            "label":   labels.get("en") or node.replace("_", " "),
            "labels":  labels,
            "kind":    kind,
            "tier":    tier,
            "defines": attrs.get("defines", ""),
            "prereqs": prereqs,
            "verifier": attrs.get("verifier", ""),
            "lab":     attrs.get("lab", ""),
            "play":    attrs.get("play", ""),
            "color":   color,
            "font":    {"size": 13},
        })
    edges_data = [{"from": u, "to": v} for u, v in graph.edges()]

    graph_json = json.dumps({"nodes": nodes_data, "edges": edges_data}, ensure_ascii=False)
    title = f"Concept Graph — {domain_name}" if domain_name else "Concept Graph"
    domain_key = domain_name.replace(" ", "_").lower() or "graph"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,sans-serif;background:#f0f2f5;overflow:hidden;height:100vh}}
.app{{
  display:grid;
  grid-template-columns:230px 1fr 210px;
  grid-template-rows:60vh 40vh;
  height:100vh;
  gap:0;
}}
/* ── Left sidebar: learning path ── */
#path-sidebar{{
  grid-column:1;grid-row:1/3;
  background:#f5f6f8;color:#2a2a2a;
  display:flex;flex-direction:column;
  overflow:hidden;
  border-right:1px solid #dde0e6;
}}
#path-header{{
  padding:14px 14px 10px;
  border-bottom:1px solid #dde0e6;
  flex-shrink:0;
}}
#path-header h1{{font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:#888;margin-bottom:2px;font-weight:700}}
#path-header .domain-name{{font-size:11px;color:#555;margin-top:4px}}
#path-steps{{flex:1;overflow-y:auto;padding:8px 0}}
#path-steps .hint{{color:#aaa;font-size:12px;text-align:center;padding:24px 12px;line-height:1.5}}
.step-item{{
  display:flex;align-items:flex-start;gap:8px;
  padding:7px 12px;cursor:pointer;
  border-left:3px solid transparent;
  transition:background .15s;
}}
.step-item:hover{{background:#ebebf0}}
.step-item.active{{background:#e8eef8;border-left-color:#4a90d9}}
.step-item.target{{background:#eaf5ea;border-left-color:#4caf50}}
.step-num{{min-width:20px;font-size:10px;font-weight:700;color:#bbb;padding-top:2px;flex-shrink:0}}
.step-item.target .step-num{{color:#4caf50}}
.step-label{{font-size:12px;font-weight:600;color:#333;line-height:1.4}}
.step-def{{font-size:10px;color:#888;margin-top:2px;line-height:1.4}}
.step-kind{{display:inline-block;padding:0 5px;border-radius:8px;font-size:9px;font-weight:700;margin-left:4px}}
#path-count{{font-size:10px;color:#aaa;margin-top:3px}}
/* ── Graph panel ── */
#graph-panel{{
  grid-column:2;grid-row:1;
  position:relative;background:#fff;
  border-bottom:2px solid #dde;
}}
#graph-container{{width:100%;height:100%}}
.graph-recenter-btn{{
  position:absolute;right:16px;bottom:16px;z-index:50;
  padding:6px 14px;border-radius:6px;
  border:1px solid #1e3a5f;background:#1e3a5f;color:#fff;
  font-size:12px;font-weight:600;font-family:system-ui,sans-serif;
  box-shadow:0 1px 4px rgba(0,0,0,.25);cursor:pointer;
}}
.graph-recenter-btn:hover{{background:#28496f;border-color:#28496f}}
/* ── Explanation panel ── */
#explain-panel{{
  grid-column:2;grid-row:2;
  background:#fff;overflow-y:auto;
  padding:16px 20px;
}}
#explain-panel .empty{{color:#aaa;font-size:13px;padding:20px 0;text-align:center}}
#explain-panel .node-title{{
  display:flex;align-items:center;gap:8px;margin-bottom:10px;
}}
#explain-panel .node-title h2{{font-size:16px;color:#1e3a5f}}
.badge{{
  display:inline-block;padding:2px 8px;border-radius:10px;
  font-size:11px;font-weight:700;
}}
.badge.primitive{{background:#e8f5e9;color:#2e7d32}}
.badge.concept{{background:#e3f2fd;color:#1565c0}}
.badge.application{{background:#fff3e0;color:#ef6c00}}
.tier-tag{{font-size:11px;color:#999;margin-left:auto}}
#explain-panel .defines{{
  font-size:14px;color:#333;line-height:1.6;margin-bottom:12px;
  padding:10px 12px;background:#f8f9fb;border-radius:6px;
  border-left:3px solid #90b4e8;
}}
#explain-panel .section-label{{
  font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;color:#999;margin-bottom:6px;
}}
#explain-panel .prereq-list{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}}
.prereq-chip{{
  padding:3px 9px;border-radius:12px;font-size:11px;
  background:#e3f2fd;color:#1565c0;cursor:pointer;
  border:1px solid #90caf9;transition:background .12s;
}}
.prereq-chip:hover{{background:#bbdefb}}
#explain-panel .meta-row{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px}}
.meta-item{{font-size:12px;color:#555}}
.meta-item b{{color:#1e3a5f}}
#explain-panel .play-hint{{
  font-size:12px;color:#5a5a5a;line-height:1.6;
  padding:8px 12px;background:#fffde7;border-radius:6px;
  border-left:3px solid #ffd54f;margin-bottom:8px;
}}
/* ── Notes sidebar ── */
#notes-sidebar{{
  grid-column:3;grid-row:1/3;
  background:#fafaf8;
  border-left:2px solid #e8e8e0;
  display:flex;flex-direction:column;
  overflow:hidden;
}}
#notes-header{{
  padding:10px 12px 8px;
  border-bottom:1px solid #e0e0d8;
  flex-shrink:0;
}}
#notes-header-top{{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px}}
#notes-header h2{{font-size:12px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.06em;margin:0}}
#notes-node-label{{font-size:11px;color:#999;margin-top:2px}}
.nb-btn{{font-size:10px;padding:2px 7px;border-radius:3px;
  border:1px solid #ddd;background:#f0f0ea;cursor:pointer;color:#777;
  font-family:system-ui,sans-serif}}
.nb-btn:hover{{background:#e0e0d8;color:#444}}
#notes-textarea{{
  flex:0 0 auto;height:100px;border:none;resize:none;
  padding:12px;font-size:12px;line-height:1.6;
  font-family:inherit;background:#fafaf8;color:#333;
  outline:none;
}}
#notes-with-entries{{
  border-top:1px solid #e8e8e0;flex:1;min-height:0;overflow-y:auto;
}}
.note-entry{{
  padding:6px 12px;cursor:pointer;
  border-bottom:1px solid #f0f0e8;
  font-size:11px;
}}
.note-entry:hover{{background:#f0efe8}}
.note-entry .note-node{{font-weight:600;color:#555;display:flex;justify-content:space-between;align-items:center}}
.note-entry .note-ts{{font-weight:400;color:#bbb;font-size:10px}}
.note-entry .note-preview{{color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
/* ── kind badge colours in sidebar ── */
.primitive-k{{background:#e8f5e9;color:#2e7d32}}
.concept-k{{background:#e3f2fd;color:#1565c0}}
.application-k{{background:#fff3e0;color:#ef6c00}}
/* ── concept detail panel ── */
#concept-detail{{margin-top:14px;border-top:1px solid #e8e8e0;padding-top:10px;}}
#concept-iframe{{width:100%;height:500px;border:1px solid #e0e0d8;border-radius:4px;margin-top:6px;display:block;}}
.concept-not-found{{color:#e57373;font-size:12px;padding:6px 0;font-style:italic;}}
</style>
</head>
<body>
<div class="app">

<!-- LEFT: learning path sidebar -->
<aside id="path-sidebar">
  <div id="path-header">
    <h1>Learning Path</h1>
    <div class="domain-name">{domain_name}</div>
    <div id="path-count"></div>
  </div>
  <div id="path-steps">
    <div class="hint">Click any node in the graph<br>to see its learning path</div>
  </div>
</aside>

<!-- CENTRE TOP: concept graph -->
<div id="graph-panel">
  <div id="graph-container"></div>
  <button class="graph-recenter-btn" onclick="reCenterGraph()" title="Re-fit the graph to the viewport">Re-Center</button>
</div>

<!-- CENTRE BOTTOM: explanation panel -->
<div id="explain-panel">
  <div class="empty">Select a node to see its definition, prerequisites, and learning context.</div>
</div>

<!-- RIGHT: notes sidebar -->
<aside id="notes-sidebar">
  <div id="notes-header">
    <div id="notes-header-top">
      <h2>Notes</h2>
      <div>
        <button class="nb-btn" id="nb-clear-btn" onclick="clearNote()">Clear</button>
        <button class="nb-btn" onclick="exportNotes()">Export</button>
      </div>
    </div>
    <div id="notes-node-label">no node selected</div>
  </div>
  <textarea id="notes-textarea" placeholder="Type notes here&#10;(auto-saved per node)"></textarea>
  <div id="notes-with-entries"></div>
</aside>

</div><!-- .app -->

<script>
const RAW = {graph_json};
const DOMAIN_KEY = "{domain_key}";

// ── index ──────────────────────────────────────────────────────────────────
const nodeIndex = {{}};
RAW.nodes.forEach(n => nodeIndex[n.id] = n);

const prereqOf  = {{}};  // id → ids that are direct prerequisites OF id
const dependsOn = {{}};  // id → ids that id feeds into
RAW.nodes.forEach(n => {{ prereqOf[n.id] = []; dependsOn[n.id] = []; }});
RAW.edges.forEach(e => {{
  prereqOf[e.to].push(e.from);
  dependsOn[e.from].push(e.to);
}});

// ── BFS longest-path levels (fixes application nodes at wrong tier) ─────────
const bfsLevels = (() => {{
  const levels = {{}};
  const successors = {{}};
  RAW.nodes.forEach(n => {{ levels[n.id] = -1; successors[n.id] = []; }});
  RAW.edges.forEach(e => successors[e.from].push(e.to));
  const sources = RAW.nodes.filter(n => !RAW.edges.some(e => e.to === n.id));
  const queue = sources.map(n => n.id);
  queue.forEach(n => levels[n] = 0);
  let i = 0;
  while (i < queue.length) {{
    const cur = queue[i++];
    for (const succ of successors[cur]) {{
      const nl = levels[cur] + 1;
      if (levels[succ] < nl) {{ levels[succ] = nl; queue.push(succ); }}
    }}
  }}
  return levels;
}})();

// ── graph algorithms ────────────────────────────────────────────────────────
function getAncestors(targetId) {{
  const visited = new Set();
  const queue = [targetId];
  while (queue.length) {{
    const cur = queue.shift();
    for (const p of prereqOf[cur])
      if (!visited.has(p)) {{ visited.add(p); queue.push(p); }}
  }}
  return visited;
}}

function topoSort(nodeSet) {{
  const inDeg = {{}};
  nodeSet.forEach(n => inDeg[n] = 0);
  nodeSet.forEach(n => {{ for (const p of prereqOf[n]) if (nodeSet.has(p)) inDeg[n]++; }});
  const reach = {{}};
  nodeSet.forEach(n => {{
    let r = 0;
    nodeSet.forEach(m => {{ if (m !== n && getAncestors(m).has(n)) r++; }});
    reach[n] = r;
  }});
  const heap = [];
  nodeSet.forEach(n => {{ if (inDeg[n] === 0) heap.push(n); }});
  heap.sort((a, b) => (reach[b] - reach[a]) || a.localeCompare(b));
  const result = [];
  while (heap.length) {{
    const node = heap.shift();
    result.push(node);
    for (const succ of dependsOn[node]) {{
      if (!nodeSet.has(succ)) continue;
      if (--inDeg[succ] === 0) {{
        heap.push(succ);
        heap.sort((a, b) => (reach[b] - reach[a]) || a.localeCompare(b));
      }}
    }}
  }}
  return result;
}}

// ── vis.js network ──────────────────────────────────────────────────────────
// Wrap a label for a node box: Latin text breaks on spaces into ~14-char
// lines; CJK text (no spaces) breaks every 6 characters.
function wrapLabel(text) {{
  const words = String(text).split(' ');
  const lines = [];
  let line = '';
  for (const w of words) {{
    if (line && (line + ' ' + w).length > 14) {{ lines.push(line); line = w; }}
    else line = line ? line + ' ' + w : w;
  }}
  if (line) lines.push(line);
  return lines
    .flatMap(l => /[\\u3040-\\u30ff\\u3400-\\u9fff\\uac00-\\ud7af]/.test(l) && !l.includes(' ') && l.length > 6
      ? l.match(/.{{1,6}}/gu) : [l])
    .join('\\n');
}}

const container = document.getElementById('graph-container');
const visNodes = new vis.DataSet(RAW.nodes.map(n => ({{
  id: n.id,
  label: wrapLabel(n.label),
  level: bfsLevels[n.id] !== undefined ? bfsLevels[n.id] : n.tier,
  color: n.color,
  font: n.font,
  shape: n.kind === 'concept' ? 'ellipse' : 'box',
}})));
const visEdges = new vis.DataSet(RAW.edges.map((e, i) => ({{
  id: i, from: e.from, to: e.to,
  arrows: 'to', color: {{color: '#c8ccd4'}}, width: 1,
}})));
const network = new vis.Network(container, {{nodes: visNodes, edges: visEdges}}, {{
  layout: {{ hierarchical: {{
    enabled: true, direction: 'UD',
    sortMethod: 'directed', levelSeparation: 85, nodeSpacing: 130,
  }} }},
  physics: {{ enabled: false }},
  interaction: {{ hover: true, tooltipDelay: 150 }},
  edges: {{ smooth: {{ type: 'cubicBezier', forceDirection: 'vertical' }} }},
}});

// Compact layout: group by tier, sort alphabetically, left-align all nodes.
network.once('afterDrawing', function() {{
  const pos = network.getPositions();
  const spacing = 140;

  // Group nodes by their BFS tier
  const byTier = {{}};
  RAW.nodes.forEach(n => {{
    const tier = bfsLevels[n.id] ?? n.tier ?? 0;
    if (!byTier[tier]) byTier[tier] = [];
    byTier[tier].push(n.id);
  }});

  // Sort each tier alphabetically, assign X starting from 0
  const tiers = Object.keys(byTier).map(Number).sort((a, b) => a - b);
  const tierSep = 85;
  tiers.forEach((tier, ti) => {{
    const ids = byTier[tier].sort();
    const y = ti * tierSep;
    ids.forEach((id, i) => {{
      network.moveNode(id, i * spacing, y);
    }});
  }});

  network.fit({{ animation: false }});
}});

function reCenterGraph() {{
  network.fit({{ animation: true }});
}}

const C_PATH   = {{background: '#fff9c4', border: '#f9a825'}};
const C_TARGET = {{background: '#ffe082', border: '#e65100'}};

function resetColors() {{
  visNodes.update(RAW.nodes.map(n => ({{id: n.id, color: n.color}})));
  visEdges.update(RAW.edges.map((e, i) => ({{id: i, color: {{color: '#c8ccd4'}}, width: 1}})));
}}

// ── explanation panel ───────────────────────────────────────────────────────
function renderExplanation(node) {{
  const kclass = node.kind;
  const prereqChips = (node.prereqs || []).map(p =>
    `<span class="prereq-chip" onclick="selectNode('${{p}}')">${{p.replace(/_/g,' ')}}</span>`
  ).join('');
  const metaItems = [
    node.verifier ? `<span class="meta-item"><b>Verifier:</b> ${{node.verifier}}</span>` : '',
    node.lab      ? `<span class="meta-item"><b>Lab:</b> ${{node.lab}}</span>` : '',
  ].filter(Boolean).join('');
  const playHtml = node.play
    ? `<div class="section-label">Try it</div><div class="play-hint">${{node.play}}</div>`
    : '';

  const panel = document.getElementById('explain-panel');
  panel.innerHTML = `
    <div class="node-title">
      <h2>${{node.label}}</h2>
      <span class="badge ${{kclass}}">${{kclass}}</span>
      <span class="tier-tag">BFS level ${{bfsLevels[node.id] ?? node.tier}}</span>
    </div>
    ${{node.defines ? `<div class="defines">${{node.defines}}</div>` : ''}}
    ${{prereqChips ? `<div class="section-label">Prerequisites</div><div class="prereq-list">${{prereqChips}}</div>` : ''}}
    ${{metaItems ? `<div class="meta-row">${{metaItems}}</div>` : ''}}
    ${{playHtml}}
  `;

  // ── concept HTML detail ──
  const conceptsBase = window.__cb_CONCEPTS_BASE;
  const conceptUrls = window.__cb_CONCEPT_URLS || {{}};
  const mappedUrl = conceptUrls[node.id];
  if (mappedUrl || conceptsBase) {{
    const conceptUrl = mappedUrl || (conceptsBase + 'concept_' + encodeURIComponent(node.id) + '.html');
    const detail = document.createElement('div');
    detail.id = 'concept-detail';
    detail.innerHTML = '<div class="section-label">Concept Detail</div><div class="concept-loading" style="color:#aaa;font-size:12px;padding:6px 0">Loading…</div>';
    panel.appendChild(detail);
    fetch(conceptUrl)
      .then(r => {{
        if (!r.ok) throw new Error('not found');
        return r.text();
      }})
      .then(html => {{
        const slot = detail.querySelector('.concept-loading');
        if (!slot) return;
        // Vite dev server returns the SPA index.html (200) for missing static files.
        // Verify we got a real concept page by checking for a known marker.
        if (html.includes('spl-credit') || html.includes('Powered by')) {{
          const iframe = document.createElement('iframe');
          iframe.id = 'concept-iframe';
          iframe.src = conceptUrl;
          slot.replaceWith(iframe);
        }} else {{
          slot.className = 'concept-not-found';
          slot.textContent = 'Content not found — generate it first.';
        }}
      }})
      .catch(() => {{
        const slot = detail.querySelector('.concept-loading');
        if (slot) {{ slot.className = 'concept-not-found'; slot.textContent = 'Content not found — generate it first.'; }}
      }});
  }}
}}

// ── learning path sidebar ───────────────────────────────────────────────────
function renderPathSidebar(orderedPath, targetId) {{
  const stepsEl = document.getElementById('path-steps');
  const countEl = document.getElementById('path-count');
  countEl.textContent = orderedPath.length
    ? `${{orderedPath.length}} step${{orderedPath.length !== 1 ? 's' : ''}} to learn first`
    : 'Root concept — no prerequisites';

  const target = nodeIndex[targetId];
  const kc = k => `${{k.charAt(0).toUpperCase() + k.slice(1)}}`;

  stepsEl.innerHTML = orderedPath.map((n, i) => {{
    const nd = nodeIndex[n];
    return `<div class="step-item" onclick="selectNode('${{n}}')">
      <span class="step-num">${{i + 1}}.</span>
      <div>
        <div class="step-label">${{nd.label}}
          <span class="step-kind ${{nd.kind}}-k">${{nd.kind}}</span>
        </div>
        ${{nd.defines ? `<div class="step-def">${{nd.defines}}</div>` : ''}}
      </div>
    </div>`;
  }}).join('') + `<div class="step-item target">
    <span class="step-num">▶</span>
    <div>
      <div class="step-label">${{target.label}}
        <span class="step-kind ${{target.kind}}-k">${{target.kind}}</span>
      </div>
      ${{target.defines ? `<div class="step-def">${{target.defines}}</div>` : ''}}
    </div>
  </div>`;
}}

// ── notes (localStorage) ────────────────────────────────────────────────────
let currentNodeId = null;

function noteKey(nodeId) {{ return `concept_notes_${{DOMAIN_KEY}}_${{nodeId}}`; }}

function loadNote(nodeId) {{
  const parsed = _parseNote(localStorage.getItem(noteKey(nodeId)));
  return parsed ? parsed.text : '';
}}

function saveNote(nodeId, text) {{
  if (text.trim()) {{
    const data = JSON.stringify({{ text, ts: new Date().toISOString() }});
    localStorage.setItem(noteKey(nodeId), data);
  }} else {{
    localStorage.removeItem(noteKey(nodeId));
  }}
  renderNotesList();
}}

function _parseNote(raw) {{
  if (!raw) return null;
  try {{ const d = JSON.parse(raw); return {{ text: d.text || '', ts: d.ts || '' }}; }}
  catch (_) {{ return {{ text: raw, ts: '' }}; }}
}}

function _fmtTs(iso) {{
  if (!iso) return '';
  const d = new Date(iso);
  const yy = d.getFullYear();
  const mm = String(d.getMonth()+1).padStart(2,'0');
  const dd = String(d.getDate()).padStart(2,'0');
  const hh = String(d.getHours()).padStart(2,'0');
  const mi = String(d.getMinutes()).padStart(2,'0');
  return `${{yy}}-${{mm}}-${{dd}} ${{hh}}:${{mi}}`;
}}

function renderNotesList() {{
  const container = document.getElementById('notes-with-entries');
  const entries = RAW.nodes
    .filter(n => localStorage.getItem(noteKey(n.id)))
    .map(n => {{
      const parsed = _parseNote(localStorage.getItem(noteKey(n.id)));
      return {{id: n.id, label: n.label, preview: (parsed?.text || '').slice(0, 60), ts: parsed?.ts || ''}};
    }});
  if (!entries.length) {{ container.innerHTML = ''; return; }}
  container.innerHTML = entries.map(e =>
    `<div class="note-entry" onclick="selectNode('${{e.id}}')">
      <div class="note-node">${{e.label}}<span class="note-ts">${{_fmtTs(e.ts)}}</span></div>
      <div class="note-preview">${{e.preview}}</div>
    </div>`
  ).join('');
}}

function switchNotes(nodeId) {{
  if (currentNodeId !== null) {{
    saveNote(currentNodeId, document.getElementById('notes-textarea').value);
  }}
  currentNodeId = nodeId;
  document.getElementById('notes-textarea').value = loadNote(nodeId);
  document.getElementById('notes-node-label').textContent =
    nodeIndex[nodeId]?.label || nodeId;
}}

function clearNote() {{
  if (!currentNodeId) return;
  document.getElementById('notes-textarea').value = '';
  saveNote(currentNodeId, '');
  const btn = document.getElementById('nb-clear-btn');
  if (btn) {{ btn.textContent = 'Cleared!'; setTimeout(() => {{ btn.textContent = 'Clear'; }}, 1000); }}
}}

function exportNotes() {{
  const notes = {{}};
  RAW.nodes.forEach(n => {{
    const v = localStorage.getItem(noteKey(n.id));
    if (v) notes[n.id] = v;
  }});
  const blob = new Blob([JSON.stringify(notes, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${{DOMAIN_KEY}}_notes.json`;
  a.click();
}}

document.getElementById('notes-textarea').addEventListener('input', () => {{
  if (currentNodeId) saveNote(currentNodeId, document.getElementById('notes-textarea').value);
}});

// ── unified node select ─────────────────────────────────────────────────────
function selectNode(nodeId) {{
  if (!nodeIndex[nodeId]) return;
  network.selectNodes([nodeId]);
  handleSelect(nodeId);
}}

function handleSelect(targetId) {{
  const node = nodeIndex[targetId];

  renderExplanation(node);
  switchNotes(targetId);

  const ancestors = getAncestors(targetId);
  const pathSet = new Set([...ancestors]);
  const orderedPath = topoSort(pathSet);

  renderPathSidebar(orderedPath, targetId);

  resetColors();
  visNodes.update(orderedPath.map(n => ({{id: n, color: C_PATH}})));
  visNodes.update([{{id: targetId, color: C_TARGET}}]);
  visEdges.update(RAW.edges.map((e, i) => {{
    const inPath = pathSet.has(e.from) && (pathSet.has(e.to) || e.to === targetId);
    return {{id: i, color: {{color: inPath ? '#f9a825' : '#c8ccd4'}}, width: inPath ? 2 : 1}};
  }}));
}}

network.on('click', params => {{
  if (params.nodes.length) handleSelect(params.nodes[0]);
}});

// initialise notes list on load
renderNotesList();

// When viewed directly (not in an iframe), inject a back link next to the
// "Learning Path" heading so it doesn't look like a title-bar element.
if (window.parent === window) {{
  var h1 = document.querySelector('#path-header h1');
  if (h1) {{
    var backLink = document.createElement('a');
    backLink.href = '../../';
    backLink.textContent = '← App';
    backLink.style.cssText = [
      'font-size:10px','color:#2563eb','font-family:system-ui,sans-serif',
      'text-decoration:none','font-weight:400','letter-spacing:normal',
      'text-transform:none','white-space:nowrap','flex-shrink:0'
    ].join(';');
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:baseline;gap:8px;';
    h1.parentNode.insertBefore(row, h1);
    row.appendChild(h1);
    row.appendChild(backLink);
  }}
}}
</script>
</body>
</html>"""


_RENDERERS = {"mermaid": _to_mermaid, "dot": _to_dot, "ascii": _to_ascii, "html": None}


# ---------------------------------------------------------------------------
# Domain loading — `--domain linalg_graph`, `--domain path/to/graph.py`, or
# `--domain hybrid.json` (an exported / composed graph — see `compose` below)
# ---------------------------------------------------------------------------

class _GraphModule:
    """Wraps a pre-built graph so it satisfies the `build()` domain contract.

    Lets exported/composed JSON graphs flow back through the same --domain
    pipeline as Python domain modules — `compose` writes one of these, and
    `stats`/`show`/`visualize`/... can immediately analyze it.
    """

    def __init__(self, graph: nx.DiGraph):
        self._graph = graph

    def build(self) -> nx.DiGraph:
        return self._graph


def _load_yaml_graph(path: Path) -> nx.DiGraph:
    """Build a DiGraph from a concept-graph YAML file (74_concept_book format).

    Handles primitives (no composed_of), concepts (composed_of list),
    and applications (needs list).  Edges u→v mean "u is prerequisite of v".
    """
    if not _YAML_AVAILABLE:
        raise click.ClickException("PyYAML is required to load .yaml graphs: pip install pyyaml")
    raw = _yaml.safe_load(path.read_text(encoding="utf-8"))
    g = nx.DiGraph()
    g.graph["domain"] = raw.get("domain", path.stem)

    def _add_nodes(section: dict, kind: str) -> None:
        for name, attrs in (section or {}).items():
            prereqs = attrs.get("composed_of") or attrs.get("needs") or []
            g.add_node(name,
                kind=kind,
                tier=attrs.get("tier", 0),
                defines=attrs.get("defines", ""),
                composed_of=prereqs,
                verifier=attrs.get("verifier", ""),
                lab=attrs.get("lab", ""),
                play=attrs.get("play", ""),
                domain=attrs.get("domain", ""),
                labels=attrs.get("labels") or {},
            )
            for prereq in prereqs:
                g.add_edge(prereq, name)

    _add_nodes(raw.get("primitives", {}), "primitive")
    _add_nodes(raw.get("concepts", {}), "concept")
    _add_nodes(raw.get("applications", {}), "application")
    return g


def _graph_to_yaml(graph: nx.DiGraph) -> str:
    """Serialise a concept-graph DiGraph to canonical YAML (SPL concept-book format).

    Output sections: domain → primitives → concepts → applications.
    Each section is sorted by tier then name.  Application prereqs use ``needs:``
    to match the authoring convention; all others use ``composed_of:``.

    The result is valid PyYAML-loadable text and is designed to be easy to
    hand-edit — short strings stay inline, strings containing special YAML
    characters are single-quoted, and each section gets a blank-line separator.
    """
    if not _YAML_AVAILABLE:
        raise click.ClickException("PyYAML required to write YAML: pip install pyyaml")

    def _scalar(value: str) -> str:
        """Return value as a safe inline YAML scalar (single-quoted when needed)."""
        if not value:
            return "''"
        # Characters that require quoting in YAML bare scalars
        needs_quote = any(c in value for c in ":#{}[]|>&*!,?@`\"'") or value[0] in "-"
        if needs_quote:
            return "'" + value.replace("'", "''") + "'"
        return value

    def _list_block(items: list[str], indent: str) -> list[str]:
        return [f"{indent}- {item}" for item in items]

    domain_name = graph.graph.get("domain", "")
    by_kind: dict[str, list[tuple[str, dict]]] = {"primitive": [], "concept": [], "application": []}
    for node, attrs in graph.nodes(data=True):
        kind = attrs.get("kind", "concept")
        by_kind.setdefault(kind, []).append((node, dict(attrs)))
    for kind in by_kind:
        by_kind[kind].sort(key=lambda x: (x[1].get("tier", 0), x[0]))

    lines: list[str] = []
    if domain_name:
        lines.append(f"domain: {_scalar(domain_name)}")
    lines.append("")

    def _write_section(kind: str, section_key: str, prereq_key: str) -> None:
        nodes = by_kind.get(kind, [])
        if not nodes:
            return
        lines.append(f"{section_key}:")
        for name, attrs in nodes:
            lines.append(f"  {name}:")
            if attrs.get("defines"):
                lines.append(f"    defines: {_scalar(attrs['defines'])}")
            tier = attrs.get("tier")
            if tier is not None:
                lines.append(f"    tier: {int(tier)}")
            prereqs = attrs.get("composed_of") or []
            if prereqs:
                lines.append(f"    {prereq_key}:")
                lines.extend(_list_block(prereqs, "    "))
            for key in ("verifier", "lab", "play", "domain"):
                val = attrs.get(key, "")
                if val:
                    lines.append(f"    {key}: {_scalar(str(val))}")
        lines.append("")

    _write_section("primitive", "primitives", "composed_of")
    _write_section("concept",   "concepts",   "composed_of")
    _write_section("application", "applications", "needs")
    return "\n".join(lines)


def _load_domain(domain: str):
    """Load a domain module by import name, ``.py`` file path, ``.yaml``, or ``.json`` graph."""
    path = Path(domain)
    if domain.endswith(".yaml") or domain.endswith(".yml"):
        return _GraphModule(_load_yaml_graph(path))
    if domain.endswith(".json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        return _GraphModule(nx.node_link_graph(data, directed=True, multigraph=False))
    if domain.endswith(".py") or path.exists():
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise click.ClickException(f"Cannot load domain module from {domain!r}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    try:
        return importlib.import_module(domain)
    except ImportError as exc:
        raise click.ClickException(f"Cannot import domain module {domain!r}: {exc}")


# ---------------------------------------------------------------------------
# CLI — `python concept_graph.py --domain <module_or_path> <command> ...`
# ---------------------------------------------------------------------------

class _Domain:
    """Lazily resolves --domain to a built graph.

    Lazy because `import` only inspects an exported JSON file — it has no
    need for a domain graph, so it shouldn't be forced to require --domain.
    """

    def __init__(self, name: str | None):
        self._name = name
        self._graph: nx.DiGraph | None = None

    @property
    def graph(self) -> nx.DiGraph:
        graph = self._graph
        if graph is None:
            if not self._name:
                raise click.ClickException("This command requires --domain MODULE_OR_PATH")
            module = _load_domain(self._name)
            if not hasattr(module, "build"):
                raise click.ClickException(
                    f"{self._name!r} has no build() — not a concept-graph domain module")
            graph = module.build()
            self._graph = graph
        return graph


@click.group()
@click.option("--domain", "-d", default=None,
              help="Domain module to analyze — an importable module name "
                   "(e.g. linalg_graph) or a path to its .py file. "
                   "Required by every command except `import`.")
@click.pass_context
def cli(ctx, domain):
    """Inspect, visualize, and share any concept graph exposing build()."""
    ctx.obj = _Domain(domain)


@cli.command()
@click.option("--strict", is_flag=True,
              help="Every leaf must be an explicitly declared primitive — the tighter "
                   "rule generation itself does not enforce. Use to review which "
                   "concepts are quietly relying on the lenient rule.")
@click.pass_obj
def stats(domain, strict):
    """Print node/edge counts and the structural verifier checks."""
    graph = domain.graph
    click.echo(f"Nodes: {graph.number_of_nodes()}  Edges: {graph.number_of_edges()}")
    click.echo(f"Acyclic: {acyclic(graph)}")
    primitives = [n for n, d in graph.nodes(data=True) if d.get("kind") == "primitive"]
    click.echo(f"Reducible (to its {len(primitives)} declared primitives): "
               f"{reducible(graph, primitives, strict=strict)}")
    # Leaves (in-degree 0) that are declared concepts/applications rather than
    # primitives — accepted automatically by the lenient rule, but worth a
    # teacher's eye: promote to primitives:, add a real composed_of, or leave
    # as-is if it's genuinely a fine domain-local stopping point.
    local_axioms = sorted(
        n for n, d in graph.nodes(data=True)
        if d.get("kind") != "primitive" and graph.in_degree(n) == 0
    )
    if local_axioms:
        click.echo(f"Local axioms (declared concepts with no composed_of, not in primitives:): "
                   f"{len(local_axioms)}")
        for n in local_axioms:
            click.echo(f"    {n}")
    by_kind: dict[str, int] = {}
    for _, attrs in graph.nodes(data=True):
        by_kind[attrs.get("kind", "?")] = by_kind.get(attrs.get("kind", "?"), 0) + 1
    for kind, count in sorted(by_kind.items()):
        click.echo(f"  {kind:11}: {count}")


@cli.command(name="list")
@click.option("--kind", type=click.Choice(["primitive", "concept", "application"]),
              default=None, help="Restrict to one node kind.")
@click.pass_obj
def list_nodes(domain, kind):
    """List nodes ordered by tier, optionally filtered by --kind."""
    graph = domain.graph
    rows = [
        (attrs.get("tier", 0), name, attrs.get("kind"))
        for name, attrs in graph.nodes(data=True)
        if kind is None or attrs.get("kind") == kind
    ]
    for tier, name, k in sorted(rows):
        click.echo(f"  tier {tier}  [{k:11}] {name}")


@cli.command()
@click.argument("node")
@click.pass_obj
def show(domain, node):
    """Show full metadata for one node (definition, prerequisites, applications)."""
    graph = domain.graph
    if not in_graph(graph, node):
        raise click.ClickException(f"Unknown node: {node!r}")
    attrs = graph.nodes[node]
    click.echo(f"{node}  [{attrs.get('kind')}]  tier={attrs.get('tier')}")
    if attrs.get("defines"):
        click.echo(f"  defines : {attrs['defines']}")
    if attrs.get("composed_of"):
        click.echo(f"  needs   : {', '.join(attrs['composed_of'])}")
    apps = applications_of(graph, node)
    if apps:
        click.echo(f"  unlocks : {', '.join(apps)}")
    for key in ("verifier", "lab", "play", "domain"):
        if attrs.get(key):
            click.echo(f"  {key:8}: {attrs[key]}")


@cli.command(name="ancestors")
@click.argument("target")
@click.pass_obj
def ancestors_cmd(domain, target):
    """List everything `target` transitively depends on."""
    graph = domain.graph
    if not in_graph(graph, target):
        raise click.ClickException(f"Unknown node: {target!r}")
    anc = ancestors(graph, target)
    click.echo(f"Ancestors of {target} ({len(anc)}):")
    for n in sorted(anc):
        click.echo(f"  {n}")


@cli.command()
@click.argument("target")
@click.option("--know", "-k", "known", multiple=True,
              help="Concept the learner already knows (repeatable).")
@click.option("--weight", default=1.0, show_default=True,
              help="Application-reach weight used to order the remaining steps.")
@click.pass_obj
def path(domain, target, known, weight):
    """Print the productivity-ordered steps still needed to reach `target`."""
    graph = domain.graph
    if not in_graph(graph, target):
        raise click.ClickException(f"Unknown node: {target!r}")
    remaining = learning_path(graph, target, known, weight=weight)
    if not remaining:
        click.echo(f"Nothing left to learn — {target} is already reachable from your known set.")
        return
    click.echo(f"Learning path to {target} ({len(remaining)} steps):")
    for i, n in enumerate(remaining, 1):
        click.echo(f"  {i:2}. {n}")


@cli.command()
@click.option("--weight", default=1.0, show_default=True,
              help="Application-reach weight used to break topological ties.")
@click.pass_obj
def order(domain, weight):
    """Print every node in productivity (topological + reach-weighted) order."""
    graph = domain.graph
    for i, n in enumerate(productivity_order(graph, weight=weight), 1):
        kind = graph.nodes[n].get("kind", "?")
        click.echo(f"  {i:2}. [{kind:11}] {n}")


@cli.command()
@click.option("--format", "fmt", type=click.Choice(sorted(_RENDERERS)), default="mermaid",
              show_default=True, help="Output format.")
@click.option("--target", "-t", default=None,
              help="Restrict to the ancestor closure of this node (instead of the full graph).")
@click.option("--output", "-o", type=click.Path(dir_okay=False, writable=True), default=None,
              help="Write to a file instead of stdout.  For --format html, defaults to "
                   "<domain>.html in the current directory.")
@click.pass_context
def visualize(ctx, fmt, target, output):
    """Render the concept graph as mermaid / graphviz-dot / ascii / interactive html.

    The html format produces a self-contained page: click any node to see its
    productivity-ordered learning path highlighted in the graph.
    """
    domain = ctx.obj
    graph = domain.graph
    domain_name = domain._name or ""
    if target:
        if not in_graph(graph, target):
            raise click.ClickException(f"Unknown node: {target!r}")
        graph = restrict(graph, ancestors(graph, target) | {target})

    if fmt == "html":
        stem = Path(domain_name).stem if domain_name else "concept_graph"
        text = _to_html(graph, domain_name=stem)
        if output:
            out_path = Path(output)
        else:
            # default: <domain_dir>/output/html/<stem>.html
            domain_dir = Path(domain_name).parent if domain_name else Path(".")
            out_path = domain_dir / "output" / "html" / f"{stem}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        click.echo(f"Wrote interactive HTML ({graph.number_of_nodes()} nodes) → {out_path}")
        return

    text = _RENDERERS[fmt](graph)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        click.echo(f"Wrote {fmt} graph ({graph.number_of_nodes()} nodes) to {output}")
    else:
        click.echo(text)


@cli.command()
@click.argument("output", type=click.Path(dir_okay=False, writable=True))
@click.option("--format", "fmt",
              type=click.Choice(["yaml", "json"]), default=None,
              help="Output format. Inferred from the file extension when omitted "
                   "(.yaml/.yml → yaml, anything else → json).")
@click.option("--target", "-t", multiple=True,
              help="Export only the ancestor closure of these nodes (repeatable). "
                   "Default: export the full graph.")
@click.pass_obj
def export(domain, output, fmt, target):
    """Export the graph (or a subgraph) to YAML or JSON for sharing / reuse.

    YAML is the preferred format — it supports hand-editing and comments.
    JSON (networkx node-link format) is useful for programmatic consumers and
    can be loaded back via ``--domain file.json`` or ``import``.

    \b
        # Export full graph to YAML (canonical, shareable)
        python concept_graph.py --domain linalg_graph.py export linalg.yaml

        # Export the ancestor closure of one concept to JSON
        python concept_graph.py --domain linalg.yaml export eigen.json -t eigenpair

        # Export subgraph to YAML then use it as its own domain
        python concept_graph.py --domain linalg.yaml export core.yaml -t spectral_theorem
        python concept_graph.py --domain core.yaml stats
    """
    graph = domain.graph
    if target:
        keep = set(target)
        for t in target:
            if not in_graph(graph, t):
                raise click.ClickException(f"Unknown node: {t!r}")
            keep |= ancestors(graph, t)
        graph = restrict(graph, keep)

    out_path = Path(output)
    # Infer format from extension when not explicit
    resolved_fmt = fmt or ("yaml" if out_path.suffix.lower() in (".yaml", ".yml") else "json")

    if resolved_fmt == "yaml":
        if not _YAML_AVAILABLE:
            raise click.ClickException("PyYAML required for YAML export: pip install pyyaml")
        out_path.write_text(_graph_to_yaml(graph), encoding="utf-8")
    else:
        data = nx.node_link_data(graph)
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    click.echo(f"Exported {graph.number_of_nodes()} nodes / {graph.number_of_edges()} "
               f"edges → {output} ({resolved_fmt})")


@cli.command()
@click.option("--domain", "-d", "domains", multiple=True, required=True,
              help="A domain to fold in (repeatable — give at least two, "
                   "e.g. -d linalg_graph -d geometry_graph).")
@click.argument("output", type=click.Path(dir_okay=False, writable=True))
def compose(domains, output):
    """Compose several domain graphs into one hybrid concept graph.

    Authoring a concept graph that spans multiple fields by hand is exactly
    the kind of "too daunting to publish" task the concept-book framework
    exists to make tractable — `compose` takes that first mechanical step:
    union the domains' nodes and edges into one graph and write it out as
    JSON (the same shareable shape `export` produces, so the result flows
    straight back into `stats`/`show`/`visualize`/... via --domain hybrid.json).

    Kept deliberately simple for now: nodes are merged by name, last domain
    wins on attribute conflicts, and every name collision across domains is
    reported so the author can resolve it (rename one side, or confirm the
    overlap is intentional and should become a bridging point). Smarter
    merge strategies — explicit bridging edges, namespacing, alias maps —
    can layer on top once real hybrid graphs show what's actually needed.
    """
    if len(domains) < 2:
        raise click.ClickException("compose needs at least two --domain values")

    combined = nx.DiGraph()
    owner: dict[str, str] = {}
    collisions: list[tuple[str, str, str]] = []
    for name in domains:
        graph = _Domain(name).graph
        for node in graph.nodes():
            if node in owner and owner[node] != name:
                collisions.append((node, owner[node], name))
            owner[node] = name
        combined = nx.compose(combined, graph)

    data = nx.node_link_data(combined)
    Path(output).write_text(json.dumps(data, indent=2), encoding="utf-8")
    click.echo(f"Composed {len(domains)} domains ({', '.join(domains)}) into "
               f"{combined.number_of_nodes()} nodes / {combined.number_of_edges()} "
               f"edges → {output}")
    if collisions:
        click.echo(f"\n{len(collisions)} name collision(s) — later domain's node wins:")
        for node, first, second in collisions:
            click.echo(f"  {node!r}: declared by both {first!r} and {second!r}")


@cli.command(name="import")
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
def import_cmd(input_file):
    """Load a concept graph from any supported format and report its shape.

    Accepts .yaml/.yml (SPL concept-book format), .json (networkx node-link),
    or a .py domain module exposing ``build() -> DiGraph``.  No ``--domain``
    flag needed — the file itself is the source.

    \b
        python concept_graph.py import linalg_graph.yaml
        python concept_graph.py import linalg_graph.py
        python concept_graph.py import hybrid.json

    Typical reuse workflow:
      1. import a graph to inspect it
      2. export a subgraph (ancestor closure of key concepts) to a new YAML
      3. compose two graphs into a hybrid
      4. pass the result as --domain to visualize / stats / path
    """
    module = _load_domain(input_file)
    loaded = module.build()

    ext = Path(input_file).suffix.lower()
    fmt_label = {".yaml": "yaml", ".yml": "yaml", ".json": "json", ".py": "python module"}.get(ext, ext)
    domain_name = loaded.graph.get("domain", "") if loaded.graph else ""
    domain_tag = f" (domain: {domain_name})" if domain_name else ""

    click.echo(f"Loaded {loaded.number_of_nodes()} nodes / {loaded.number_of_edges()} "
               f"edges from {input_file} [{fmt_label}]{domain_tag}")
    click.echo(f"Acyclic   : {acyclic(loaded)}")
    primitives = [n for n, d in loaded.nodes(data=True) if d.get("kind") == "primitive"]
    click.echo(f"Reducible : {reducible(loaded, primitives)}")
    by_kind: dict[str, int] = {}
    for _, attrs in loaded.nodes(data=True):
        k = attrs.get("kind", "?")
        by_kind[k] = by_kind.get(k, 0) + 1
    for kind, count in sorted(by_kind.items()):
        click.echo(f"  {kind:11}: {count}")


@cli.command()
@click.argument("output", type=click.Path(dir_okay=False, writable=True))
@click.option("--force", is_flag=True, default=False,
              help="Overwrite output file if it already exists.")
@click.pass_obj
def convert(domain, output, force):
    """Convert any concept-graph format to canonical YAML.

    YAML is the first-class concept-graph format in SPL — it supports comments,
    is easy to author and diff, and is the canonical input for concept-book
    generation and the HTML visualiser.  Use this command to migrate graphs:

    \b
        # Python domain module → YAML
        python concept_graph.py --domain linalg_graph.py convert linalg_graph.yaml

        # networkx JSON export → YAML
        python concept_graph.py --domain hybrid.json convert hybrid.yaml

        # Round-trip check: reload the YAML and diff stats
        python concept_graph.py --domain linalg_graph.yaml stats

    The output YAML follows the 74_concept_book structure:
    domain → primitives → concepts → applications, sorted by tier then name.
    Primitive and concept prereqs use ``composed_of:``, application prereqs use
    ``needs:`` — matching the hand-authored YAML convention.

    Nodes that carry no ``kind`` attribute are written as concepts.  Tier values
    are inferred from the graph topology (longest-path from sources) for any node
    whose stored tier is 0 and that has in-edges — this corrects the common case
    where JSON-exported graphs have lost tier information.
    """
    if not _YAML_AVAILABLE:
        raise click.ClickException("PyYAML required: pip install pyyaml")

    out_path = Path(output)
    if out_path.exists() and not force:
        raise click.ClickException(
            f"{output!r} already exists — pass --force to overwrite.")

    graph = domain.graph

    # Repair missing / stale tier values via longest-path from sources.
    # Sources (in-degree 0) get tier 0; every other node gets
    # max(tier of predecessors) + 1.  Only applied where the stored tier
    # would place a node above all its prerequisites (a sign of missing data).
    topo = list(nx.topological_sort(graph))
    computed: dict[str, int] = {}
    for node in topo:
        preds = list(graph.predecessors(node))
        computed[node] = max((computed[p] for p in preds), default=-1) + 1
    for node in graph.nodes():
        stored = graph.nodes[node].get("tier", 0)
        if stored == 0 and computed[node] > 0:
            graph.nodes[node]["tier"] = computed[node]

    yaml_text = _graph_to_yaml(graph)
    out_path.write_text(yaml_text, encoding="utf-8")

    by_kind: dict[str, int] = {}
    for _, attrs in graph.nodes(data=True):
        k = attrs.get("kind", "concept")
        by_kind[k] = by_kind.get(k, 0) + 1
    summary = ", ".join(f"{v} {k}s" for k, v in sorted(by_kind.items()))
    click.echo(f"Wrote {graph.number_of_nodes()} nodes ({summary}), "
               f"{graph.number_of_edges()} edges → {output}")


@cli.command()
@click.argument("output", required=False, default=None,
                type=click.Path(dir_okay=False, writable=True))
@click.option("--include-book", "-b", "book_html", default=None,
              type=click.Path(exists=True),
              help="Path to a generated concept-book HTML to bundle alongside the graph.")
@click.pass_context
def share(ctx, output, book_html):
    """Bundle the concept graph (YAML + HTML navigator) into a shareable .zip.

    The zip contains:
      <stem>_graph.yaml          — the source graph (canonical, editable)
      <stem>_graph.html          — the interactive navigator (vis.js, self-contained)
      <stem>_concept_book.html   — (optional) the generated concept-book HTML

    Open the .html files directly in any browser — no server required.
    Use ``publish`` (coming in Phase 5) for formal, vetted distribution.

    OUTPUT defaults to <stem>_share.zip in the current directory.
    """
    import zipfile

    domain = ctx.obj
    domain_name = domain._name or "concept_graph"
    # Strip trailing _graph suffix so chinese_characters_graph → chinese_characters
    raw_stem = Path(domain_name).stem
    stem = raw_stem[:-6] if raw_stem.endswith("_graph") else raw_stem

    # Generate the HTML navigator into a temp string
    graph = domain.graph
    html_text = _to_html(graph, domain_name=stem)

    # Re-serialize the graph to canonical YAML
    yaml_text = _graph_to_yaml(graph)

    out_path = Path(output) if output else Path(f"{stem}_share.zip")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stem}_graph.yaml", yaml_text)
        zf.writestr(f"{stem}_graph.html", html_text)
        if book_html:
            book_path = Path(book_html)
            zf.write(book_path, arcname=f"{stem}_concept_book.html")

    contents = [f"{stem}_graph.yaml", f"{stem}_graph.html"]
    if book_html:
        contents.append(f"{stem}_concept_book.html")
    click.echo(f"Wrote share bundle ({', '.join(contents)}) → {out_path}")
    click.echo("Recipient: unzip and open the .html file(s) in any browser.")


if __name__ == "__main__":
    cli()
