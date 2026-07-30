#!/usr/bin/env python3
"""Sync ingested chapters from concept-book-press into public/domains/.

concept-book-press's pipeline (ingest -> extract -> validate) produces one
graph.yaml + concept_sources.yaml per chapter under
concept-book-press/output/{book}/ch{N}/. This script copies those into a
concept-book domain directory, renders output/graph.html so the graph is
browsable immediately, and registers/refreshes a catalog.json entry with
has_book=False (no concept-book HTML has been generated yet — that's a
separate, LLM-driven step via batch_generate.py / spl).

Usage:
    python scripts/sync_from_press.py --book college-physics-2e --prefix college_physics_ch
    python scripts/sync_from_press.py --book college-physics-2e --chapters 3-34
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRESS_ROOT = Path.home() / "projects" / "digital-duck" / "concept-book-press"
DOMAINS_ROOT = REPO_ROOT / "public" / "domains"
CATALOG_PATH = DOMAINS_ROOT / "catalog.json"
GRAPH_TOOL = REPO_ROOT / "scripts" / "concept_graph.py"


def _graph_stats(graph_yaml: dict) -> dict:
    primitives = graph_yaml.get("primitives", {}) or {}
    concepts = graph_yaml.get("concepts", {}) or {}
    applications = graph_yaml.get("applications", {}) or {}
    edges = sum(len(v.get("composed_of", []) or []) for v in concepts.values())
    edges += sum(len(v.get("needs", []) or []) for v in applications.values())
    return {
        "nodes": len(primitives) + len(concepts) + len(applications),
        "edges": edges,
        "primitives": len(primitives),
        "concepts": len(concepts),
        "applications": len(applications),
    }


def _chapter_title(chunks_path: Path, chapter: int) -> str:
    if not chunks_path.exists():
        return f"Chapter {chapter}"
    title = yaml.safe_load(chunks_path.read_text(encoding="utf-8")).get("chapter_title") or f"Chapter {chapter}"
    # "Chapter 3 Two-Dimensional Kinematics" -> "Two-Dimensional Kinematics"
    prefix = f"Chapter {chapter} "
    return title[len(prefix):] if title.startswith(prefix) else title


def _pick_capstone(graph_yaml: dict) -> str | None:
    apps = graph_yaml.get("applications", {}) or {}
    if apps:
        return next(iter(apps))
    concepts = graph_yaml.get("concepts", {}) or {}
    if not concepts:
        return None
    return max(concepts, key=lambda k: concepts[k].get("tier", 0))


def sync_chapter(book: str, chapter: int, domain_prefix: str, dry_run: bool) -> dict | None:
    src_dir = PRESS_ROOT / "output" / book / f"ch{chapter}"
    graph_src = src_dir / "graph.yaml"
    if not graph_src.exists():
        print(f"  ch{chapter}: SKIP (no graph.yaml at {graph_src})")
        return None

    # Zero-padded so plain string sort (used by the frontend's domain
    # dropdowns) matches chapter order: ch01..ch09, ch10..ch34.
    domain_id = f"{domain_prefix}{chapter:02d}"
    dest_dir = DOMAINS_ROOT / domain_id
    input_dir = dest_dir / "input"

    graph_yaml = yaml.safe_load(graph_src.read_text(encoding="utf-8"))
    stats = _graph_stats(graph_yaml)
    title = _chapter_title(src_dir / "chunks.yaml", chapter)
    capstone = _pick_capstone(graph_yaml)

    print(f"  ch{chapter}: {domain_id}  \"{title}\"  "
          f"(nodes={stats['nodes']} edges={stats['edges']} capstone={capstone})")

    if dry_run:
        return None

    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "graph.yaml").write_text(graph_src.read_text(encoding="utf-8"), encoding="utf-8")
    sources_src = src_dir / "concept_sources.yaml"
    if sources_src.exists():
        (input_dir / "concept_sources.yaml").write_text(sources_src.read_text(encoding="utf-8"), encoding="utf-8")

    graph_html = dest_dir / "output" / "graph.html"
    graph_html.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(GRAPH_TOOL), "--domain", str(input_dir / "graph.yaml"),
         "visualize", "--format", "html", "--output", str(graph_html)],
        check=True, cwd=str(REPO_ROOT),
    )

    return {
        "id": domain_id,
        "name": f"Physics Ch{chapter}: {title}",
        "description": f"OpenStax College Physics 2e, Chapter {chapter}: {title}.",
        "capstone": capstone or "",
        **stats,
        "tags": ["science"],
        "default_level": "college",
        "has_navigator": True,
        "has_book": False,
        "books": [],
        "generated_concepts": [],
    }


def _parse_chapters(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-")
            out.extend(range(int(lo), int(hi) + 1))
        elif part:
            out.append(int(part))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True, help="concept-book-press book slug, e.g. college-physics-2e")
    ap.add_argument("--prefix", required=True, help="domain id prefix, e.g. college_physics_ch")
    ap.add_argument("--chapters", default=None, help="e.g. '3-34' or '1,3,5' — default: all available")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    book_dir = PRESS_ROOT / "output" / args.book
    if args.chapters:
        chapters = _parse_chapters(args.chapters)
    else:
        chapters = sorted(
            int(p.name[2:]) for p in book_dir.glob("ch*") if p.is_dir() and p.name[2:].isdigit()
        )

    print(f"Source : {book_dir}")
    print(f"Dest   : {DOMAINS_ROOT}")
    print(f"Chapters: {chapters}")
    print()

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if CATALOG_PATH.exists() else []
    by_id = {e["id"]: e for e in catalog}
    added, refreshed = 0, 0

    for ch in chapters:
        entry = sync_chapter(args.book, ch, args.prefix, args.dry_run)
        if entry is None:
            continue
        if entry["id"] in by_id:
            existing = by_id[entry["id"]]
            # Preserve anything book-generation has already populated.
            entry["has_book"] = existing.get("has_book", False)
            entry["books"] = existing.get("books", [])
            entry["generated_concepts"] = existing.get("generated_concepts", [])
            existing.update(entry)
            refreshed += 1
        else:
            catalog.append(entry)
            by_id[entry["id"]] = entry
            added += 1

    if not args.dry_run:
        CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"{'(dry run) ' if args.dry_run else ''}catalog: {added} added, {refreshed} refreshed")


if __name__ == "__main__":
    main()
