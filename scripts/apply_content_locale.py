#!/usr/bin/env python3
"""Merge locales/content.yaml into the files the app and SPL actually read.

  concepts.<id>                    → each graph.yaml node's `labels:` (every domain
                                     that has the node; read by spl/tools.py
                                     localized_label() and, via concept_graph.py,
                                     by graph.html)
  domains.<id>.concepts.<node>     → a domain-scoped override of the above, for a
                                     node id that means something else in that domain
  domains.<id>.name / description  → catalog.json `name`/`description` (source
                                     language) and `i18n.<lang>.{name,description}`

graph.yaml files get line-level edits of just their `labels:` blocks (ruamel.yaml
finds the positions), so comments, layout and line wrapping all survive; catalog.json is written through scripts/catalog_lock.py. Files
already in sync are left untouched. Re-render graph.html afterwards (e.g.
scripts/sync_from_spl.sh, or concept_graph.py visualize) so the navigator
picks up new labels. See docs/DEV/readme-i18n.md §2a.

Usage:
    python scripts/apply_content_locale.py            # apply
    python scripts/apply_content_locale.py --dry-run  # list what would change
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog_lock import read_catalog, update_catalog  # noqa: E402

SECTIONS = ("primitives", "concepts", "applications")


def _labels_for(content: dict, domain: str, node: str) -> dict | None:
    scoped = (((content.get("domains") or {}).get(domain) or {}).get("concepts") or {}).get(node)
    return scoped or (content.get("concepts") or {}).get(node)


def _scalar(value: str) -> str:
    """A YAML scalar for `value`: plain when safe, quoted otherwise."""
    out = yaml.safe_dump(value, allow_unicode=True, width=10**9, default_flow_style=False)
    return out.removesuffix("\n...\n").rstrip("\n")


def _block_end(lines: list[str], after: int, stop: int) -> int:
    """First line index in [after, stop) that is not part of the value block
    ending before `stop` — i.e. `stop` pulled back over trailing blank and
    comment lines, so an insertion lands next to the node, not after them."""
    end = stop
    while end > after and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return end


def _label_edits(text: str, graph, want_for) -> list[tuple[int, int, list[str], str]]:
    """Line edits (start, end, new_lines, node) that set each node's `labels:`.

    Only the `labels:` block is written; every other line — including how the
    file wraps long `defines` text — stays byte-for-byte as it was.
    """
    lines = text.splitlines(keepends=True)
    # Line where each top-level section / node starts, to bound the last key.
    starts = sorted([graph.lc.key(k)[0] for k in graph] +
                    [sec.lc.key(n)[0] for k in graph if isinstance(sec := graph[k], dict) for n in sec])
    def next_start(line: int) -> int:
        return next((s for s in starts if s > line), len(lines))

    edits = []
    for section in SECTIONS:
        nodes = graph.get(section) or {}
        for node, attrs in nodes.items():
            want = want_for(node)
            if not want or not isinstance(attrs, dict) or dict(attrs.get("labels") or {}) == dict(want):
                continue
            keys = list(attrs)
            col = attrs.lc.key(keys[0])[1]
            block = [" " * col + "labels:\n"] + \
                    [" " * (col + 2) + f"{lang}: {_scalar(str(v))}\n" for lang, v in want.items()]
            node_line = nodes.lc.key(node)[0]
            if "labels" in attrs:
                i = keys.index("labels")
                start = attrs.lc.key("labels")[0]
                stop = attrs.lc.key(keys[i + 1])[0] if i + 1 < len(keys) else next_start(node_line)
                edits.append((start, _block_end(lines, start + 1, stop), block, node))
            else:  # insert right after `defines`, where authors look for it
                if "defines" in keys and keys.index("defines") + 1 < len(keys):
                    at = attrs.lc.key(keys[keys.index("defines") + 1])[0]
                elif "defines" in keys:
                    at = _block_end(lines, attrs.lc.key("defines")[0] + 1, next_start(node_line))
                else:
                    at = attrs.lc.key(keys[0])[0]
                edits.append((at, at, block, node))
    return edits


def apply_graphs(content: dict, domains_dir: Path, dry_run: bool) -> list[Path]:
    """Returns the graph.yaml files that changed (or would, with dry_run) —
    their graph.html needs re-rendering to show the new labels."""
    changed: list[Path] = []
    for gy in sorted(domains_dir.rglob("input/graph.yaml")):
        domain = gy.parent.parent.name
        text = gy.read_text(encoding="utf-8")
        graph = YAML().load(text)  # round-trip load, for line positions only
        edits = _label_edits(text, graph, lambda node: _labels_for(content, domain, node))
        if not edits:
            continue
        changed.append(gy)
        names = [e[3] for e in edits]
        click.echo(f"  {domain}/input/graph.yaml: {len(names)} node(s) — "
                   + ", ".join(names[:6]) + (" …" if len(names) > 6 else ""))
        if dry_run:
            continue
        lines = text.splitlines(keepends=True)
        for start, end, block, _ in sorted(edits, reverse=True):
            lines[start:end] = block
        new = "".join(lines)
        # The edit must only have touched labels.
        before, after = yaml.safe_load(text), yaml.safe_load(new)
        for section in SECTIONS:
            for node, attrs in (after.get(section) or {}).items():
                old = dict((before.get(section) or {}).get(node) or {})
                old.pop("labels", None)
                cur = dict(attrs or {})
                cur.pop("labels", None)
                assert old == cur, f"{gy}: edit changed more than labels of {node}"
        gy.write_text(new, encoding="utf-8")
    return changed


def apply_catalog(content: dict, catalog_path: Path, dry_run: bool) -> int:
    source = (content.get("_meta") or {}).get("source", "en")
    domains = content.get("domains") or {}

    def entry_update(entry: dict) -> dict:
        text = domains.get(entry.get("id")) or {}
        new = {}
        i18n = {k: dict(v) for k, v in (entry.get("i18n") or {}).items()}
        for field in ("name", "description"):
            for lang, val in (text.get(field) or {}).items():
                if lang == source:
                    new[field] = val
                else:
                    i18n.setdefault(lang, {})[field] = val
        if i18n:
            new["i18n"] = i18n
        return {k: v for k, v in new.items() if entry.get(k) != v}

    pending = {e["id"]: entry_update(e) for e in read_catalog(catalog_path)}
    pending = {k: v for k, v in pending.items() if v}
    for did, upd in pending.items():
        click.echo(f"  catalog.json: {did} — {', '.join(sorted(upd))}")
    if pending and not dry_run:
        def mutate(catalog: list[dict]) -> None:
            for entry in catalog:
                entry.update(entry_update(entry))
        update_catalog(mutate, catalog_path)
    return len(pending)


@click.command()
@click.option("--content", "content_path", type=click.Path(path_type=Path),
              default=ROOT / "locales" / "content.yaml", show_default=True)
@click.option("--domains-dir", type=click.Path(path_type=Path),
              default=ROOT / "public" / "domains", show_default=True)
@click.option("--dry-run", is_flag=True, help="List changes without writing.")
def main(content_path: Path, domains_dir: Path, dry_run: bool) -> None:
    if not content_path.exists():
        sys.exit(f"{content_path} not found")
    content = yaml.safe_load(content_path.read_text(encoding="utf-8")) or {}
    n_graph = len(apply_graphs(content, domains_dir, dry_run))
    n_cat = apply_catalog(content, domains_dir / "catalog.json", dry_run)
    verb = "would change" if dry_run else "changed"
    click.echo(f"{verb}: {n_graph} graph.yaml file(s), {n_cat} catalog entr(y/ies)")


if __name__ == "__main__":
    main()
