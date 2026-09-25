#!/usr/bin/env python3
"""Check i18n coverage and YAML hygiene. See docs/DEV/readme-i18n.md (Phase 5).

Errors (exit 1) are things that break or silently misbehave:
  - a t()/i18n()/data-t key used in src/ that ui.yaml doesn't define
  - a translation whose {placeholders} differ from the source language's
  - a leaf missing the source language, a non-string key (YAML 1.1 reads
    `no`/`yes`/`on`/`off` as booleans), or a value YAML parsed as a mapping
    (an unquoted value starting with `{`)
Warnings (exit 0, or 1 with --strict) are gaps the fallback chain covers:
  - UI strings, node labels or catalog chapter text missing in a language
  - a zh label with no CJK characters, an en label that still contains `_` (a raw id)
  - locales/content.yaml out of sync with graph.yaml / catalog.json (rebuild)

Languages checked are ui.yaml's `_meta.languages` (the UI locales).

Usage:
    python scripts/check_i18n.py            # report
    python scripts/check_i18n.py --strict   # warnings fail too (CI)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click
import yaml

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = re.compile(r"\{(\w+)\}")
CJK = re.compile(r"[㐀-鿿]")
# Keys used from src/: t('k'), t("k"), t(`k`), i18n(el, 'k'), data-t="k",
# data-t-title="k", data-t-placeholder="k". A template key such as
# t(`level.${l}`) counts as a use of every key under its static prefix.
USE_PATTERNS = [
    re.compile(r"""\bt\(\s*(['"`])([\w.${}]+)\1"""),
    # first argument may hold one level of parens: i18n(document.createElement('span'), 'k')
    re.compile(r"""\bi18n\(\s*[^,()]*(?:\([^()]*\))?\s*,\s*(['"`])([\w.${}]+)\1"""),
    re.compile(r"""\bdata-t(?:-title|-placeholder)?=(["'])([\w.]+)\1"""),
]
# Any string literal shaped like a dotted key also counts as a use when the key
# exists (keys passed through helpers, e.g. makeSelect(..., 'panel.model')).
LITERAL = re.compile(r"""(['"`])([a-z_]+(?:\.\w+)+)\1""")
# Keys read outside src/ (spl/tools.py) or only through a helper.
EXTERNAL_PREFIXES = ("book.", "tag.")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        # e.g. an unquoted value starting with `{`: `ja: {n} ノード` is not valid YAML
        click.echo(f"  ✗ {path.relative_to(ROOT)}: YAML parse error — {e}".replace("\n", " "), err=True)
        click.echo("    (quote values that start with { [ : or @)", err=True)
        sys.exit(1)


def _leaves(node, prefix: str, rep: Report, where: str) -> dict[str, dict]:
    """Flatten like src/i18n.js: a leaf is a mapping whose values are all strings."""
    out: dict[str, dict] = {}
    for k, v in node.items():
        if not isinstance(k, str):
            rep.error(f"{where}: key {k!r} under '{prefix or '<root>'}' is not a string "
                      f"(YAML 1.1 reads no/yes/on/off as booleans — quote it)")
            continue
        key = f"{prefix}.{k}" if prefix else k
        if not isinstance(v, dict):
            rep.error(f"{where}: '{key}' should map languages to text, got {type(v).__name__}")
            continue
        kinds = {isinstance(x, str) for x in v.values()}
        if kinds == {True}:
            out[key] = v
        elif kinds == {True, False}:
            bad = [lang for lang, x in v.items() if not isinstance(x, str)]
            rep.error(f"{where}: '{key}' has non-text values for {bad} — "
                      f"quote values that start with {{ [ : or @")
        else:
            out.update(_leaves(v, key, rep, where))
    return out


def _check_leaves(leaves: dict[str, dict], langs: list[str], source: str,
                  rep: Report, where: str) -> None:
    missing: dict[str, list[str]] = {lang: [] for lang in langs}
    for key, texts in leaves.items():
        bad = [lang for lang in texts if not isinstance(lang, str)]
        if bad:
            rep.error(f"{where}: '{key}' has language key(s) {bad} that YAML read as "
                      f"non-strings (no/yes/on/off are booleans in YAML 1.1 — quote them)")
            texts = {k: v for k, v in texts.items() if isinstance(k, str)}
        if source not in texts:
            rep.error(f"{where}: '{key}' has no source-language ({source}) text")
            continue
        want = set(PLACEHOLDER.findall(texts[source]))
        for lang, text in texts.items():
            got = set(PLACEHOLDER.findall(text))
            if lang != source and got != want:
                rep.error(f"{where}: '{key}' [{lang}] placeholders {sorted(got)} ≠ "
                          f"{source} {sorted(want)}")
        for lang in langs:
            if lang not in texts:
                missing[lang].append(key)
    for lang, keys in missing.items():
        if keys:
            rep.warn(f"{where}: {len(keys)} key(s) missing [{lang}]: {', '.join(keys[:8])}"
                     + (" …" if len(keys) > 8 else ""))


def _used_keys(src: Path) -> tuple[dict[str, set[str]], set[str]]:
    """Map each key (or `prefix.*` for template keys) to the files using it,
    plus every dotted string literal (a looser "maybe used" set)."""
    used: dict[str, set[str]] = {}
    literals: set[str] = set()
    for f in sorted(src.rglob("*.js")):
        if f.name == "i18n.js":  # defines the API; its comments show example keys
            continue
        text = f.read_text(encoding="utf-8")
        literals.update(m.group(2) for m in LITERAL.finditer(text))
        for pat in USE_PATTERNS:
            for m in pat.finditer(text):
                key = m.group(2)
                if "${" in key:
                    key = key.split("${", 1)[0].rstrip(".") + ".*"
                used.setdefault(key, set()).add(str(f.relative_to(ROOT)))
    return used, literals


def check_ui(rep: Report, ui: dict) -> list[str]:
    meta = ui.get("_meta", {})
    source = meta.get("source", "en")
    langs = list((meta.get("languages") or {source: {}}).keys())
    tree = {k: v for k, v in ui.items() if k != "_meta"}
    leaves = _leaves(tree, "", rep, "ui.yaml")
    _check_leaves(leaves, langs, source, rep, "ui.yaml")

    used, literals = _used_keys(ROOT / "src")
    for key, files in sorted(used.items()):
        if key.endswith(".*"):
            if not any(k.startswith(key[:-1]) for k in leaves):
                rep.error(f"src: no ui.yaml keys under '{key}' (used in {', '.join(sorted(files))})")
        elif key not in leaves:
            rep.error(f"src: '{key}' is not defined in ui.yaml (used in {', '.join(sorted(files))})")
    prefixes = tuple(k[:-1] for k in used if k.endswith(".*")) + EXTERNAL_PREFIXES
    unused = [k for k in leaves
              if k not in used and k not in literals and not k.startswith(prefixes)]
    if unused:
        rep.warn(f"ui.yaml: {len(unused)} key(s) not used in src/: {', '.join(unused)}")
    return langs


def check_content(rep: Report, langs: list[str], content: dict | None) -> None:
    domains_dir = ROOT / "public" / "domains"
    concepts = (content or {}).get("concepts") or {}
    source = ((content or {}).get("_meta") or {}).get("source", "en")
    if content is not None:
        _check_leaves(_leaves({"concepts": concepts}, "", rep, "content.yaml"), langs, source,
                      rep, "content.yaml")
        dom_leaves = _leaves({"domains": content.get("domains") or {}}, "", rep, "content.yaml")
        _check_leaves(dom_leaves, langs, source, rep, "content.yaml")

    # Node labels as shipped (graph.yaml), per domain. Domains with no labels
    # at all (they show id-derived labels) are summarized in one line, so the
    # per-domain warnings point at partial gaps.
    unlabeled: list[str] = []
    for gy in sorted(domains_dir.rglob("input/graph.yaml")):
        dom = gy.parent.parent.name
        graph = _load(gy) or {}
        missing: dict[str, int] = {lang: 0 for lang in langs}
        nodes = 0
        for section in ("primitives", "concepts", "applications"):
            for nid, attrs in (graph.get(section) or {}).items():
                nodes += 1
                labels = (attrs or {}).get("labels") or {}
                for lang in langs:
                    if not labels.get(lang):
                        missing[lang] += 1
                if labels.get("zh") and not CJK.search(labels["zh"]):
                    rep.warn(f"{dom}: '{nid}' zh label {labels['zh']!r} has no CJK characters")
                if labels.get("en") and "_" in labels["en"]:
                    rep.warn(f"{dom}: '{nid}' en label {labels['en']!r} looks like a raw id")
                if nid in concepts and labels and labels != concepts[nid]:
                    rep.warn(f"{dom}: '{nid}' labels differ from content.yaml — rebuild graph.yaml")
        if nodes and all(n == nodes for n in missing.values()):
            unlabeled.append(dom)
            continue
        for lang, n in missing.items():
            if n:
                rep.warn(f"{dom}: {n}/{nodes} node(s) have no [{lang}] label")
    if unlabeled:
        rep.warn(f"{len(unlabeled)} domain(s) have no node labels at all (id-derived labels are "
                 f"shown): {', '.join(unlabeled[:5])}" + (" …" if len(unlabeled) > 5 else ""))

    # Chapter names/descriptions as shipped (catalog.json).
    catalog = json.loads((domains_dir / "catalog.json").read_text(encoding="utf-8"))
    content_domains = (content or {}).get("domains") or {}
    no_text: dict[str, list[str]] = {}
    for entry in catalog:
        did = entry.get("id")
        for lang in langs:
            if lang == source:
                continue
            got = (entry.get("i18n") or {}).get(lang) or {}
            for field in ("name", "description"):
                if not got.get(field):
                    no_text.setdefault(f"i18n.{lang}.{field}", []).append(did)
        want = content_domains.get(did)
        if want:
            for field in ("name", "description"):
                for lang, text in (want.get(field) or {}).items():
                    shipped = entry.get(field) if lang == source else \
                        ((entry.get("i18n") or {}).get(lang) or {}).get(field)
                    if shipped != text:
                        rep.warn(f"catalog.json: '{did}' {field} [{lang}] differs from "
                                 f"content.yaml — rebuild the catalog")
    for field, ids in no_text.items():
        rep.warn(f"catalog.json: {len(ids)}/{len(catalog)} domain(s) have no {field}: "
                 + ", ".join(ids[:5]) + (" …" if len(ids) > 5 else ""))


@click.command()
@click.option("--strict", is_flag=True, help="Treat warnings as errors (exit 1).")
def main(strict: bool) -> None:
    rep = Report()
    ui = _load(ROOT / "locales" / "ui.yaml")
    if ui is None:
        click.echo("locales/ui.yaml not found", err=True)
        sys.exit(1)
    langs = check_ui(rep, ui)
    check_content(rep, langs, _load(ROOT / "locales" / "content.yaml"))

    click.echo(f"Languages checked: {', '.join(langs)}")
    for msg in rep.errors:
        click.echo(f"  ✗ {msg}")
    for msg in rep.warnings:
        click.echo(f"  ! {msg}")
    click.echo(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    sys.exit(1 if rep.errors or (strict and rep.warnings) else 0)


if __name__ == "__main__":
    main()
